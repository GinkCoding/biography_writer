"""指标收集器 - 收集性能指标、API调用、Token使用量和成本

功能：
1. API调用次数统计
2. Token使用量追踪
3. 按层/按功能成本分析
4. 生成速度（字/秒）
5. 检索延迟
6. 存储操作耗时
"""
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict
from loguru import logger


class MetricType(str, Enum):
    """指标类型"""
    API_CALL = "api_call"           # API调用
    GENERATION = "generation"       # 内容生成
    RETRIEVAL = "retrieval"         # 检索操作
    STORAGE = "storage"             # 存储操作
    LATENCY = "latency"             # 延迟指标
    THROUGHPUT = "throughput"       # 吞吐量


@dataclass
class APICallMetrics:
    """API调用指标"""
    provider: str                           # 提供商 (kimi/openai/zhipuai)
    model: str                              # 模型名称
    call_count: int = 0                     # 调用次数
    total_tokens: int = 0                   # 总Token数
    prompt_tokens: int = 0                  # 提示Token数
    completion_tokens: int = 0              # 生成Token数
    total_cost_usd: float = 0.0             # 总成本(美元)
    avg_latency_ms: float = 0.0             # 平均延迟
    errors: int = 0                         # 错误次数
    retries: int = 0                        # 重试次数

    def add_call(
        self,
        tokens: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: float = 0.0,
        error: bool = False,
        retry: bool = False
    ):
        """添加一次调用记录"""
        self.call_count += 1
        self.total_tokens += tokens
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_cost_usd += cost_usd

        # 更新平均延迟
        if self.avg_latency_ms == 0:
            self.avg_latency_ms = latency_ms
        else:
            self.avg_latency_ms = (self.avg_latency_ms * (self.call_count - 1) + latency_ms) / self.call_count

        if error:
            self.errors += 1
        if retry:
            self.retries += 1


@dataclass
class GenerationMetrics:
    """生成指标"""
    layer: str                              # 所属层
    operation: str                          # 操作名称
    total_calls: int = 0                    # 总调用次数
    total_chars_generated: int = 0          # 总生成字符数
    total_duration_ms: float = 0.0          # 总耗时
    avg_speed_chars_per_sec: float = 0.0    # 平均生成速度(字/秒)
    success_count: int = 0                  # 成功次数
    failure_count: int = 0                  # 失败次数

    def add_generation(
        self,
        chars: int,
        duration_ms: float,
        success: bool = True
    ):
        """添加生成记录"""
        self.total_calls += 1
        self.total_chars_generated += chars
        self.total_duration_ms += duration_ms

        if success:
            self.success_count += 1
        else:
            self.failure_count += 1

        # 计算平均速度
        duration_sec = duration_ms / 1000
        if duration_sec > 0:
            speed = chars / duration_sec
            if self.avg_speed_chars_per_sec == 0:
                self.avg_speed_chars_per_sec = speed
            else:
                self.avg_speed_chars_per_sec = (
                    self.avg_speed_chars_per_sec * (self.total_calls - 1) + speed
                ) / self.total_calls


@dataclass
class RetrievalMetrics:
    """检索指标"""
    retrieval_type: str                     # 检索类型 (vector/bm25/hybrid/rerank)
    total_calls: int = 0                    # 总调用次数
    total_duration_ms: float = 0.0          # 总耗时
    avg_latency_ms: float = 0.0             # 平均延迟
    total_results_returned: int = 0         # 返回结果总数
    cache_hits: int = 0                     # 缓存命中次数
    cache_misses: int = 0                   # 缓存未命中次数

    def add_retrieval(
        self,
        duration_ms: float,
        results_count: int,
        cache_hit: bool = False
    ):
        """添加检索记录"""
        self.total_calls += 1
        self.total_duration_ms += duration_ms
        self.total_results_returned += results_count

        if cache_hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

        # 更新平均延迟
        if self.avg_latency_ms == 0:
            self.avg_latency_ms = duration_ms
        else:
            self.avg_latency_ms = (self.avg_latency_ms * (self.total_calls - 1) + duration_ms) / self.total_calls

    @property
    def cache_hit_rate(self) -> float:
        """缓存命中率"""
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total


@dataclass
class StorageMetrics:
    """存储指标"""
    storage_type: str                       # 存储类型 (vector_db/sqlite/file)
    operation: str                          # 操作类型 (read/write/delete/query)
    total_calls: int = 0                    # 总调用次数
    total_duration_ms: float = 0.0          # 总耗时
    avg_latency_ms: float = 0.0             # 平均延迟
    total_bytes: int = 0                    # 总字节数
    errors: int = 0                         # 错误次数

    def add_operation(
        self,
        duration_ms: float,
        bytes_count: int = 0,
        error: bool = False
    ):
        """添加操作记录"""
        self.total_calls += 1
        self.total_duration_ms += duration_ms
        self.total_bytes += bytes_count

        if error:
            self.errors += 1

        # 更新平均延迟
        if self.avg_latency_ms == 0:
            self.avg_latency_ms = duration_ms
        else:
            self.avg_latency_ms = (self.avg_latency_ms * (self.total_calls - 1) + duration_ms) / self.total_calls


@dataclass
class WorkflowMetrics:
    """工作流整体指标"""
    book_id: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    total_chapters: int = 0
    completed_chapters: int = 0
    total_sections: int = 0
    completed_sections: int = 0
    total_api_calls: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_generation_time_ms: float = 0.0
    avg_chapter_length: float = 0.0
    success_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MetricsCollector:
    """指标收集器

    单例模式，确保全局只有一个收集器实例
    """
    _instance: Optional['MetricsCollector'] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, project_root: Optional[Path] = None):
        if self._initialized:
            return

        self.project_root = project_root or Path.cwd()
        self.observability_dir = self.project_root / ".observability"
        self.metrics_file = self.observability_dir / "metrics.jsonl"

        self.observability_dir.mkdir(parents=True, exist_ok=True)

        # 各层指标存储
        self._api_metrics: Dict[str, APICallMetrics] = {}  # key: "provider:model"
        self._generation_metrics: Dict[str, GenerationMetrics] = {}  # key: "layer:operation"
        self._retrieval_metrics: Dict[str, RetrievalMetrics] = {}  # key: retrieval_type
        self._storage_metrics: Dict[str, StorageMetrics] = {}  # key: "storage_type:operation"

        # 工作流整体指标
        self._workflow_metrics: Optional[WorkflowMetrics] = None

        # Token价格配置 (USD per 1K tokens)
        self._token_pricing = {
            "kimi": {
                "moonshot-v1-8k": {"input": 0.003, "output": 0.003},
                "moonshot-v1-32k": {"input": 0.006, "output": 0.006},
                "moonshot-v1-128k": {"input": 0.012, "output": 0.012},
            },
            "openai": {
                "gpt-4-turbo-preview": {"input": 0.01, "output": 0.03},
                "gpt-4": {"input": 0.03, "output": 0.06},
                "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
            },
            "zhipuai": {
                "glm-4": {"input": 0.007, "output": 0.007},
                "glm-3-turbo": {"input": 0.001, "output": 0.001},
            },
        }

        self._initialized = True
        logger.info(f"MetricsCollector initialized: {self.observability_dir}")

    def start_workflow(self, book_id: Optional[str] = None):
        """开始记录工作流指标"""
        self._workflow_metrics = WorkflowMetrics(
            book_id=book_id,
            start_time=datetime.now().isoformat()
        )

    def end_workflow(self):
        """结束工作流记录"""
        if self._workflow_metrics:
            self._workflow_metrics.end_time = datetime.now().isoformat()
            self._save_workflow_metrics()

    def record_api_call(
        self,
        provider: str,
        model: str,
        tokens: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        error: bool = False,
        retry: bool = False
    ):
        """记录API调用"""
        key = f"{provider}:{model}"

        if key not in self._api_metrics:
            self._api_metrics[key] = APICallMetrics(
                provider=provider,
                model=model
            )

        # 计算成本
        cost = self._calculate_cost(provider, model, prompt_tokens, completion_tokens)

        self._api_metrics[key].add_call(
            tokens=tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            error=error,
            retry=retry
        )

        # 更新工作流指标
        if self._workflow_metrics:
            self._workflow_metrics.total_api_calls += 1
            self._workflow_metrics.total_tokens += tokens
            self._workflow_metrics.total_cost_usd += cost

        # 保存到文件
        self._append_metric(MetricType.API_CALL, {
            "provider": provider,
            "model": model,
            "tokens": tokens,
            "cost_usd": cost,
            "latency_ms": latency_ms,
            "error": error
        })

    def record_generation(
        self,
        layer: str,
        operation: str,
        chars: int,
        duration_ms: float,
        success: bool = True
    ):
        """记录生成指标"""
        key = f"{layer}:{operation}"

        if key not in self._generation_metrics:
            self._generation_metrics[key] = GenerationMetrics(
                layer=layer,
                operation=operation
            )

        self._generation_metrics[key].add_generation(chars, duration_ms, success)

        # 更新工作流指标
        if self._workflow_metrics:
            self._workflow_metrics.avg_generation_time_ms = self._get_avg_generation_time()

        self._append_metric(MetricType.GENERATION, {
            "layer": layer,
            "operation": operation,
            "chars": chars,
            "duration_ms": duration_ms,
            "success": success
        })

    def record_retrieval(
        self,
        retrieval_type: str,
        duration_ms: float,
        results_count: int = 0,
        cache_hit: bool = False
    ):
        """记录检索指标"""
        if retrieval_type not in self._retrieval_metrics:
            self._retrieval_metrics[retrieval_type] = RetrievalMetrics(
                retrieval_type=retrieval_type
            )

        self._retrieval_metrics[retrieval_type].add_retrieval(
            duration_ms=duration_ms,
            results_count=results_count,
            cache_hit=cache_hit
        )

        self._append_metric(MetricType.RETRIEVAL, {
            "retrieval_type": retrieval_type,
            "duration_ms": duration_ms,
            "results_count": results_count,
            "cache_hit": cache_hit
        })

    def record_storage(
        self,
        storage_type: str,
        operation: str,
        duration_ms: float,
        bytes_count: int = 0,
        error: bool = False
    ):
        """记录存储指标"""
        key = f"{storage_type}:{operation}"

        if key not in self._storage_metrics:
            self._storage_metrics[key] = StorageMetrics(
                storage_type=storage_type,
                operation=operation
            )

        self._storage_metrics[key].add_operation(
            duration_ms=duration_ms,
            bytes_count=bytes_count,
            error=error
        )

        self._append_metric(MetricType.STORAGE, {
            "storage_type": storage_type,
            "operation": operation,
            "duration_ms": duration_ms,
            "bytes": bytes_count,
            "error": error
        })

    def record_chapter_complete(self, chapter_num: int, word_count: int):
        """记录章节完成"""
        if self._workflow_metrics:
            self._workflow_metrics.completed_chapters += 1
            # 更新平均章节长度
            n = self._workflow_metrics.completed_chapters
            old_avg = self._workflow_metrics.avg_chapter_length
            self._workflow_metrics.avg_chapter_length = (
                (old_avg * (n - 1)) + word_count
            ) / n

    def record_section_complete(self):
        """记录小节完成"""
        if self._workflow_metrics:
            self._workflow_metrics.completed_sections += 1

    def _calculate_cost(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int
    ) -> float:
        """计算API调用成本"""
        pricing = self._token_pricing.get(provider, {}).get(model, {})

        input_price = pricing.get("input", 0.0)
        output_price = pricing.get("output", 0.0)

        prompt_cost = (prompt_tokens / 1000) * input_price
        completion_cost = (completion_tokens / 1000) * output_price

        return prompt_cost + completion_cost

    def _get_avg_generation_time(self) -> float:
        """获取平均生成时间"""
        if not self._generation_metrics:
            return 0.0

        total_time = sum(m.total_duration_ms for m in self._generation_metrics.values())
        total_calls = sum(m.total_calls for m in self._generation_metrics.values())

        if total_calls == 0:
            return 0.0

        return total_time / total_calls

    def _append_metric(self, metric_type: MetricType, data: Dict[str, Any]):
        """追加指标到文件"""
        try:
            record = {
                "timestamp": datetime.now().isoformat(),
                "type": metric_type.value,
                **data
            }

            with open(self.metrics_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to append metric: {e}")

    def _save_workflow_metrics(self):
        """保存工作流指标"""
        if not self._workflow_metrics:
            return

        try:
            # 计算成功率
            total_gen = sum(m.total_calls for m in self._generation_metrics.values())
            success_gen = sum(m.success_count for m in self._generation_metrics.values())
            if total_gen > 0:
                self._workflow_metrics.success_rate = success_gen / total_gen

            # 保存到文件
            workflow_file = self.observability_dir / "workflow_metrics.json"
            with open(workflow_file, "w", encoding="utf-8") as f:
                json.dump(self._workflow_metrics.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save workflow metrics: {e}")

    def get_api_summary(self) -> Dict[str, Any]:
        """获取API调用汇总"""
        total_calls = sum(m.call_count for m in self._api_metrics.values())
        total_tokens = sum(m.total_tokens for m in self._api_metrics.values())
        total_cost = sum(m.total_cost_usd for m in self._api_metrics.values())
        total_errors = sum(m.errors for m in self._api_metrics.values())

        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "error_rate": total_errors / total_calls if total_calls > 0 else 0,
            "by_provider": {
                key: {
                    "call_count": m.call_count,
                    "total_tokens": m.total_tokens,
                    "total_cost_usd": round(m.total_cost_usd, 4),
                    "avg_latency_ms": round(m.avg_latency_ms, 2),
                    "error_rate": m.errors / m.call_count if m.call_count > 0 else 0
                }
                for key, m in self._api_metrics.items()
            }
        }

    def get_generation_summary(self) -> Dict[str, Any]:
        """获取生成指标汇总"""
        total_chars = sum(m.total_chars_generated for m in self._generation_metrics.values())
        total_time = sum(m.total_duration_ms for m in self._generation_metrics.values())

        speed = 0.0
        if total_time > 0:
            speed = (total_chars / (total_time / 1000))  # chars per second

        return {
            "total_chars_generated": total_chars,
            "avg_speed_chars_per_sec": round(speed, 2),
            "by_layer": {
                key: {
                    "total_calls": m.total_calls,
                    "total_chars": m.total_chars_generated,
                    "avg_speed": round(m.avg_speed_chars_per_sec, 2),
                    "success_rate": m.success_count / m.total_calls if m.total_calls > 0 else 0
                }
                for key, m in self._generation_metrics.items()
            }
        }

    def get_retrieval_summary(self) -> Dict[str, Any]:
        """获取检索指标汇总"""
        return {
            retrieval_type: {
                "total_calls": m.total_calls,
                "avg_latency_ms": round(m.avg_latency_ms, 2),
                "cache_hit_rate": round(m.cache_hit_rate, 2),
                "avg_results": m.total_results_returned / m.total_calls if m.total_calls > 0 else 0
            }
            for retrieval_type, m in self._retrieval_metrics.items()
        }

    def get_storage_summary(self) -> Dict[str, Any]:
        """获取存储指标汇总"""
        return {
            key: {
                "total_calls": m.total_calls,
                "avg_latency_ms": round(m.avg_latency_ms, 2),
                "total_bytes": m.total_bytes,
                "error_rate": m.errors / m.total_calls if m.total_calls > 0 else 0
            }
            for key, m in self._storage_metrics.items()
        }

    def get_full_report(self) -> Dict[str, Any]:
        """获取完整报告"""
        return {
            "timestamp": datetime.now().isoformat(),
            "workflow": self._workflow_metrics.to_dict() if self._workflow_metrics else None,
            "api_calls": self.get_api_summary(),
            "generation": self.get_generation_summary(),
            "retrieval": self.get_retrieval_summary(),
            "storage": self.get_storage_summary()
        }

    def reset(self):
        """重置所有指标"""
        self._api_metrics.clear()
        self._generation_metrics.clear()
        self._retrieval_metrics.clear()
        self._storage_metrics.clear()
        self._workflow_metrics = None


# 便捷装饰器
def track_api_call(provider_attr: str = "provider", model_attr: str = "model"):
    """API调用追踪装饰器

    Usage:
        @track_api_call()
        async def complete(self, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        async def async_wrapper(*args, **kwargs):
            collector = MetricsCollector()

            # 获取provider和model
            self_obj = args[0]
            provider = getattr(self_obj, provider_attr, "unknown")
            model = getattr(self_obj, model_attr, "unknown")

            start_time = datetime.now()
            error = False

            try:
                result = await func(*args, **kwargs)

                # 尝试从结果中提取token信息
                prompt_tokens = 0
                completion_tokens = 0
                total_tokens = 0

                if isinstance(result, dict):
                    prompt_tokens = result.get("prompt_tokens", 0)
                    completion_tokens = result.get("completion_tokens", 0)
                    total_tokens = result.get("total_tokens", 0)

                duration_ms = (datetime.now() - start_time).total_seconds() * 1000

                collector.record_api_call(
                    provider=provider,
                    model=model,
                    tokens=total_tokens,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=duration_ms,
                    error=False
                )

                return result

            except Exception as e:
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                collector.record_api_call(
                    provider=provider,
                    model=model,
                    latency_ms=duration_ms,
                    error=True
                )
                raise

        return async_wrapper
    return decorator


def track_generation(layer: str, operation: Optional[str] = None):
    """生成追踪装饰器"""
    def decorator(func: Callable) -> Callable:
        op_name = operation or func.__name__

        async def async_wrapper(*args, **kwargs):
            collector = MetricsCollector()
            start_time = datetime.now()
            success = True

            try:
                result = await func(*args, **kwargs)

                # 计算字符数
                chars = 0
                if isinstance(result, str):
                    chars = len(result)
                elif hasattr(result, "content"):
                    chars = len(result.content)
                elif hasattr(result, "word_count"):
                    chars = result.word_count

                duration_ms = (datetime.now() - start_time).total_seconds() * 1000

                collector.record_generation(
                    layer=layer,
                    operation=op_name,
                    chars=chars,
                    duration_ms=duration_ms,
                    success=True
                )

                return result

            except Exception as e:
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                collector.record_generation(
                    layer=layer,
                    operation=op_name,
                    chars=0,
                    duration_ms=duration_ms,
                    success=False
                )
                raise

        return async_wrapper
    return decorator


def get_collector(project_root: Optional[Path] = None) -> MetricsCollector:
    """获取全局收集器实例"""
    return MetricsCollector(project_root=project_root)
