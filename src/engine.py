"""传记生成引擎主控."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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


# ========== V2 改进组件 ==========

class EventTracker:
    """跨章节事件追踪器 - 防止重复事件"""
    
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path
        self.events: Dict[str, Dict] = {}
        self.written_events: set = set()
        self._load()
    
    def _load(self):
        if self.storage_path:
            file = self.storage_path / "event_tracker.json"
            if file.exists():
                data = json.loads(file.read_text(encoding='utf-8'))
                self.events = data.get('events', {})
                self.written_events = set(data.get('written', []))
    
    def save(self):
        if self.storage_path:
            self.storage_path.mkdir(parents=True, exist_ok=True)
            file = self.storage_path / "event_tracker.json"
            file.write_text(json.dumps({
                'events': self.events,
                'written': list(self.written_events)
            }, ensure_ascii=False, indent=2), encoding='utf-8')
    
    def register_event(self, event: str, chapter: int, context: str = ""):
        """注册事件到追踪器"""
        event_key = event.strip()
        self.events[event_key] = {
            'first_chapter': chapter,
            'context': context,
            'registered_at': datetime.now().isoformat()
        }
        self.save()
    
    def mark_event_written(self, event: str, chapter: int):
        """标记事件已写入某章节"""
        self.written_events.add(f"{chapter}:{event.strip()}")
        self.save()
    
    def get_written_events(self) -> List[str]:
        """获取所有已写入的事件"""
        return list(self.written_events)
    
    def check_duplicate(self, event: str, current_chapter: int) -> Optional[str]:
        """检查事件是否在其他章节已写入"""
        event_key = event.strip()
        for written in self.written_events:
            if written.endswith(f":{event_key}"):
                parts = written.split(':', 1)
                if len(parts) == 2 and parts[0].isdigit():
                    chapter = int(parts[0])
                    if chapter != current_chapter:
                        return f"已在第{chapter}章写入"
        return None


class ContentCleaner:
    """内容清理器 - 移除AI元数据和占位符"""
    
    RULES = [
        (r'【[^】]*(?:修改说明|AI|重写|润色)[^】]*】[\s\S]*?(?=\n\n|\Z)', ''),  # AI元数据
        (r'\*\*?\s*\n+\*\*?【[^】]*】[\s\S]*$', ''),  # 修改说明块
        (r'^.*?这是一篇经过.*?重写稿.*?\n', ''),  # 开头声明
        (r'^\s*(?:主旨运用|本段功能|段落功能|转场提示|写作提示|写作要求|本章任务)\s*[：:].*$\n?', '', re.MULTILINE),  # 编辑批注
        (r'^\s*[\(\[]?(?:主旨运用|本段功能|段落功能|转场提示|写作提示|写作要求|本章任务)\s*[：:][^\n]*[\)\]]?\s*$\n?', '', re.MULTILINE),  # 批注变体
        (r'\[待补充[^\]]*\]', ''),  # 占位符
        (r'\(待补充[^)]*\)', ''),  # 占位符
        (r'.*待补充.*\n?', ''),  # 含待补充的行
        (r'^\s*---\s*\n+\s*\*{3}[^*]+\*{3}\s*\n?', '', re.MULTILINE),  # 分隔线后的标记
    ]
    
    @classmethod
    def clean(cls, content: str) -> str:
        """清理内容"""
        cleaned = content
        for pattern, repl, *flags in cls.RULES:
            flag = flags[0] if flags else 0
            cleaned = re.sub(pattern, repl, cleaned, flags=flag)
        return cleaned.strip()
    
    @classmethod
    def has_metadata(cls, content: str) -> bool:
        """检查是否含有元数据"""
        metadata_patterns = [
            r'【[^】]*(?:修改说明|AI|重写|润色)[^】]*】',
            r'这是一篇经过.*重写稿',
            r'(?:主旨运用|本段功能|段落功能|转场提示|写作提示|写作要求|本章任务)\s*[：:]',
            r'\[待补充[^\]]*\]',
            r'\(待补充[^)]*\)',
        ]
        return any(re.search(p, content) for p in metadata_patterns)

    @classmethod
    def clean_chapter(cls, chapter):
        """清理整章的各小节内容，避免把章节对象当成单一字符串。"""
        for section in getattr(chapter, "sections", []):
            section.content = cls.clean(section.content)
        return chapter

    @classmethod
    def chapter_has_metadata(cls, chapter) -> bool:
        return any(cls.has_metadata(section.content) for section in getattr(chapter, "sections", []))


class ValidationError:
    """验证错误"""
    def __init__(self, field: str, message: str, severity: str = "error"):
        self.field = field
        self.message = message
        self.severity = severity


class OutlineValidator:
    """大纲验证器"""
    
    def validate(self, outline: Dict) -> Tuple[bool, List[ValidationError]]:
        """验证大纲结构"""
        errors = []
        
        if not outline.get('chapters'):
            errors.append(ValidationError('chapters', '缺少章节列表'))
            return False, errors
        
        chapter_orders = []
        for i, ch in enumerate(outline['chapters']):
            if 'order' not in ch:
                errors.append(ValidationError(f'chapter_{i}', '缺少order字段'))
            else:
                chapter_orders.append(ch['order'])
            
            if not ch.get('title'):
                errors.append(ValidationError(f'chapter_{i}', '缺少title字段'))
        
        # 检查顺序
        if chapter_orders != sorted(chapter_orders):
            errors.append(ValidationError('chapters', '章节顺序不正确'))
        
        return len(errors) == 0, errors


class ContentValidator:
    """内容验证器"""
    
    def validate(self, content: str) -> Tuple[bool, List[ValidationError]]:
        """验证内容质量"""
        errors = []
        
        # 检查元数据残留
        if ContentCleaner.has_metadata(content):
            errors.append(ValidationError('metadata', '含有AI元数据残留', 'warning'))
        
        # 检查占位符
        if re.search(r'待补充|TODO|FIXME', content):
            errors.append(ValidationError('placeholder', '含有未完成的占位符'))
        
        # 检查字数
        word_count = len(content.replace(' ', '').replace('\n', ''))
        if word_count < 500:
            errors.append(ValidationError('word_count', f'字数过少({word_count})', 'warning'))
        
        return len([e for e in errors if e.severity == 'error']) == 0, errors


class FinalReviewParser:
    """终审报告解析器"""
    
    def parse(self, content: str) -> Dict:
        """解析终审报告"""
        result = {'passed': False, 'serious_issues': [], 'suggestions': []}
        
        # 检查是否通过
        if re.search(r'(?:passed|通过)[\s:：]+(true|是|通过)', content, re.I):
            result['passed'] = True
        
        # 提取严重问题
        serious_match = re.search(r'(?:===严重问题===|【严重问题】)\s*\n(.*?)(?=\n===|\n【|$)', content, re.S)
        if serious_match:
            issues = [l.strip() for l in serious_match.group(1).split('\n') if l.strip() and not l.strip().startswith('1.')]
            result['serious_issues'] = issues
        
        return result


class AutoReviser:
    """自动修订器"""
    
    def __init__(self, llm: LLMClient, storage_path: Optional[Path] = None):
        self.llm = llm
        self.storage_path = storage_path
    
    async def fix_metadata(self, content: str) -> str:
        """修复元数据问题"""
        return ContentCleaner.clean(content)
    
    async def revise_by_feedback(self, content: str, feedback: str) -> str:
        """根据反馈修订内容"""
        prompt = f"""请根据以下反馈修订内容。保持原文风格和主要信息，只修改问题部分。

【原文】
{content[:3000]}

【反馈】
{feedback}

【要求】
1. 直接输出修订后的正文
2. 不要添加任何元数据或修改说明
3. 保持原有格式"""
        
        try:
            revised = await self.llm.complete([
                {"role": "user", "content": prompt}
            ], temperature=0.3, max_tokens=4000)
            return ContentCleaner.clean(revised)
        except Exception as e:
            logger.warning(f"自动修订失败: {e}")
            return content


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
        
        # V2 改进组件
        self.event_tracker: Optional[EventTracker] = None
        self.outline_validator = OutlineValidator()
        self.content_validator = ContentValidator()
        self.auto_reviser: Optional[AutoReviser] = None
        self._final_review_done = False

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
            vector_store=self.vector_store,
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
            
            # V2: 验证大纲
            outline_dict = json.loads(outline_path.read_text(encoding='utf-8'))
            is_valid, errors = self.outline_validator.validate(outline_dict)
            if not is_valid:
                for err in errors:
                    logger.error(f"大纲验证失败: {err.field} - {err.message}")
                raise ValueError("大纲验证失败，无法继续")
            logger.info("✓ 大纲验证通过")

            if self.metrics._workflow_metrics:
                self.metrics._workflow_metrics.total_chapters = self.outline.total_chapters

            project_path = Path(settings.paths.output_dir) / self.book_id
            project_path.mkdir(parents=True, exist_ok=True)
            
            # V2: 初始化事件追踪器
            self.event_tracker = EventTracker(project_path)
            self.auto_reviser = AutoReviser(self.llm, project_path)
            
            # V2: 注册大纲中的关键事件
            for ch in self.outline.chapters:
                time_period = f"{ch.time_period_start}-{ch.time_period_end}" if ch.time_period_start else f"第{ch.order}章"
                key_events = [time_period] if time_period else []
                for event in key_events:
                    self.event_tracker.register_event(event, ch.order, ch.title)
            
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
                prompt_state = self.state_manager.get_context_for_generation()
                prompt_state["hard_facts"] = self.state_manager.get_hard_fact_guard()
                generation_state = self.state_manager.state
                
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
                    global_state=generation_state,
                    progress_callback=on_progress,
                )
                
                # V2: 清理元数据
                had_metadata = ContentCleaner.chapter_has_metadata(chapter)
                chapter = ContentCleaner.clean_chapter(chapter)
                if had_metadata:
                    logger.info(f"  已清理章节{chapter_num}的元数据")
                
                # V2: 验证内容
                is_valid, errors = self.content_validator.validate(chapter.full_content)
                if not is_valid:
                    for err in errors:
                        logger.warning(f"  内容问题({err.field}): {err.message}")
                
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
                    "timeline": [event.model_dump() for event in self.timeline.events] if self.timeline else [],
                    "subject_profile": generation_state.subject_profile.model_dump() if getattr(generation_state, "subject_profile", None) else {},
                    "book_outline": self.outline.model_dump() if self.outline else {},
                    "character_profiles": {
                        name: {"display_name": name}
                        for name in getattr(generation_state, "character_name_mappings", {}).keys()
                    },
                    "established_facts": prompt_state.get("hard_facts", []),
                    "hard_facts": prompt_state.get("hard_facts", []),
                }
                previous_chapter = chapters[-1] if chapters else None
                chapter = await self.review_layer.review_chapter(
                    chapter=chapter,
                    chapter_context=chapter_context,
                    previous_chapter=previous_chapter,
                )
                
                # V2: 审校后再次清理
                chapter = ContentCleaner.clean_chapter(chapter)
                
                self.tracer.end_trace(review_trace, TraceStatus.COMPLETED)
                self.runtime_monitor.save_json_artifact(
                    name=f"chapter_{chapter_num:02d}_reviewed.json",
                    data=chapter.model_dump(),
                    stage="05_review",
                )

                chapters.append(chapter)
                chapter_summary = str(chapter.metadata.get("chapter_summary") or f"{chapter_outline.title}：{chapter_outline.summary}")
                self.state_manager.add_chapter_summary(chapter_summary)
                self.state_manager.save()
                
                # V2: 标记事件已写入
                if self.event_tracker:
                    time_key = f"{chapter_outline.time_period_start}-{chapter_outline.time_period_end}"
                    self.event_tracker.mark_event_written(time_key, chapter_num)

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
            
            # V2: 全部章节完成后，执行终审和自动修订
            await self._perform_final_review_and_revision(chapters, progress_callback)

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
        generation_state = self.state_manager.state

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
                global_state=generation_state,
                progress_callback=on_progress,
            )
            chapter_context = {
                "time_period_start": chapter_outline.time_period_start,
                "time_period_end": chapter_outline.time_period_end,
                "style": self.outline.style.value if self.outline else "literary",
                "subject_name": self.outline.subject_name if self.outline else "",
                "chapter_num": chapter_number,
                "timeline": [event.model_dump() for event in self.timeline.events] if self.timeline else [],
                "subject_profile": generation_state.subject_profile.model_dump() if getattr(generation_state, "subject_profile", None) else {},
                "book_outline": self.outline.model_dump() if self.outline else {},
                "established_facts": self.state_manager.get_hard_fact_guard(),
                "hard_facts": self.state_manager.get_hard_fact_guard(),
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
        
        # V2: 恢复组件状态
        project_path = Path(settings.paths.output_dir) / book_id
        self.event_tracker = EventTracker(project_path)
        self.auto_reviser = AutoReviser(self.llm, project_path)

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

    def _extract_role_mentions(self, text: str) -> Dict[str, List[str]]:
        """从章节正文中提取常见家庭角色的人名提及。"""
        boundary = r"(?=陪|跑|说|问|笑|哭|在|把|给|来|去|走|进|对|便|就|也|都|正|还|又|跟|和|向|替|为|突|忽|忙|慌|急|连|先|赶|立|匆|[，。、“”‘’：:；\s])"
        role_patterns = {
            "妻子": [
                rf"(?:妻子|爱人|太太)([\u4e00-\u9fff]{{2,4}}?){boundary}",
                r"([\u4e00-\u9fff]{2,4})(?:是他的妻子|作为妻子)",
            ],
            "丈夫": [
                rf"(?:丈夫|先生|爱人)([\u4e00-\u9fff]{{2,4}}?){boundary}",
            ],
            "儿子": [
                rf"(?:儿子|大儿子|小儿子|长子|次子)([\u4e00-\u9fff]{{2,4}}?){boundary}",
            ],
            "女儿": [
                rf"(?:女儿|大女儿|小女儿|长女|次女)([\u4e00-\u9fff]{{2,4}}?){boundary}",
            ],
        }
        invalid_names = {
            "有些", "一个", "两个", "后来", "当时", "一直", "只是", "开始",
            "已经", "正在", "默默", "慢慢", "忽然", "终于", "还是", "其实",
        }

        result: Dict[str, List[str]] = {}
        for role, patterns in role_patterns.items():
            names: List[str] = []
            for pattern in patterns:
                for match in re.findall(pattern, text):
                    name = str(match).strip()
                    if len(name) < 2 or len(name) > 4:
                        continue
                    if name in invalid_names:
                        continue
                    if any(token in name for token in ("妻子", "丈夫", "儿子", "女儿", "父亲", "母亲")):
                        continue
                    if name not in names:
                        names.append(name)
            if names:
                result[role] = names
        return result

    def _run_rule_based_book_scan(self, chapters: List[GeneratedChapter]) -> List[Dict[str, Any]]:
        """先用规则抓最致命、最不该放过的硬伤。"""
        issues: List[Dict[str, Any]] = []

        role_name_occurrences: Dict[str, Dict[str, List[int]]] = {}
        for chapter in chapters:
            role_mentions = self._extract_role_mentions(chapter.full_content)
            for role, names in role_mentions.items():
                role_name_occurrences.setdefault(role, {})
                for name in names:
                    role_name_occurrences[role].setdefault(name, [])
                    role_name_occurrences[role][name].append(chapter.outline.order)

        for role, name_map in role_name_occurrences.items():
            distinct_names = [name for name in name_map.keys() if name]
            if len(distinct_names) <= 1:
                continue

            ordered = sorted(
                ((min(chapters_seen), name) for name, chapters_seen in name_map.items() if chapters_seen),
                key=lambda item: item[0],
            )
            canonical_name = ordered[0][1]
            conflicting_names = [name for _, name in ordered[1:]]
            affected_chapters = sorted({
                chapter_num
                for name in conflicting_names
                for chapter_num in name_map.get(name, [])
            })
            issues.append(
                {
                    "type": "role_name_drift",
                    "severity": "critical",
                    "description": f"{role}名字前后不一致，前文是“{canonical_name}”，后文又出现“{'、'.join(conflicting_names)}”",
                    "chapters": affected_chapters,
                    "scope": "chapter",
                    "rewrite_strategy": "local_chapter",
                    "blocking": True,
                }
            )

        for chapter in chapters:
            if ContentCleaner.has_metadata(chapter.full_content):
                issues.append(
                    {
                        "type": "editorial_residue",
                        "severity": "critical",
                        "description": f"第{chapter.outline.order}章存在编辑批注或提示词残留",
                        "chapters": [chapter.outline.order],
                        "scope": "chapter",
                        "rewrite_strategy": "local_cleanup",
                        "blocking": True,
                    }
                )

        return issues

    def _build_final_review_payload(self, chapters: List[GeneratedChapter]) -> Dict[str, Any]:
        """构建终审负载，尽量用摘要和硬事实，不把正文全部塞给模型。"""
        hard_facts = self.state_manager.get_hard_fact_guard() if self.state_manager else []
        chapter_cards = []
        for chapter in chapters:
            chapter_cards.append(
                {
                    "chapter": chapter.outline.order,
                    "title": chapter.outline.title,
                    "time_range": f"{chapter.outline.time_period_start or ''}-{chapter.outline.time_period_end or ''}",
                    "summary": chapter.metadata.get("chapter_summary") or chapter.outline.summary,
                    "opening": chapter.full_content[:500],
                    "ending": chapter.full_content[-500:],
                    "role_mentions": self._extract_role_mentions(chapter.full_content),
                }
            )

        return {
            "book_id": self.book_id,
            "title": self.outline.title if self.outline else "",
            "subject_name": self.outline.subject_name if self.outline else "",
            "hard_facts": hard_facts[:12],
            "chapters": chapter_cards,
        }

    def _extract_json_object_loose(self, text: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return {}

    async def _request_structured_final_review(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """用结构化终审补足规则扫描抓不到的跨章逻辑问题。"""
        prompt = f"""请对这本传记做全书终审。重点只看严重问题，不要吹毛求疵。

返回JSON，格式必须是：
{{
  "passed": true,
  "issues": [
    {{
      "type": "character_drift|timeline_conflict|editorial_residue|duplicate_event|other",
      "severity": "critical|high|medium",
      "description": "问题描述",
      "chapters": [11, 12],
      "scope": "sentence|section|chapter|book",
      "rewrite_strategy": "local_sentence|local_section|local_chapter|manual_review",
      "blocking": true
    }}
  ],
  "summary": "总体判断"
}}

判定原则：
1. 只报会明显毁掉可信度或沉浸感的问题
2. 优先看：人物名字漂移、家庭关系前后矛盾、年龄与年份推算冲突、编辑批注残留
3. 能局部修的，rewrite_strategy 必须给 local_sentence/local_section/local_chapter
4. 只有真的牵涉整本结构，scope 才能写 book
5. 不要输出思考过程，不要输出JSON外的文字

待审信息：
{json.dumps(payload, ensure_ascii=False)}
"""
        try:
            response = await self.llm.complete(
                [
                    {"role": "system", "content": "你是传记终审编辑，只输出合法JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=5000,
            )
            parsed = self._extract_json_object_loose(response)
            issues = parsed.get("issues", []) if isinstance(parsed.get("issues", []), list) else []
            sanitized = []
            for item in issues:
                if not isinstance(item, dict):
                    continue
                chapters = item.get("chapters", [])
                if not isinstance(chapters, list):
                    chapters = []
                sanitized.append(
                    {
                        "type": str(item.get("type", "other")).strip() or "other",
                        "severity": str(item.get("severity", "medium")).strip() or "medium",
                        "description": str(item.get("description", "")).strip(),
                        "chapters": [int(ch) for ch in chapters if str(ch).isdigit()],
                        "scope": str(item.get("scope", "chapter")).strip() or "chapter",
                        "rewrite_strategy": str(item.get("rewrite_strategy", "local_chapter")).strip() or "local_chapter",
                        "blocking": bool(item.get("blocking", False)),
                    }
                )
            return {
                "passed": bool(parsed.get("passed", False)),
                "summary": str(parsed.get("summary", "")).strip(),
                "issues": sanitized,
            }
        except Exception as exc:
            logger.warning(f"结构化终审失败: {exc}")
            return {"passed": True, "summary": "", "issues": []}

    async def _repair_chapter_for_final_issue(
        self,
        chapter: GeneratedChapter,
        issue: Dict[str, Any],
        previous_chapter: Optional[GeneratedChapter],
        hard_facts: List[str],
    ) -> GeneratedChapter:
        """终审阶段默认按章做最小必要修复，不做全书重写。"""
        previous_excerpt = previous_chapter.full_content[-1500:] if previous_chapter else "（无前章）"
        hard_fact_text = "\n".join(f"- {fact}" for fact in hard_facts[:12]) if hard_facts else "（无）"
        prompt = f"""请修复这一章中与全书一致性相关的问题。要求最小必要改动，不要重写整章风格。

【问题类型】
{issue.get("type", "other")}

【问题描述】
{issue.get("description", "")}

【前一章结尾】
{previous_excerpt}

【当前章节全文】
{chapter.full_content}

【硬事实守卫】
{hard_fact_text}

【修复原则】
1. 只改有问题的句子、段落或小节
2. 人名、关系、年份、年龄推算必须与前文一致
3. 删除编辑批注、提示词、提纲残留
4. 不要新增没有依据的大情节
5. 保留原有小节标题，直接输出修复后的整章正文
"""
        try:
            rewritten = await self.llm.complete(
                [
                    {"role": "system", "content": "你是一位克制的终审编辑，擅长局部修订而不是推倒重写。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.25,
                max_tokens=16384,
            )
            cleaned = ContentCleaner.clean(rewritten)
            if cleaned and self.review_layer:
                return self.review_layer._replace_chapter_sections_from_text(chapter, cleaned)
        except Exception as exc:
            logger.warning(f"终审按章修复失败: {exc}")
        return chapter

    async def _apply_final_review_repairs(
        self,
        chapters: List[GeneratedChapter],
        issues: List[Dict[str, Any]],
    ) -> List[GeneratedChapter]:
        """根据终审问题做局部修复。"""
        if not issues:
            return chapters

        hard_facts = self.state_manager.get_hard_fact_guard() if self.state_manager else []
        chapter_index = {chapter.outline.order: idx for idx, chapter in enumerate(chapters)}

        for issue in issues:
            strategy = issue.get("rewrite_strategy", "")
            if strategy == "manual_review":
                continue

            target_chapters = issue.get("chapters", [])
            if not target_chapters:
                continue

            for chapter_num in target_chapters:
                idx = chapter_index.get(chapter_num)
                if idx is None:
                    continue
                previous_chapter = chapters[idx - 1] if idx > 0 else None
                repaired = await self._repair_chapter_for_final_issue(
                    chapter=chapters[idx],
                    issue=issue,
                    previous_chapter=previous_chapter,
                    hard_facts=hard_facts,
                )
                chapters[idx] = ContentCleaner.clean_chapter(repaired)

        return chapters
    
    # ========== V2: 终审和自动修订 ==========
    
    async def _perform_final_review_and_revision(
        self, 
        chapters: List[GeneratedChapter], 
        progress_callback: Optional[Callable[[str], None]] = None
    ):
        """执行全文终审和自动修订"""
        if self._final_review_done:
            return
        
        logger.info("\n📚 开始全文终审...")
        self._emit_progress("开始全文终审", progress_callback, stage="final_review")

        try:
            rule_issues = self._run_rule_based_book_scan(chapters)
            final_review_payload = self._build_final_review_payload(chapters)
            llm_review = await self._request_structured_final_review(final_review_payload)

            combined_issues = list(rule_issues)
            for item in llm_review.get("issues", []):
                if not any(
                    existing.get("type") == item.get("type")
                    and existing.get("description") == item.get("description")
                    and existing.get("chapters") == item.get("chapters")
                    for existing in combined_issues
                ):
                    combined_issues.append(item)

            review_report = {
                "passed": len(combined_issues) == 0,
                "summary": llm_review.get("summary", ""),
                "rule_issues": rule_issues,
                "llm_issues": llm_review.get("issues", []),
                "combined_issues": combined_issues,
            }

            if self.book_id:
                project_path = Path(settings.paths.output_dir) / self.book_id
                project_path.mkdir(parents=True, exist_ok=True)
                review_file = project_path / "final_review.json"
                review_file.write_text(
                    json.dumps(review_report, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            if not combined_issues:
                logger.info("✓ 终审通过，无严重问题")
                self._emit_progress("终审通过", progress_callback, stage="final_review", status="completed")
            else:
                blocking_issues = [item for item in combined_issues if item.get("blocking")]
                logger.warning(f"⚠️ 发现{len(combined_issues)}个终审问题，其中{len(blocking_issues)}个需要强制处理")
                self._emit_progress(
                    f"发现{len(combined_issues)}个终审问题，开始按章局部修订",
                    progress_callback,
                    stage="auto_revision",
                )

                chapters[:] = await self._apply_final_review_repairs(chapters, blocking_issues)
                post_rule_issues = self._run_rule_based_book_scan(chapters)

                unresolved = []
                for item in post_rule_issues:
                    if item.get("blocking"):
                        unresolved.append(item)

                if self.book_id:
                    project_path = Path(settings.paths.output_dir) / self.book_id
                    post_review_file = project_path / "final_review_after_repair.json"
                    post_review_file.write_text(
                        json.dumps(
                            {
                                "remaining_blocking_issues": unresolved,
                                "remaining_rule_issues": post_rule_issues,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )

                if unresolved:
                    logger.warning(f"终审后仍有{len(unresolved)}个未消除的硬伤，已写入终审报告，建议人工抽检")
                    self._emit_progress(
                        f"终审后仍有{len(unresolved)}个硬伤待处理",
                        progress_callback,
                        stage="auto_revision",
                        status="warning",
                    )
                else:
                    logger.info("✓ 终审问题已完成局部修订")
                    self._emit_progress("终审问题已完成局部修订", progress_callback, stage="auto_revision", status="completed")
            
            self._final_review_done = True
            
        except Exception as e:
            logger.warning(f"终审过程出错: {e}")
            # 不阻断流程，继续完成
