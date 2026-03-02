"""健康报告生成器 - 生成工作流健康报告

功能：
1. 各层执行时间统计
2. 成功率统计
3. 错误类型分布
4. 性能瓶颈识别
5. 健康评分
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum
from loguru import logger

from .workflow_tracer import WorkflowTracer, TraceEvent, TraceStatus
from .metrics_collector import MetricsCollector


class HealthStatus(str, Enum):
    """健康状态"""
    HEALTHY = "healthy"         # 健康
    WARNING = "warning"         # 警告
    CRITICAL = "critical"       # 严重
    UNKNOWN = "unknown"         # 未知


@dataclass
class LayerHealth:
    """层健康状态"""
    layer_name: str
    total_operations: int = 0
    success_count: int = 0
    failure_count: int = 0
    avg_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    min_duration_ms: float = float('inf')
    error_types: Dict[str, int] = field(default_factory=dict)
    status: str = HealthStatus.UNKNOWN

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_operations == 0:
            return 0.0
        return self.success_count / self.total_operations


@dataclass
class HealthReport:
    """健康报告"""
    timestamp: str
    book_id: Optional[str]
    overall_status: str
    health_score: float  # 0-100
    duration_seconds: float

    # 各层统计
    layer_health: Dict[str, LayerHealth]

    # 整体统计
    total_operations: int
    total_success: int
    total_failures: int
    overall_success_rate: float

    # 性能统计
    avg_operation_time_ms: float
    slowest_layer: Optional[str]
    fastest_layer: Optional[str]

    # 错误分析
    error_distribution: Dict[str, int]
    most_common_error: Optional[str]

    # 步骤序列分析
    step_sequence_violations: List[Dict]
    dependency_violations: List[Dict]

    # 建议
    recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp,
            "book_id": self.book_id,
            "overall_status": self.overall_status,
            "health_score": round(self.health_score, 2),
            "duration_seconds": round(self.duration_seconds, 2),
            "layer_health": {
                name: {
                    "total_operations": lh.total_operations,
                    "success_rate": round(lh.success_rate, 2),
                    "avg_duration_ms": round(lh.avg_duration_ms, 2),
                    "max_duration_ms": round(lh.max_duration_ms, 2),
                    "min_duration_ms": round(lh.min_duration_ms, 2) if lh.min_duration_ms != float('inf') else 0,
                    "error_types": lh.error_types,
                    "status": lh.status
                }
                for name, lh in self.layer_health.items()
            },
            "overall": {
                "total_operations": self.total_operations,
                "total_success": self.total_success,
                "total_failures": self.total_failures,
                "success_rate": round(self.overall_success_rate, 2)
            },
            "performance": {
                "avg_operation_time_ms": round(self.avg_operation_time_ms, 2),
                "slowest_layer": self.slowest_layer,
                "fastest_layer": self.fastest_layer
            },
            "errors": {
                "distribution": self.error_distribution,
                "most_common": self.most_common_error
            },
            "workflow": {
                "step_sequence_violations": self.step_sequence_violations,
                "dependency_violations": self.dependency_violations
            },
            "recommendations": self.recommendations
        }

    def to_markdown(self) -> str:
        """生成Markdown格式报告"""
        lines = [
            "# 工作流健康报告",
            "",
            f"**生成时间**: {self.timestamp}",
            f"**项目ID**: {self.book_id or 'N/A'}",
            f"**整体状态**: {self._status_emoji(self.overall_status)} {self.overall_status.upper()}",
            f"**健康评分**: {self.health_score:.1f}/100",
            "",
            "## 总体统计",
            "",
            f"- 总操作数: {self.total_operations}",
            f"- 成功: {self.total_success}",
            f"- 失败: {self.total_failures}",
            f"- 成功率: {self.overall_success_rate:.1%}",
            "",
            "## 各层健康状态",
            ""
        ]

        for layer_name, lh in self.layer_health.items():
            lines.extend([
                f"### {layer_name}",
                "",
                f"- 状态: {self._status_emoji(lh.status)} {lh.status}",
                f"- 操作数: {lh.total_operations}",
                f"- 成功率: {lh.success_rate:.1%}",
                f"- 平均耗时: {lh.avg_duration_ms:.1f}ms",
                f"- 最大耗时: {lh.max_duration_ms:.1f}ms",
                ""
            ])

        lines.extend([
            "## 性能分析",
            "",
            f"- 平均操作时间: {self.avg_operation_time_ms:.1f}ms",
            f"- 最慢层: {self.slowest_layer or 'N/A'}",
            f"- 最快层: {self.fastest_layer or 'N/A'}",
            ""
        ])

        if self.error_distribution:
            lines.extend([
                "## 错误分布",
                ""
            ])
            for error_type, count in sorted(self.error_distribution.items(), key=lambda x: -x[1]):
                lines.append(f"- {error_type}: {count}次")
            lines.append("")

        if self.step_sequence_violations or self.dependency_violations:
            lines.extend([
                "## 工作流问题",
                ""
            ])

            if self.step_sequence_violations:
                lines.append("### 步骤顺序违规")
                for v in self.step_sequence_violations:
                    lines.append(f"- {v.get('step_id', 'Unknown')}: 期望顺序{v.get('expected_order')}, 实际{v.get('actual_order')}")
                lines.append("")

            if self.dependency_violations:
                lines.append("### 依赖违规")
                for v in self.dependency_violations:
                    lines.append(f"- {v.get('step_id', 'Unknown')}: 缺少依赖 {v.get('missing_dependency')}")
                lines.append("")

        if self.recommendations:
            lines.extend([
                "## 优化建议",
                ""
            ])
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")

        return "\n".join(lines)

    def _status_emoji(self, status: str) -> str:
        """状态表情"""
        return {
            HealthStatus.HEALTHY: "✅",
            HealthStatus.WARNING: "⚠️",
            HealthStatus.CRITICAL: "❌",
            HealthStatus.UNKNOWN: "❓"
        }.get(status, "❓")


class HealthReporter:
    """健康报告生成器"""

    def __init__(
        self,
        project_root: Optional[Path] = None,
        tracer: Optional[WorkflowTracer] = None,
        collector: Optional[MetricsCollector] = None
    ):
        self.project_root = project_root or Path.cwd()
        self.observability_dir = self.project_root / ".observability"
        self.reports_dir = self.observability_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self.tracer = tracer or WorkflowTracer(project_root=project_root)
        self.collector = collector or MetricsCollector(project_root=project_root)

        # 阈值配置
        self.thresholds = {
            "success_rate_warning": 0.9,    # 成功率低于90%警告
            "success_rate_critical": 0.7,   # 成功率低于70%严重
            "latency_warning_ms": 5000,     # 5秒以上警告
            "latency_critical_ms": 10000,   # 10秒以上严重
        }

    def generate_report(self, book_id: Optional[str] = None) -> HealthReport:
        """生成健康报告"""
        start_time = datetime.now()

        # 读取追踪数据
        traces = self._load_traces(book_id)

        # 分析各层健康状态
        layer_health = self._analyze_layer_health(traces)

        # 计算整体统计
        total_operations = sum(lh.total_operations for lh in layer_health.values())
        total_success = sum(lh.success_count for lh in layer_health.values())
        total_failures = sum(lh.failure_count for lh in layer_health.values())
        overall_success_rate = total_success / total_operations if total_operations > 0 else 0.0

        # 性能分析
        avg_time = sum(lh.avg_duration_ms for lh in layer_health.values()) / len(layer_health) if layer_health else 0
        slowest = max(layer_health.items(), key=lambda x: x[1].avg_duration_ms)[0] if layer_health else None
        fastest = min(layer_health.items(), key=lambda x: x[1].avg_duration_ms)[0] if layer_health else None

        # 错误分析
        error_dist = self._aggregate_errors(layer_health)
        most_common = max(error_dist.items(), key=lambda x: x[1])[0] if error_dist else None

        # 步骤序列分析
        step_violations = self.tracer.get_step_sequence_report().get("step_order_violations", [])
        dep_violations = [v for v in step_violations if v.get("type") == "dependency_violation"]
        seq_violations = [v for v in step_violations if v.get("type") == "order_violation"]

        # 生成建议
        recommendations = self._generate_recommendations(
            layer_health, overall_success_rate, error_dist, step_violations
        )

        # 计算健康评分
        health_score = self._calculate_health_score(
            layer_health, overall_success_rate, step_violations
        )

        # 确定整体状态
        overall_status = self._determine_overall_status(
            health_score, overall_success_rate, layer_health
        )

        duration = (datetime.now() - start_time).total_seconds()

        report = HealthReport(
            timestamp=datetime.now().isoformat(),
            book_id=book_id,
            overall_status=overall_status,
            health_score=health_score,
            duration_seconds=duration,
            layer_health=layer_health,
            total_operations=total_operations,
            total_success=total_success,
            total_failures=total_failures,
            overall_success_rate=overall_success_rate,
            avg_operation_time_ms=avg_time,
            slowest_layer=slowest,
            fastest_layer=fastest,
            error_distribution=error_dist,
            most_common_error=most_common,
            step_sequence_violations=seq_violations,
            dependency_violations=dep_violations,
            recommendations=recommendations
        )

        # 保存报告
        self._save_report(report)

        return report

    def _load_traces(self, book_id: Optional[str] = None) -> List[TraceEvent]:
        """加载追踪数据"""
        return self.tracer.read_traces(book_id=book_id, limit=10000)

    def _analyze_layer_health(self, traces: List[TraceEvent]) -> Dict[str, LayerHealth]:
        """分析各层健康状态"""
        layer_stats = defaultdict(lambda: {
            "durations": [],
            "success": 0,
            "failure": 0,
            "errors": defaultdict(int)
        })

        for trace in traces:
            layer = trace.layer

            if trace.status == TraceStatus.COMPLETED:
                layer_stats[layer]["success"] += 1
            elif trace.status == TraceStatus.FAILED:
                layer_stats[layer]["failure"] += 1
                if trace.error:
                    layer_stats[layer]["errors"][trace.error[:50]] += 1

            if trace.duration_ms > 0:
                layer_stats[layer]["durations"].append(trace.duration_ms)

        layer_health = {}
        for layer_name, stats in layer_stats.items():
            durations = stats["durations"]

            lh = LayerHealth(
                layer_name=layer_name,
                total_operations=stats["success"] + stats["failure"],
                success_count=stats["success"],
                failure_count=stats["failure"],
                avg_duration_ms=sum(durations) / len(durations) if durations else 0,
                max_duration_ms=max(durations) if durations else 0,
                min_duration_ms=min(durations) if durations else float('inf'),
                error_types=dict(stats["errors"])
            )

            # 确定层状态
            if lh.success_rate < self.thresholds["success_rate_critical"]:
                lh.status = HealthStatus.CRITICAL
            elif lh.success_rate < self.thresholds["success_rate_warning"]:
                lh.status = HealthStatus.WARNING
            elif lh.avg_duration_ms > self.thresholds["latency_critical_ms"]:
                lh.status = HealthStatus.WARNING
            else:
                lh.status = HealthStatus.HEALTHY

            layer_health[layer_name] = lh

        return layer_health

    def _aggregate_errors(self, layer_health: Dict[str, LayerHealth]) -> Dict[str, int]:
        """聚合错误分布"""
        error_dist = defaultdict(int)
        for lh in layer_health.values():
            for error_type, count in lh.error_types.items():
                error_dist[error_type] += count
        return dict(error_dist)

    def _generate_recommendations(
        self,
        layer_health: Dict[str, LayerHealth],
        overall_success_rate: float,
        error_dist: Dict[str, int],
        step_violations: List[Dict]
    ) -> List[str]:
        """生成优化建议"""
        recommendations = []

        # 成功率建议
        if overall_success_rate < self.thresholds["success_rate_critical"]:
            recommendations.append("整体成功率过低，建议检查系统配置和依赖服务状态")
        elif overall_success_rate < self.thresholds["success_rate_warning"]:
            recommendations.append("成功率有提升空间，建议分析失败原因")

        # 各层建议
        for layer_name, lh in layer_health.items():
            if lh.status == HealthStatus.CRITICAL:
                recommendations.append(f"{layer_name}层状态严重，建议立即检查")
            elif lh.status == HealthStatus.WARNING:
                if lh.success_rate < self.thresholds["success_rate_warning"]:
                    recommendations.append(f"{layer_name}层成功率较低，建议优化错误处理")
                if lh.avg_duration_ms > self.thresholds["latency_warning_ms"]:
                    recommendations.append(f"{layer_name}层响应较慢，建议优化性能")

        # 错误类型建议
        for error_type in error_dist.keys():
            if "timeout" in error_type.lower():
                recommendations.append(f"检测到超时错误: {error_type}，建议增加超时时间或优化性能")
            elif "rate limit" in error_type.lower() or "rate_limit" in error_type.lower():
                recommendations.append(f"检测到限流错误，建议降低请求频率或增加重试间隔")
            elif "connection" in error_type.lower():
                recommendations.append(f"检测到连接错误，建议检查网络连接和服务可用性")

        # 步骤序列建议
        if step_violations:
            recommendations.append(f"检测到{len(step_violations)}个工作流顺序问题，建议检查流程逻辑")

        return recommendations

    def _calculate_health_score(
        self,
        layer_health: Dict[str, LayerHealth],
        overall_success_rate: float,
        step_violations: List[Dict]
    ) -> float:
        """计算健康评分 (0-100)"""
        score = 100.0

        # 成功率扣分
        if overall_success_rate < 1.0:
            score -= (1.0 - overall_success_rate) * 30

        # 层状态扣分
        for lh in layer_health.values():
            if lh.status == HealthStatus.CRITICAL:
                score -= 15
            elif lh.status == HealthStatus.WARNING:
                score -= 5

        # 步骤违规扣分
        score -= len(step_violations) * 5

        return max(0.0, min(100.0, score))

    def _determine_overall_status(
        self,
        health_score: float,
        overall_success_rate: float,
        layer_health: Dict[str, LayerHealth]
    ) -> str:
        """确定整体状态"""
        # 检查是否有严重层
        critical_layers = sum(1 for lh in layer_health.values() if lh.status == HealthStatus.CRITICAL)
        if critical_layers > 0 or health_score < 50:
            return HealthStatus.CRITICAL

        # 检查是否有警告层
        warning_layers = sum(1 for lh in layer_health.values() if lh.status == HealthStatus.WARNING)
        if warning_layers > 0 or health_score < 80 or overall_success_rate < self.thresholds["success_rate_warning"]:
            return HealthStatus.WARNING

        return HealthStatus.HEALTHY

    def _save_report(self, report: HealthReport):
        """保存报告"""
        try:
            # JSON格式
            json_file = self.reports_dir / f"health_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

            # Markdown格式
            md_file = self.reports_dir / f"health_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            with open(md_file, "w", encoding="utf-8") as f:
                f.write(report.to_markdown())

            logger.info(f"Health report saved: {json_file}")
        except Exception as e:
            logger.error(f"Failed to save health report: {e}")

    def get_latest_report(self) -> Optional[HealthReport]:
        """获取最新报告"""
        try:
            report_files = sorted(self.reports_dir.glob("health_report_*.json"), reverse=True)
            if not report_files:
                return None

            with open(report_files[0], "r", encoding="utf-8") as f:
                data = json.load(f)

            # 简化的重建逻辑
            return self.generate_report(data.get("book_id"))
        except Exception as e:
            logger.error(f"Failed to load latest report: {e}")
            return None

    def compare_reports(self, report1: HealthReport, report2: HealthReport) -> Dict[str, Any]:
        """比较两份报告"""
        return {
            "health_score_delta": report2.health_score - report1.health_score,
            "success_rate_delta": report2.overall_success_rate - report1.overall_success_rate,
            "operations_delta": report2.total_operations - report1.total_operations,
            "layer_comparison": {
                layer: {
                    "success_rate_delta": (
                        report2.layer_health[layer].success_rate -
                        report1.layer_health[layer].success_rate
                    ) if layer in report1.layer_health and layer in report2.layer_health else None
                }
                for layer in set(report1.layer_health.keys()) | set(report2.layer_health.keys())
            }
        }


def get_reporter(
    project_root: Optional[Path] = None,
    tracer: Optional[WorkflowTracer] = None,
    collector: Optional[MetricsCollector] = None
) -> HealthReporter:
    """获取健康报告生成器实例"""
    return HealthReporter(
        project_root=project_root,
        tracer=tracer,
        collector=collector
    )
