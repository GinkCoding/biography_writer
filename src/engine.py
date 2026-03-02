"""传记生成引擎主控"""
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Callable
from datetime import datetime
from loguru import logger

from src.config import settings
from src.llm_client import LLMClient
from src.models import (
    WritingStyle, BookOutline, BiographyBook,
    GeneratedChapter, GlobalState
)
from src.layers.data_ingestion import DataIngestionLayer, VectorStore
from src.layers.knowledge_memory import KnowledgeMemoryLayer, GlobalStateManager
from src.layers.planning import PlanningOrchestrationLayer
from src.layers.generation import IterativeGenerationLayer
from src.layers.review_output import ReviewOutputLayer
from src.version_control import GitManager
from src.utils import generate_id, save_json

# 导入可观测性模块
from src.observability import WorkflowTracer, MetricsCollector, HealthReporter
from src.observability.workflow_tracer import LayerType, TraceStatus


class BiographyEngine:
    """传记生成引擎"""

    def __init__(self):
        self.llm = LLMClient()
        self.vector_store = VectorStore()

        # 初始化各层
        self.data_layer = DataIngestionLayer()
        self.knowledge_layer = KnowledgeMemoryLayer(self.llm)
        self.planning_layer = PlanningOrchestrationLayer(self.llm)
        self.generation_layer = IterativeGenerationLayer(self.llm, self.vector_store)

        self.book_id: Optional[str] = None
        self.outline: Optional[BookOutline] = None
        self.timeline = None
        self.state_manager: Optional[GlobalStateManager] = None
        self.review_layer: Optional[ReviewOutputLayer] = None
        self.git_manager: Optional[GitManager] = None

        # 初始化可观测性组件
        self.tracer = WorkflowTracer()
        self.metrics = MetricsCollector()
        self.health_reporter = HealthReporter(
            tracer=self.tracer,
            collector=self.metrics
        )

        # 确保目录存在
        settings.ensure_dirs()

    async def initialize_from_interview(
        self,
        interview_file: Path,
        subject_hint: Optional[str] = None,
        style: WritingStyle = WritingStyle.LITERARY,
        target_words: Optional[int] = None
    ) -> str:
        """
        从采访文件初始化项目

        Returns:
            book_id: 项目ID
        """
        logger.info(f"开始初始化项目，采访文件: {interview_file}")

        # 生成项目ID
        self.book_id = generate_id(
            interview_file.stem,
            datetime.now().isoformat()
        )

        # 设置追踪上下文
        self.tracer.set_context(book_id=self.book_id)
        self.metrics.start_workflow(book_id=self.book_id)

        # 记录步骤开始
        self.tracer.trace_step_start(
            step_id="engine.initialize",
            step_name="初始化项目",
            expected_order=1,
            dependencies=[]
        )

        trace_id = self.tracer.start_trace(LayerType.ENGINE, "initialize_from_interview", {
            "interview_file": str(interview_file),
            "style": style.value,
            "target_words": target_words
        })

        try:
            # 1. 数据接入与解析
            logger.info("【第1层】数据接入与解析...")
            layer_trace = self.tracer.start_trace(LayerType.DATA_INGESTION, "process_interview")
            materials = await self.data_layer.process_interview(
                file_path=interview_file,
                subject_hint=subject_hint
            )
            self.tracer.end_trace(layer_trace, TraceStatus.COMPLETED, {
                "materials_count": len(materials) if materials else 0
            })

            if not materials:
                raise ValueError("未能从采访文件中提取有效素材")

            logger.info(f"素材处理完成，共 {len(materials)} 个文本块")

            # 2. 知识构建与全局记忆
            logger.info("【第2层】知识构建与全局记忆...")
            layer_trace = self.tracer.start_trace(LayerType.KNOWLEDGE_MEMORY, "build_knowledge_base")
            self.timeline, knowledge_graph, self.state_manager = \
                await self.knowledge_layer.build_knowledge_base(
                    materials=materials,
                    book_id=self.book_id,
                    subject_hint=subject_hint
                )
            self.tracer.end_trace(layer_trace, TraceStatus.COMPLETED)

            # 保存知识图谱
            kg_path = Path(settings.paths.cache_dir) / f"{self.book_id}_kg.json"
            save_json(knowledge_graph.to_dict(), kg_path)

            # 3. 规划与编排
            logger.info("【第3层】规划与编排...")
            layer_trace = self.tracer.start_trace(LayerType.PLANNING, "create_book_plan")
            self.outline = await self.planning_layer.create_book_plan(
                timeline=self.timeline,
                style=style,
                target_words=target_words
            )
            self.tracer.end_trace(layer_trace, TraceStatus.COMPLETED, {
                "total_chapters": self.outline.total_chapters,
                "target_words": self.outline.target_total_words
            })

            # 保存大纲
            outline_path = Path(settings.paths.cache_dir) / f"{self.book_id}_outline.json"
            save_json(self.outline.model_dump(), outline_path)

            logger.info(f"大纲生成完成: {self.outline.title}")
            logger.info(f"  - 章节数: {self.outline.total_chapters}")
            logger.info(f"  - 目标字数: {self.outline.target_total_words}")

            # 更新工作流指标
            self.metrics._workflow_metrics.total_chapters = self.outline.total_chapters

            # 初始化Git版本控制
            project_path = Path(settings.paths.output_dir) / self.book_id
            project_path.mkdir(parents=True, exist_ok=True)
            self.git_manager = GitManager(str(project_path))
            self.git_manager.init_repo()

            # 提交大纲
            self.git_manager.commit_outline(
                message=f"Initial outline for {self.outline.title}",
                outline_version="1.0"
            )

            # 初始化审校层
            self.review_layer = ReviewOutputLayer(
                llm=self.llm,
                timeline=self.timeline,
                output_dir=Path(settings.paths.output_dir)
            )

            # 标记步骤完成
            self.tracer.trace_step_complete("engine.initialize", {
                "book_id": self.book_id,
                "total_chapters": self.outline.total_chapters
            })
            self.tracer.end_trace(trace_id, TraceStatus.COMPLETED)

        except Exception as e:
            self.tracer.trace_step_failure("engine.initialize", str(e))
            self.tracer.end_trace(trace_id, TraceStatus.FAILED, error=str(e))
            raise

        return self.book_id

    async def generate_book(
        self,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> BiographyBook:
        """
        生成完整传记
        """
        if not self.outline or not self.state_manager:
            raise RuntimeError("请先调用 initialize_from_interview 初始化项目")

        logger.info(f"开始生成传记: {self.outline.title}")

        # 记录步骤开始
        self.tracer.trace_step_start(
            step_id="engine.generate_book",
            step_name="生成完整传记",
            expected_order=2,
            dependencies=["engine.initialize"]
        )

        trace_id = self.tracer.start_trace(LayerType.ENGINE, "generate_book", {
            "book_id": self.book_id,
            "total_chapters": len(self.outline.chapters)
        })

        chapters = []
        total_chapters = len(self.outline.chapters)

        try:
            for i, chapter_outline in enumerate(self.outline.chapters):
                chapter_num = i + 1

                # 更新状态
                self.state_manager.update_for_chapter(
                    chapter_order=chapter_num
                    
                )
                self.state_manager.save()

                # 获取生成上下文
                global_state = self.state_manager.get_context_for_generation()

                # 设置当前章节上下文
                self.tracer.set_context(book_id=self.book_id, chapter_num=chapter_num)

                # 4. 迭代生成
                logger.info(f"【第4层】生成第{chapter_num}/{total_chapters}章...")
                gen_trace = self.tracer.start_trace(LayerType.GENERATION, "generate_chapter", {
                    "chapter_num": chapter_num,
                    "chapter_title": chapter_outline.title
                })

                def on_progress(msg: str):
                    if progress_callback:
                        progress_callback(f"[{chapter_num}/{total_chapters}] {msg}")

                chapter = await self.generation_layer.generate_chapter(
                    chapter_outline=chapter_outline,
                    book_outline=self.outline,
                    global_state=global_state,
                    progress_callback=on_progress
                )

                self.tracer.end_trace(gen_trace, TraceStatus.COMPLETED, {
                    "word_count": chapter.word_count,
                    "section_count": len(chapter.sections)
                })

                # 5. 审校
                logger.info(f"【第5层】审查第{chapter_num}章...")
                review_trace = self.tracer.start_trace(LayerType.REVIEW_OUTPUT, "review_chapter", {
                    "chapter_num": chapter_num
                })
                chapter_context = {
                    "time_period_start": chapter_outline.time_period_start,
                    "time_period_end": chapter_outline.time_period_end,
                    "style": self.outline.style.value if self.outline else "literary",
                    "subject_name": self.outline.subject_name if self.outline else "",
                    "chapter_num": chapter_num,
                }

                # 获取前一章用于跨章节一致性检查
                previous_chapter = chapters[-1] if chapters else None

                chapter = await self.review_layer.review_chapter(
                    chapter=chapter,
                    chapter_context=chapter_context,
                    previous_chapter=previous_chapter
                )

                self.tracer.end_trace(review_trace, TraceStatus.COMPLETED)

                chapters.append(chapter)

                # 更新状态
                chapter_summary = f"{chapter_outline.title}({chapter.word_count}字)"
                self.state_manager.add_chapter_summary(chapter_summary)
                self.state_manager.save()

                # Git提交章节
                if self.git_manager:
                    self.git_manager.commit_chapter(
                        chapter_num=chapter_num,
                        chapter_title=chapter_outline.title,
                        word_count=chapter.word_count
                    )

                logger.info(f"第{chapter_num}章完成，字数: {chapter.word_count}")

                # 记录章节完成指标
                self.metrics.record_chapter_complete(chapter_num, chapter.word_count)

                # 记录小节完成
                for section in chapter.sections:
                    self.metrics.record_section_complete()

            # 构建完整书籍
            book = BiographyBook(
                id=self.book_id,
                outline=self.outline,
                chapters=chapters
            )

            logger.info(f"传记生成完成！")
            logger.info(f"  - 总章节: {len(chapters)}")
            logger.info(f"  - 总字数: {book.total_word_count}")

            # 标记步骤完成
            self.tracer.trace_step_complete("engine.generate_book", {
                "total_chapters": len(chapters),
                "total_word_count": book.total_word_count
            })
            self.tracer.end_trace(trace_id, TraceStatus.COMPLETED)

            # 结束工作流指标收集
            self.metrics.end_workflow()

            # 生成健康报告
            try:
                report = self.health_reporter.generate_report(book_id=self.book_id)
                logger.info(f"健康报告已生成，评分: {report.health_score:.1f}/100")
            except Exception as e:
                logger.warning(f"生成健康报告失败: {e}")

            return book

        except Exception as e:
            self.tracer.trace_step_failure("engine.generate_book", str(e))
            self.tracer.end_trace(trace_id, TraceStatus.FAILED, error=str(e))
            raise
