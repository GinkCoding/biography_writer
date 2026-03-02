"""工作流追踪器 - 记录调用链和步骤执行顺序

功能：
1. 调用追踪 (call_trace.jsonl): 记录每个步骤的调用时间、参数、结果
2. 步骤顺序追踪: 检测工作流执行顺序是否正确，记录步骤跳跃或重复
3. 依赖关系验证: 验证步骤依赖关系

参考: /Users/guoquan/work/Kimi/webnovel-writer/.claude/scripts/workflow_manager.py
"""
import json
import os
import gzip
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
from loguru import logger


class TraceStatus(str, Enum):
    """追踪状态"""
    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class LayerType(str, Enum):
    """层类型"""
    DATA_INGESTION = "data_ingestion"      # 第1层: 数据接入
    KNOWLEDGE_MEMORY = "knowledge_memory"  # 第2层: 知识记忆
    PLANNING = "planning"                  # 第3层: 规划编排
    GENERATION = "generation"              # 第4层: 迭代生成
    REVIEW_OUTPUT = "review_output"        # 第5层: 审校输出
    ENGINE = "engine"                      # 主引擎
    LLM_CLIENT = "llm_client"              # LLM客户端
    AGENT = "agent"                        # Agent层


@dataclass
class TraceEvent:
    """追踪事件数据模型"""
    timestamp: str                          # ISO格式时间戳
    layer: str                              # 所属层
    operation: str                          # 操作名称
    duration_ms: float                      # 执行时长(毫秒)
    status: str                             # 状态: success/failure/skipped
    book_id: Optional[str] = None           # 项目ID
    chapter_num: Optional[int] = None       # 章节号
    section_num: Optional[int] = None       # 小节号
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外元数据
    error: Optional[str] = None             # 错误信息
    parent_trace_id: Optional[str] = None   # 父追踪ID
    trace_id: str = field(default_factory=lambda: f"trace_{datetime.now().strftime('%Y%m%d%H%M%S%f')}")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    def to_json_line(self) -> str:
        """转换为JSON Lines格式"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


@dataclass
class StepSequence:
    """步骤序列记录"""
    step_id: str
    step_name: str
    expected_order: int
    actual_order: int
    started_at: str
    completed_at: Optional[str] = None
    status: str = TraceStatus.STARTED
    dependencies: List[str] = field(default_factory=list)


class WorkflowTracer:
    """工作流追踪器

    单例模式，确保全局只有一个追踪器实例
    """
    _instance: Optional['WorkflowTracer'] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        project_root: Optional[Path] = None,
        max_file_size_mb: int = 10,
        max_backup_files: int = 5
    ):
        if self._initialized:
            return

        self.project_root = project_root or Path.cwd()
        self.observability_dir = self.project_root / ".observability"
        self.trace_file = self.observability_dir / "call_trace.jsonl"
        self.state_file = self.observability_dir / "workflow_state.json"

        self.max_file_size = max_file_size_mb * 1024 * 1024
        self.max_backup_files = max_backup_files

        # 确保目录存在
        self.observability_dir.mkdir(parents=True, exist_ok=True)

        # 步骤序列追踪
        self._step_sequences: Dict[str, StepSequence] = {}
        self._completed_steps: List[str] = []
        self._step_order_violations: List[Dict] = []

        # 当前追踪上下文
        self._current_book_id: Optional[str] = None
        self._current_chapter: Optional[int] = None
        self._active_traces: Dict[str, TraceEvent] = {}

        # 依赖关系定义
        self._dependency_graph: Dict[str, List[str]] = {
            # 引擎主流程依赖
            "engine.initialize": [],
            "engine.generate_book": ["engine.initialize"],
            "engine.generate_chapter": ["engine.generate_book"],
            "engine.save_book": ["engine.generate_book"],

            # 各层依赖
            "layer.data_ingestion": [],
            "layer.knowledge_memory": ["layer.data_ingestion"],
            "layer.planning": ["layer.knowledge_memory"],
            "layer.generation": ["layer.planning"],
            "layer.review_output": ["layer.generation"],

            # Agent依赖
            "agent.context": ["layer.planning"],
            "agent.data": ["layer.generation"],
        }

        self._initialized = True
        logger.info(f"WorkflowTracer initialized: {self.observability_dir}")

    def set_context(self, book_id: Optional[str] = None, chapter_num: Optional[int] = None):
        """设置当前追踪上下文"""
        self._current_book_id = book_id
        self._current_chapter = chapter_num

    def start_trace(
        self,
        layer: str,
        operation: str,
        metadata: Optional[Dict[str, Any]] = None,
        parent_trace_id: Optional[str] = None
    ) -> str:
        """开始一个追踪事件

        Returns:
            trace_id: 追踪ID，用于后续完成追踪
        """
        trace = TraceEvent(
            timestamp=datetime.now().isoformat(),
            layer=layer,
            operation=operation,
            duration_ms=0.0,
            status=TraceStatus.STARTED,
            book_id=self._current_book_id,
            chapter_num=self._current_chapter,
            metadata=metadata or {},
            parent_trace_id=parent_trace_id
        )

        self._active_traces[trace.trace_id] = trace
        self._append_to_file(trace)

        return trace.trace_id

    def end_trace(
        self,
        trace_id: str,
        status: str = TraceStatus.COMPLETED,
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> Optional[TraceEvent]:
        """结束一个追踪事件"""
        trace = self._active_traces.pop(trace_id, None)
        if not trace:
            logger.warning(f"Trace {trace_id} not found")
            return None

        # 计算持续时间
        start_time = datetime.fromisoformat(trace.timestamp)
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000

        trace.duration_ms = duration_ms
        trace.status = status
        trace.error = error

        if metadata:
            trace.metadata.update(metadata)

        self._append_to_file(trace)
        return trace

    def trace_step_start(
        self,
        step_id: str,
        step_name: str,
        expected_order: int,
        dependencies: Optional[List[str]] = None
    ):
        """记录步骤开始"""
        # 检查步骤顺序
        actual_order = len(self._completed_steps) + 1

        step = StepSequence(
            step_id=step_id,
            step_name=step_name,
            expected_order=expected_order,
            actual_order=actual_order,
            started_at=datetime.now().isoformat(),
            dependencies=dependencies or [],
            status=TraceStatus.STARTED
        )

        # 检查依赖是否满足
        for dep in step.dependencies:
            if dep not in self._completed_steps:
                violation = {
                    "type": "dependency_violation",
                    "step_id": step_id,
                    "missing_dependency": dep,
                    "timestamp": datetime.now().isoformat()
                }
                self._step_order_violations.append(violation)
                self._append_to_file(TraceEvent(
                    timestamp=datetime.now().isoformat(),
                    layer="workflow",
                    operation="dependency_violation",
                    duration_ms=0.0,
                    status="warning",
                    book_id=self._current_book_id,
                    metadata=violation
                ))

        # 检查顺序是否正确
        if expected_order != actual_order:
            violation = {
                "type": "order_violation",
                "step_id": step_id,
                "expected_order": expected_order,
                "actual_order": actual_order,
                "timestamp": datetime.now().isoformat()
            }
            self._step_order_violations.append(violation)
            self._append_to_file(TraceEvent(
                timestamp=datetime.now().isoformat(),
                layer="workflow",
                operation="order_violation",
                duration_ms=0.0,
                status="warning",
                book_id=self._current_book_id,
                metadata=violation
            ))

        self._step_sequences[step_id] = step

        # 记录追踪事件
        self._append_to_file(TraceEvent(
            timestamp=step.started_at,
            layer="workflow",
            operation="step_start",
            duration_ms=0.0,
            status=TraceStatus.STARTED,
            book_id=self._current_book_id,
            chapter_num=self._current_chapter,
            metadata={
                "step_id": step_id,
                "step_name": step_name,
                "expected_order": expected_order,
                "actual_order": actual_order
            }
        ))

    def trace_step_complete(self, step_id: str, metadata: Optional[Dict[str, Any]] = None):
        """记录步骤完成"""
        step = self._step_sequences.get(step_id)
        if step:
            step.completed_at = datetime.now().isoformat()
            step.status = TraceStatus.COMPLETED
            self._completed_steps.append(step_id)

            # 计算持续时间
            start_time = datetime.fromisoformat(step.started_at)
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            self._append_to_file(TraceEvent(
                timestamp=step.completed_at,
                layer="workflow",
                operation="step_complete",
                duration_ms=duration_ms,
                status=TraceStatus.COMPLETED,
                book_id=self._current_book_id,
                chapter_num=self._current_chapter,
                metadata={
                    "step_id": step_id,
                    "step_name": step.step_name,
                    **(metadata or {})
                }
            ))

    def trace_step_failure(self, step_id: str, error: str, metadata: Optional[Dict[str, Any]] = None):
        """记录步骤失败"""
        step = self._step_sequences.get(step_id)
        if step:
            step.completed_at = datetime.now().isoformat()
            step.status = TraceStatus.FAILED

            start_time = datetime.fromisoformat(step.started_at)
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            self._append_to_file(TraceEvent(
                timestamp=step.completed_at,
                layer="workflow",
                operation="step_failure",
                duration_ms=duration_ms,
                status=TraceStatus.FAILED,
                book_id=self._current_book_id,
                chapter_num=self._current_chapter,
                error=error,
                metadata={
                    "step_id": step_id,
                    "step_name": step.step_name,
                    **(metadata or {})
                }
            ))

    def _append_to_file(self, event: TraceEvent):
        """追加事件到追踪文件"""
        try:
            # 检查文件大小，必要时轮转
            self._rotate_if_needed()

            with open(self.trace_file, "a", encoding="utf-8") as f:
                f.write(event.to_json_line() + "\n")
        except Exception as e:
            logger.error(f"Failed to append trace: {e}")

    def _rotate_if_needed(self):
        """检查并执行日志轮转"""
        if not self.trace_file.exists():
            return

        if self.trace_file.stat().st_size < self.max_file_size:
            return

        # 执行轮转
        for i in range(self.max_backup_files - 1, 0, -1):
            old_file = self.trace_file.parent / f"call_trace.jsonl.{i}.gz"
            new_file = self.trace_file.parent / f"call_trace.jsonl.{i + 1}.gz"
            if old_file.exists():
                shutil.move(old_file, new_file)

        # 压缩当前文件
        compressed = self.trace_file.parent / "call_trace.jsonl.1.gz"
        with open(self.trace_file, "rb") as f_in:
            with gzip.open(compressed, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        # 清空当前文件
        self.trace_file.unlink()

    def get_step_sequence_report(self) -> Dict[str, Any]:
        """获取步骤序列报告"""
        return {
            "total_steps": len(self._step_sequences),
            "completed_steps": len(self._completed_steps),
            "step_order_violations": self._step_order_violations,
            "steps": {
                step_id: {
                    "step_name": seq.step_name,
                    "expected_order": seq.expected_order,
                    "actual_order": seq.actual_order,
                    "status": seq.status,
                    "started_at": seq.started_at,
                    "completed_at": seq.completed_at,
                    "dependencies": seq.dependencies
                }
                for step_id, seq in self._step_sequences.items()
            }
        }

    def reset(self):
        """重置追踪状态"""
        self._step_sequences.clear()
        self._completed_steps.clear()
        self._step_order_violations.clear()
        self._active_traces.clear()
        self._current_book_id = None
        self._current_chapter = None

    def read_traces(
        self,
        layer: Optional[str] = None,
        operation: Optional[str] = None,
        book_id: Optional[str] = None,
        limit: int = 100
    ) -> List[TraceEvent]:
        """读取追踪记录"""
        events = []

        if not self.trace_file.exists():
            return events

        try:
            with open(self.trace_file, "r", encoding="utf-8") as f:
                for line in f:
                    if len(events) >= limit:
                        break

                    try:
                        data = json.loads(line.strip())

                        # 过滤条件
                        if layer and data.get("layer") != layer:
                            continue
                        if operation and data.get("operation") != operation:
                            continue
                        if book_id and data.get("book_id") != book_id:
                            continue

                        events.append(TraceEvent(**data))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Failed to read traces: {e}")

        return events


# 便捷装饰器
def trace_event(
    layer: str,
    operation: Optional[str] = None,
    include_args: bool = False,
    include_result: bool = False
):
    """追踪装饰器

    Usage:
        @trace_event(layer="llm_client", operation="complete")
        async def complete(self, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        op_name = operation or func.__name__

        async def async_wrapper(*args, **kwargs):
            tracer = WorkflowTracer()

            metadata = {}
            if include_args:
                metadata["args"] = str(args[1:])  # 排除self
                metadata["kwargs"] = {k: str(v) for k, v in kwargs.items()}

            trace_id = tracer.start_trace(layer, op_name, metadata)

            try:
                result = await func(*args, **kwargs)

                result_metadata = {}
                if include_result:
                    result_metadata["result_type"] = type(result).__name__
                    if isinstance(result, str):
                        result_metadata["result_length"] = len(result)

                tracer.end_trace(trace_id, TraceStatus.COMPLETED, result_metadata)
                return result

            except Exception as e:
                tracer.end_trace(trace_id, TraceStatus.FAILED, error=str(e))
                raise

        def sync_wrapper(*args, **kwargs):
            tracer = WorkflowTracer()

            metadata = {}
            if include_args:
                metadata["args"] = str(args[1:])
                metadata["kwargs"] = {k: str(v) for k, v in kwargs.items()}

            trace_id = tracer.start_trace(layer, op_name, metadata)

            try:
                result = func(*args, **kwargs)

                result_metadata = {}
                if include_result:
                    result_metadata["result_type"] = type(result).__name__

                tracer.end_trace(trace_id, TraceStatus.COMPLETED, result_metadata)
                return result

            except Exception as e:
                tracer.end_trace(trace_id, TraceStatus.FAILED, error=str(e))
                raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# 全局便捷函数
def get_tracer(project_root: Optional[Path] = None) -> WorkflowTracer:
    """获取全局追踪器实例"""
    return WorkflowTracer(project_root=project_root)
