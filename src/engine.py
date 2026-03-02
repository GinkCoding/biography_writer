"""传记生成引擎主控."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from loguru import logger

from src.config import settings
from src.layers.data_ingestion import DataIngestionLayer, VectorStore
from src.layers.generation import IterativeGenerationLayer
from src.layers.knowledge_memory import GlobalStateManager, KnowledgeMemoryLayer
from src.layers.planning import PlanningOrchestrationLayer
from src.layers.review_output import ReviewOutputLayer
from src.llm_client import LLMClient
from src.models import (
    BiographyBook,
    BookOutline,
    CharacterProfile,
    GeneratedChapter,
    Timeline,
    WritingStyle,
)
from src.observability import HealthReporter, MetricsCollector, WorkflowTracer
from src.observability.logging_setup import setup_application_logging
from src.observability.runtime_monitor import get_runtime_monitor
from src.observability.workflow_tracer import LayerType, TraceStatus
from src.utils import generate_id, save_json, truncate_text
from src.version_control import GitManager


class BiographyEngine:
    """传记生成引擎."""

    def __init__(self):
        setup_application_logging()
        settings.ensure_dirs()

        self.llm = LLMClient()
        self.vector_store = VectorStore()

        # 初始化各层
        self.data_layer = DataIngestionLayer()
        self.knowledge_layer = KnowledgeMemoryLayer(self.llm)
        self.planning_layer = PlanningOrchestrationLayer(self.llm)
        self.generation_layer = IterativeGenerationLayer(self.llm, self.vector_store)

        self.book_id: Optional[str] = None
        self.outline: Optional[BookOutline] = None
        self.timeline: Optional[Timeline] = None
        self.state_manager: Optional[GlobalStateManager] = None
        self.review_layer: Optional[ReviewOutputLayer] = None
        self.git_manager: Optional[GitManager] = None
        self._last_health_report: Optional[Dict[str, Any]] = None
        self.run_id: Optional[str] = None

        # 可观测性组件
        self.tracer = WorkflowTracer(project_root=Path(__file__).parent.parent)
        self.metrics = MetricsCollector(project_root=Path(__file__).parent.parent)
        self.health_reporter = HealthReporter(
            project_root=Path(__file__).parent.parent,
            tracer=self.tracer,
            collector=self.metrics,
        )
        self.runtime_monitor = get_runtime_monitor(project_root=Path(__file__).parent.parent)

    def _emit_progress(
        self,
        message: str,
        progress_callback: Optional[Callable[[str], None]] = None,
        stage: Optional[str] = None,
        status: str = "running",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        logger.info(message)
        if progress_callback:
            try:
                progress_callback(message)
            except Exception:
                pass
        if stage:
            self.runtime_monitor.log_event(
                stage=stage,
                status=status,
                message=message,
                metadata=metadata or {},
            )

    def _ensure_review_layer(self) -> None:
        if self.review_layer is not None:
            return
        if self.timeline is None:
            subject_name = self.outline.subject_name if self.outline else "传主"
            self.timeline = Timeline(subject=CharacterProfile(name=subject_name), events=[])
        self.review_layer = ReviewOutputLayer(
            llm=self.llm,
            timeline=self.timeline,
            output_dir=Path(settings.paths.output_dir),
        )

    def _build_materials_summary(self, materials: list[Any]) -> list[Dict[str, Any]]:
        summary = []
        for item in materials:
            content = getattr(item, "content", "")
            summary.append(
                {
                    "id": getattr(item, "id", ""),
                    "source_file": getattr(item, "source_file", ""),
                    "chunk_index": getattr(item, "chunk_index", 0),
                    "topics": getattr(item, "topics", []),
                    "time_references": getattr(item, "time_references", []),
                    "content_preview": truncate_text(content, 200),
                    "content_length": len(content),
                }
            )
        return summary

    def _ensure_runtime_run(self, workflow: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        current = self.runtime_monitor.get_current_status()
        should_start = (
            not self.runtime_monitor.has_active_run()
            or current.get("book_id") != self.book_id
        )
        if not should_start:
            self.run_id = current.get("run_id")
            return

        if not self.book_id:
            return
        payload = {"workflow": workflow}
        if metadata:
            payload.update(metadata)
        self.run_id = self.runtime_monitor.start_run(self.book_id, metadata=payload)

    async def initialize_from_interview(
        self,
        interview_file: Path,
        subject_hint: Optional[str] = None,
        style: WritingStyle = WritingStyle.LITERARY,
        target_words: Optional[int] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """从采访文件初始化项目并生成大纲."""
        self.llm.set_progress_callback(progress_callback)
        self.book_id = generate_id(interview_file.stem, datetime.now().isoformat())
        self.run_id = self.runtime_monitor.start_run(
            self.book_id,
            metadata={
                "interview_file": str(interview_file),
                "style": style.value,
                "target_words": target_words,
            },
        )
        current_runtime_status = self.runtime_monitor.get_current_status()
        self._emit_progress(
            f"开始初始化项目: {interview_file}",
            progress_callback=progress_callback,
            stage="engine.initialize",
            status="started",
        )
        self._emit_progress(
            "运行监控已启动",
            progress_callback=progress_callback,
            stage="engine.initialize",
            metadata={
                "run_id": self.run_id,
                "status_file": current_runtime_status.get("status_file"),
                "events_file": current_runtime_status.get("events_file"),
            },
        )

        self.tracer.set_context(book_id=self.book_id)
        self.metrics.start_workflow(book_id=self.book_id)
        self.tracer.trace_step_start(
            step_id="engine.initialize",
            step_name="初始化项目",
            expected_order=1,
            dependencies=[],
        )
        trace_id = self.tracer.start_trace(
            LayerType.ENGINE,
            "initialize_from_interview",
            {
                "interview_file": str(interview_file),
                "style": style.value,
                "target_words": target_words,
            },
        )

        try:
            self._emit_progress("第1层/5: 数据接入与解析", progress_callback, stage="data_ingestion")
            layer_trace = self.tracer.start_trace(LayerType.DATA_INGESTION, "process_interview")
            materials = await self.data_layer.process_interview(
                file_path=interview_file,
                subject_hint=subject_hint,
            )
            self.tracer.end_trace(
                layer_trace,
                TraceStatus.COMPLETED,
                {"materials_count": len(materials) if materials else 0},
            )
            if not materials:
                raise ValueError("未能从采访文件中提取有效素材")

            self.runtime_monitor.save_json_artifact(
                name="materials_summary.json",
                data=self._build_materials_summary(materials),
                stage="01_data_ingestion",
            )

            self._emit_progress("第2层/5: 知识构建与全局记忆", progress_callback, stage="knowledge_memory")
            layer_trace = self.tracer.start_trace(LayerType.KNOWLEDGE_MEMORY, "build_knowledge_base")
            self.timeline, knowledge_graph, self.state_manager = await self.knowledge_layer.build_knowledge_base(
                materials=materials,
                book_id=self.book_id,
                subject_hint=subject_hint,
            )
            self.tracer.end_trace(layer_trace, TraceStatus.COMPLETED)

            kg_path = Path(settings.paths.cache_dir) / f"{self.book_id}_kg.json"
            save_json(knowledge_graph.to_dict(), kg_path)
            self.runtime_monitor.save_json_artifact(
                name="knowledge_graph.json",
                data=knowledge_graph.to_dict(),
                stage="02_knowledge_memory",
            )

            timeline_path = Path(settings.paths.cache_dir) / f"{self.book_id}_timeline.json"
            save_json(self.timeline.model_dump(), timeline_path)
            self.runtime_monitor.save_json_artifact(
                name="timeline.json",
                data=self.timeline.model_dump(),
                stage="02_knowledge_memory",
            )

            self._emit_progress("第3层/5: 规划与编排", progress_callback, stage="planning")
            layer_trace = self.tracer.start_trace(LayerType.PLANNING, "create_book_plan")
            self.outline = await self.planning_layer.create_book_plan(
                timeline=self.timeline,
                style=style,
                target_words=target_words,
            )
            self.tracer.end_trace(
                layer_trace,
                TraceStatus.COMPLETED,
                {
                    "total_chapters": self.outline.total_chapters,
                    "target_words": self.outline.target_total_words,
                },
            )

            outline_path = Path(settings.paths.cache_dir) / f"{self.book_id}_outline.json"
            save_json(self.outline.model_dump(), outline_path)
            self.runtime_monitor.save_json_artifact(
                name="outline.json",
                data=self.outline.model_dump(),
                stage="03_planning",
            )

            if self.metrics._workflow_metrics:
                self.metrics._workflow_metrics.total_chapters = self.outline.total_chapters

            project_path = Path(settings.paths.output_dir) / self.book_id
            project_path.mkdir(parents=True, exist_ok=True)
            self.git_manager = GitManager(str(project_path))
            self.git_manager.init_repo()
            self.git_manager.commit_outline(
                message=f"Initial outline for {self.outline.title}",
                outline_version="1.0",
            )

            self._ensure_review_layer()

            self.tracer.trace_step_complete(
                "engine.initialize",
                {"book_id": self.book_id, "total_chapters": self.outline.total_chapters},
            )
            self.tracer.end_trace(trace_id, TraceStatus.COMPLETED)
            self._emit_progress(
                f"初始化完成: {self.outline.title} ({self.outline.total_chapters}章)",
                progress_callback,
                stage="engine.initialize",
                status="completed",
            )
            return self.book_id

        except Exception as exc:
            self.tracer.trace_step_failure("engine.initialize", str(exc))
            self.tracer.end_trace(trace_id, TraceStatus.FAILED, error=str(exc))
            self.runtime_monitor.end_run(status="failed", error=str(exc))
            raise
        finally:
            self.llm.set_progress_callback(None)

    async def generate_book(
        self,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> BiographyBook:
        """生成完整传记."""
        if not self.outline or not self.state_manager:
            raise RuntimeError("请先调用 initialize_from_interview 初始化项目")

        self._ensure_runtime_run(
            workflow="generate_book",
            metadata={"total_chapters": len(self.outline.chapters)},
        )
        self._ensure_review_layer()
        self.llm.set_progress_callback(progress_callback)

        self.tracer.trace_step_start(
            step_id="engine.generate_book",
            step_name="生成完整传记",
            expected_order=2,
            dependencies=["engine.initialize"],
        )
        trace_id = self.tracer.start_trace(
            LayerType.ENGINE,
            "generate_book",
            {"book_id": self.book_id, "total_chapters": len(self.outline.chapters)},
        )
        self._emit_progress(
            f"开始生成: {self.outline.title}",
            progress_callback,
            stage="engine.generate_book",
            status="started",
            metadata={
                "run_id": self.run_id,
                "status_file": self.runtime_monitor.get_current_status().get("status_file"),
                "events_file": self.runtime_monitor.get_current_status().get("events_file"),
            },
        )

        chapters = []
        total_chapters = len(self.outline.chapters)

        try:
            for i, chapter_outline in enumerate(self.outline.chapters):
                chapter_num = i + 1
                self.state_manager.update_for_chapter(
                    chapter_order=chapter_num,
                    chapter_time_start=chapter_outline.time_period_start,
                    chapter_time_end=chapter_outline.time_period_end,
                )
                self.state_manager.save()
                global_state = self.state_manager.get_context_for_generation()
                self.tracer.set_context(book_id=self.book_id, chapter_num=chapter_num)

                self._emit_progress(
                    f"第4层/5: 生成第{chapter_num}/{total_chapters}章 - {chapter_outline.title}",
                    progress_callback,
                    stage="generation",
                    metadata={"chapter_num": chapter_num},
                )
                gen_trace = self.tracer.start_trace(
                    LayerType.GENERATION,
                    "generate_chapter",
                    {"chapter_num": chapter_num, "chapter_title": chapter_outline.title},
                )

                def on_progress(msg: str) -> None:
                    merged = f"[{chapter_num}/{total_chapters}] {msg}"
                    self._emit_progress(
                        merged,
                        progress_callback,
                        stage="generation.progress",
                        metadata={"chapter_num": chapter_num},
                    )

                chapter = await self.generation_layer.generate_chapter(
                    chapter_outline=chapter_outline,
                    book_outline=self.outline,
                    global_state=global_state,
                    progress_callback=on_progress,
                )
                self.tracer.end_trace(
                    gen_trace,
                    TraceStatus.COMPLETED,
                    {"word_count": chapter.word_count, "section_count": len(chapter.sections)},
                )
                self.runtime_monitor.save_json_artifact(
                    name=f"chapter_{chapter_num:02d}_generated.json",
                    data=chapter.model_dump(),
                    stage="04_generation",
                )

                self._emit_progress(
                    f"第5层/5: 审校第{chapter_num}章",
                    progress_callback,
                    stage="review",
                    metadata={"chapter_num": chapter_num},
                )
                review_trace = self.tracer.start_trace(
                    LayerType.REVIEW_OUTPUT,
                    "review_chapter",
                    {"chapter_num": chapter_num},
                )
                chapter_context = {
                    "time_period_start": chapter_outline.time_period_start,
                    "time_period_end": chapter_outline.time_period_end,
                    "style": self.outline.style.value if self.outline else "literary",
                    "subject_name": self.outline.subject_name if self.outline else "",
                    "chapter_num": chapter_num,
                }
                previous_chapter = chapters[-1] if chapters else None
                chapter = await self.review_layer.review_chapter(
                    chapter=chapter,
                    chapter_context=chapter_context,
                    previous_chapter=previous_chapter,
                )
                self.tracer.end_trace(review_trace, TraceStatus.COMPLETED)
                self.runtime_monitor.save_json_artifact(
                    name=f"chapter_{chapter_num:02d}_reviewed.json",
                    data=chapter.model_dump(),
                    stage="05_review",
                )

                chapters.append(chapter)
                chapter_summary = f"{chapter_outline.title}({chapter.word_count}字)"
                self.state_manager.add_chapter_summary(chapter_summary)
                self.state_manager.save()

                if self.git_manager:
                    self.git_manager.commit_chapter(
                        chapter_num=chapter_num,
                        chapter_title=chapter_outline.title,
                        word_count=chapter.word_count,
                    )

                self.metrics.record_chapter_complete(chapter_num, chapter.word_count)
                for _ in chapter.sections:
                    self.metrics.record_section_complete()

                self._emit_progress(
                    f"第{chapter_num}章完成，字数: {chapter.word_count}",
                    progress_callback,
                    stage="generation",
                    status="completed",
                    metadata={"chapter_num": chapter_num, "word_count": chapter.word_count},
                )

            book = BiographyBook(id=self.book_id, outline=self.outline, chapters=chapters)
            self.runtime_monitor.save_json_artifact(
                name="book_summary.json",
                data={
                    "book_id": book.id,
                    "title": book.outline.title,
                    "total_chapters": len(book.chapters),
                    "total_word_count": book.total_word_count,
                },
                stage="06_output",
            )

            self.tracer.trace_step_complete(
                "engine.generate_book",
                {"total_chapters": len(chapters), "total_word_count": book.total_word_count},
            )
            self.tracer.end_trace(trace_id, TraceStatus.COMPLETED)
            self.metrics.end_workflow()

            try:
                report = self.health_reporter.generate_report(book_id=self.book_id)
                self._last_health_report = report.to_dict()
                self.runtime_monitor.save_json_artifact(
                    name="health_report.json",
                    data=self._last_health_report,
                    stage="99_health",
                )
                logger.info(f"健康报告已生成，评分: {report.health_score:.1f}/100")
            except Exception as exc:
                logger.warning(f"生成健康报告失败: {exc}")

            self.runtime_monitor.end_run(status="completed")
            return book

        except Exception as exc:
            self.tracer.trace_step_failure("engine.generate_book", str(exc))
            self.tracer.end_trace(trace_id, TraceStatus.FAILED, error=str(exc))
            self.runtime_monitor.end_run(status="failed", error=str(exc))
            raise
        finally:
            self.llm.set_progress_callback(None)

    async def generate_single_chapter(
        self,
        chapter_number: int,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> GeneratedChapter:
        """生成单章（用于测试与增量生成）."""
        if not self.outline or not self.state_manager:
            raise RuntimeError("项目未初始化，请先运行 init 或 load_project")
        self._ensure_runtime_run(
            workflow="generate_single_chapter",
            metadata={"chapter_number": chapter_number},
        )
        self._ensure_review_layer()
        self.llm.set_progress_callback(progress_callback)

        chapter_outline = next((c for c in self.outline.chapters if c.order == chapter_number), None)
        if not chapter_outline:
            raise ValueError(f"未找到第{chapter_number}章")

        self.state_manager.update_for_chapter(chapter_order=chapter_number)
        self.state_manager.save()
        global_state = self.state_manager.get_context_for_generation()

        def on_progress(msg: str) -> None:
            self._emit_progress(
                f"[chapter {chapter_number}] {msg}",
                progress_callback,
                stage="generation.progress",
                metadata={"chapter_num": chapter_number},
            )

        try:
            self._emit_progress(
                f"开始生成单章: 第{chapter_number}章",
                progress_callback,
                stage="engine.generate_single_chapter",
                status="started",
                metadata={
                    "run_id": self.run_id,
                    "status_file": self.runtime_monitor.get_current_status().get("status_file"),
                    "events_file": self.runtime_monitor.get_current_status().get("events_file"),
                },
            )
            chapter = await self.generation_layer.generate_chapter(
                chapter_outline=chapter_outline,
                book_outline=self.outline,
                global_state=global_state,
                progress_callback=on_progress,
            )
            chapter_context = {
                "time_period_start": chapter_outline.time_period_start,
                "time_period_end": chapter_outline.time_period_end,
                "style": self.outline.style.value if self.outline else "literary",
                "subject_name": self.outline.subject_name if self.outline else "",
                "chapter_num": chapter_number,
            }
            chapter = await self.review_layer.review_chapter(
                chapter=chapter,
                chapter_context=chapter_context,
                previous_chapter=None,
            )
            self.runtime_monitor.save_json_artifact(
                name=f"chapter_{chapter_number:02d}_single.json",
                data=chapter.model_dump(),
                stage="04_generation",
            )
            self._emit_progress(
                f"单章生成完成: 第{chapter_number}章 ({chapter.word_count}字)",
                progress_callback,
                stage="engine.generate_single_chapter",
                status="completed",
                metadata={"chapter_num": chapter_number, "word_count": chapter.word_count},
            )
            self.runtime_monitor.end_run(status="completed")
            return chapter
        except Exception as exc:
            self.runtime_monitor.end_run(status="failed", error=str(exc))
            raise
        finally:
            self.llm.set_progress_callback(None)

    async def save_book(self, book: BiographyBook) -> Dict[str, Path]:
        """保存生成的书籍到输出目录."""
        self._ensure_review_layer()
        saved = await self.review_layer.finalize_book(book)
        saved_serialized = {k: str(v) for k, v in saved.items()}
        self.runtime_monitor.save_json_artifact(
            name="saved_files.json",
            data=saved_serialized,
            stage="06_output",
        )
        return saved

    def load_project(self, book_id: str) -> bool:
        """加载已有项目，支持断点续传."""
        self.book_id = book_id
        self.tracer.set_context(book_id=book_id)

        outline_path = Path(settings.paths.cache_dir) / f"{book_id}_outline.json"
        if not outline_path.exists():
            return False

        with open(outline_path, "r", encoding="utf-8") as f:
            self.outline = BookOutline(**json.load(f))

        timeline_path = Path(settings.paths.cache_dir) / f"{book_id}_timeline.json"
        if timeline_path.exists():
            try:
                self.timeline = Timeline(**json.loads(timeline_path.read_text(encoding="utf-8")))
            except Exception:
                self.timeline = Timeline(subject=CharacterProfile(name=self.outline.subject_name), events=[])
        else:
            self.timeline = Timeline(subject=CharacterProfile(name=self.outline.subject_name), events=[])

        self.state_manager = GlobalStateManager(book_id=book_id, cache_dir=Path(settings.paths.cache_dir))
        self.state_manager.load()
        if self.state_manager.state.current_chapter_idx == 0 and self.timeline:
            self.state_manager.init_from_timeline(self.timeline)
            self.state_manager.save()

        self._ensure_review_layer()
        return True

    def get_progress(self) -> Dict[str, Any]:
        """获取项目进度（含运行态信息）."""
        if not self.state_manager or not self.outline:
            return {"status": "未初始化"}

        state = self.state_manager.state
        total_chapters = self.outline.total_chapters
        current_chapter = state.current_chapter_idx
        progress_percent = (current_chapter / total_chapters * 100) if total_chapters else 0.0
        runtime_status = self.runtime_monitor.get_latest_status(self.book_id)

        return {
            "book_id": self.book_id,
            "run_id": runtime_status.get("run_id") if runtime_status else None,
            "current_chapter": current_chapter,
            "total_chapters": total_chapters,
            "progress_percent": progress_percent,
            "status": runtime_status.get("status", "进行中") if runtime_status else "进行中",
            "runtime_stage": runtime_status.get("current_stage") if runtime_status else None,
            "last_message": runtime_status.get("last_message") if runtime_status else None,
            "status_file": runtime_status.get("status_file") if runtime_status else None,
            "events_file": runtime_status.get("events_file") if runtime_status else None,
            "artifacts_dir": runtime_status.get("artifacts_dir") if runtime_status else None,
            "event_count": runtime_status.get("event_count", 0) if runtime_status else 0,
        }

    def get_health_report(self) -> Optional[Dict[str, Any]]:
        """获取最近健康报告."""
        if self._last_health_report:
            return self._last_health_report

        reports_dir = Path(__file__).parent.parent / ".observability" / "reports"
        report_files = sorted(reports_dir.glob("health_report_*.json"), reverse=True)
        if not report_files:
            return None

        try:
            return json.loads(report_files[0].read_text(encoding="utf-8"))
        except Exception:
            return None
