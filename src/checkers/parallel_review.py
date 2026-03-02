"""并行审查系统

实现六维并行审查的执行和结果汇总
"""
import asyncio
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

from .base_checker import BaseChecker, ReviewReport, ReviewIssue, IssueSeverity, DimensionScore
from .high_point_checker import HighPointChecker
from .consistency_checker import ConsistencyChecker
from .pacing_checker import PacingChecker
from .ooc_checker import OOCChecker
from .continuity_checker import ContinuityChecker
from .reader_pull_checker import ReaderPullChecker

logger = logging.getLogger(__name__)


class ReviewDimension(Enum):
    """审查维度枚举"""
    HIGHPOINT = "highpoint"
    CONSISTENCY = "consistency"
    PACING = "pacing"
    OOC = "ooc"
    CONTINUITY = "continuity"
    READER_PULL = "reader_pull"


@dataclass
class ParallelReviewResult:
    """并行审查结果"""
    chapter_id: str
    chapter_title: Optional[str]
    overall_score: float
    dimension_reports: Dict[str, ReviewReport]
    aggregated_issues: List[ReviewIssue]
    critical_issues_count: int
    high_priority_issues_count: int
    total_issues_count: int
    review_duration_ms: int
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "chapter_id": self.chapter_id,
            "chapter_title": self.chapter_title,
            "overall_score": self.overall_score,
            "dimension_reports": {
                dim: report.to_dict()
                for dim, report in self.dimension_reports.items()
            },
            "aggregated_issues": [
                {
                    "issue_id": i.issue_id,
                    "dimension": i.dimension,
                    "severity": i.severity.value,
                    "chapter_id": i.chapter_id,
                    "location": i.location,
                    "description": i.description,
                    "suggestion": i.suggestion,
                    "fix_priority": i.fix_priority
                }
                for i in self.aggregated_issues
            ],
            "critical_issues_count": self.critical_issues_count,
            "high_priority_issues_count": self.high_priority_issues_count,
            "total_issues_count": self.total_issues_count,
            "review_duration_ms": self.review_duration_ms,
            "timestamp": self.timestamp.isoformat()
        }


class ParallelReview:
    """
    并行审查系统

    协调六个维度的并行审查，汇总结果并生成综合报告
    """

    # 维度权重配置
    DIMENSION_WEIGHTS = {
        ReviewDimension.HIGHPOINT: 1.2,
        ReviewDimension.CONSISTENCY: 1.0,
        ReviewDimension.PACING: 1.0,
        ReviewDimension.OOC: 1.1,
        ReviewDimension.CONTINUITY: 1.0,
        ReviewDimension.READER_PULL: 1.2,
    }

    # 维度检查器映射
    CHECKER_CLASSES = {
        ReviewDimension.HIGHPOINT: HighPointChecker,
        ReviewDimension.CONSISTENCY: ConsistencyChecker,
        ReviewDimension.PACING: PacingChecker,
        ReviewDimension.OOC: OOCChecker,
        ReviewDimension.CONTINUITY: ContinuityChecker,
        ReviewDimension.READER_PULL: ReaderPullChecker,
    }

    def __init__(self, max_workers: int = 6):
        self.max_workers = max_workers
        self.checkers: Dict[ReviewDimension, BaseChecker] = {}
        self._init_checkers()

    def _init_checkers(self) -> None:
        """初始化所有检查器"""
        for dimension, checker_class in self.CHECKER_CLASSES.items():
            try:
                self.checkers[dimension] = checker_class()
                logger.info(f"Initialized {dimension.value} checker")
            except Exception as e:
                logger.error(f"Failed to initialize {dimension.value} checker: {e}")

    def configure_checker(self, dimension: ReviewDimension, config: Dict[str, Any]) -> 'ParallelReview':
        """配置特定维度的检查器"""
        if dimension in self.checkers:
            self.checkers[dimension].configure(config)
        return self

    def review(
        self,
        chapter_content: str,
        context: Dict[str, Any],
        dimensions: Optional[List[ReviewDimension]] = None
    ) -> ParallelReviewResult:
        """
        执行并行审查

        Args:
            chapter_content: 章节内容
            context: 上下文信息
            dimensions: 指定审查维度，None表示全部

        Returns:
            ParallelReviewResult: 并行审查结果
        """
        start_time = time.time()

        chapter_id = context.get("chapter_id", "unknown")
        chapter_title = context.get("chapter_title", "")

        # 确定要执行的维度
        target_dimensions = dimensions or list(ReviewDimension)

        # 执行并行审查
        dimension_reports = self._execute_parallel_review(
            chapter_content, context, target_dimensions
        )

        # 汇总结果
        aggregated_issues = self._aggregate_issues(dimension_reports)

        # 计算综合得分
        overall_score = self._calculate_overall_score(dimension_reports)

        # 统计问题
        critical_count = sum(
            1 for i in aggregated_issues if i.severity == IssueSeverity.CRITICAL
        )
        high_count = sum(
            1 for i in aggregated_issues
            if i.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH)
        )

        duration_ms = int((time.time() - start_time) * 1000)

        result = ParallelReviewResult(
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            overall_score=overall_score,
            dimension_reports=dimension_reports,
            aggregated_issues=aggregated_issues,
            critical_issues_count=critical_count,
            high_priority_issues_count=high_count,
            total_issues_count=len(aggregated_issues),
            review_duration_ms=duration_ms
        )

        logger.info(
            f"Parallel review completed for {chapter_id}: "
            f"score={overall_score}, issues={len(aggregated_issues)}, "
            f"duration={duration_ms}ms"
        )

        return result

    def _execute_parallel_review(
        self,
        chapter_content: str,
        context: Dict[str, Any],
        dimensions: List[ReviewDimension]
    ) -> Dict[str, ReviewReport]:
        """执行并行审查"""
        dimension_reports = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有审查任务
            future_to_dimension = {}
            for dimension in dimensions:
                if dimension in self.checkers:
                    future = executor.submit(
                        self._run_checker,
                        self.checkers[dimension],
                        chapter_content,
                        context
                    )
                    future_to_dimension[future] = dimension

            # 收集结果
            for future in as_completed(future_to_dimension):
                dimension = future_to_dimension[future]
                try:
                    report = future.result(timeout=60)  # 60秒超时
                    dimension_reports[dimension.value] = report
                except Exception as e:
                    logger.error(f"Checker {dimension.value} failed: {e}")
                    # 创建错误报告
                    dimension_reports[dimension.value] = self._create_error_report(
                        context.get("chapter_id", "unknown"),
                        dimension.value,
                        str(e)
                    )

        return dimension_reports

    def _run_checker(
        self,
        checker: BaseChecker,
        chapter_content: str,
        context: Dict[str, Any]
    ) -> ReviewReport:
        """运行单个检查器"""
        try:
            return checker.check(chapter_content, context)
        except Exception as e:
            logger.error(f"Checker {checker.checker_name} failed: {e}")
            raise

    def _create_error_report(self, chapter_id: str, dimension: str, error_msg: str) -> ReviewReport:
        """创建错误报告"""
        report = ReviewReport(
            chapter_id=chapter_id,
            reviewer_name=f"{dimension}_checker",
            overall_score=0
        )
        report.dimension_scores[dimension] = DimensionScore(
            dimension_name=f"{dimension}检查",
            score=0,
            details={"error": error_msg}
        )
        report.issues.append(ReviewIssue(
            issue_id=f"ERR_{dimension.upper()}",
            dimension=dimension,
            severity=IssueSeverity.CRITICAL,
            chapter_id=chapter_id,
            description=f"检查器执行失败: {error_msg}",
            suggestion="请检查系统配置或联系技术支持"
        ))
        return report

    def _aggregate_issues(self, dimension_reports: Dict[str, ReviewReport]) -> List[ReviewIssue]:
        """汇总所有维度的问题"""
        all_issues = []

        for dimension, report in dimension_reports.items():
            for issue in report.issues:
                # 确保维度信息正确
                if not issue.dimension:
                    issue.dimension = dimension
                all_issues.append(issue)

        # 按严重级别和优先级排序
        severity_order = {
            IssueSeverity.CRITICAL: 0,
            IssueSeverity.HIGH: 1,
            IssueSeverity.MEDIUM: 2,
            IssueSeverity.LOW: 3,
            IssueSeverity.INFO: 4
        }

        all_issues.sort(key=lambda i: (severity_order.get(i.severity, 5), i.fix_priority))

        return all_issues

    def _calculate_overall_score(self, dimension_reports: Dict[str, ReviewReport]) -> float:
        """计算综合得分"""
        if not dimension_reports:
            return 0.0

        total_weight = 0.0
        weighted_sum = 0.0

        for dimension, report in dimension_reports.items():
            dim_enum = ReviewDimension(dimension)
            weight = self.DIMENSION_WEIGHTS.get(dim_enum, 1.0)

            # 使用维度的综合得分
            score = report.overall_score
            if not score and dimension in report.dimension_scores:
                score = report.dimension_scores[dimension].score

            weighted_sum += score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0

        base_score = weighted_sum / total_weight

        # 严重问题扣分
        critical_count = sum(
            1 for r in dimension_reports.values()
            for i in r.issues if i.severity == IssueSeverity.CRITICAL
        )

        penalty = critical_count * 10
        final_score = max(0.0, base_score - penalty)

        return round(final_score, 2)

    def get_dimension_summary(self, result: ParallelReviewResult) -> Dict[str, Any]:
        """获取维度摘要"""
        summary = {}

        for dimension, report in result.dimension_reports.items():
            dim_score = report.dimension_scores.get(dimension)
            summary[dimension] = {
                "score": dim_score.score if dim_score else report.overall_score,
                "issues_count": len(report.issues),
                "critical_issues": len([i for i in report.issues if i.severity == IssueSeverity.CRITICAL]),
                "status": "PASS" if (dim_score and dim_score.score >= 70) else "FAIL"
            }

        return summary

    def generate_review_summary(self, result: ParallelReviewResult) -> str:
        """生成审查摘要文本"""
        lines = [
            f"=== 六维并行审查报告 ===",
            f"章节: {result.chapter_id} {result.chapter_title or ''}",
            f"综合得分: {result.overall_score}/100",
            f"审查耗时: {result.review_duration_ms}ms",
            f"",
            f"问题统计:",
            f"  - 严重问题: {result.critical_issues_count}",
            f"  - 高优先级: {result.high_priority_issues_count}",
            f"  - 总计: {result.total_issues_count}",
            f"",
            f"各维度得分:",
        ]

        for dimension, report in result.dimension_reports.items():
            dim_score = report.dimension_scores.get(dimension)
            score = dim_score.score if dim_score else report.overall_score
            lines.append(f"  - {dimension}: {score}/100")

        if result.aggregated_issues:
            lines.extend([
                f"",
                f"待修复问题 (Top 5):",
            ])
            for issue in result.aggregated_issues[:5]:
                lines.append(f"  [{issue.severity.value}] {issue.dimension}: {issue.description[:50]}...")

        return "\n".join(lines)


# 便捷函数
def review_chapter(
    chapter_content: str,
    context: Dict[str, Any],
    dimensions: Optional[List[ReviewDimension]] = None,
    max_workers: int = 6
) -> ParallelReviewResult:
    """
    便捷函数：审查单个章节

    Args:
        chapter_content: 章节内容
        context: 上下文信息
        dimensions: 指定审查维度
        max_workers: 最大并行数

    Returns:
        ParallelReviewResult: 审查结果
    """
    reviewer = ParallelReview(max_workers=max_workers)
    return reviewer.review(chapter_content, context, dimensions)


def quick_review(chapter_content: str, chapter_id: str = "unknown") -> Dict[str, Any]:
    """
    快速审查：简化版审查

    Args:
        chapter_content: 章节内容
        chapter_id: 章节ID

    Returns:
        Dict: 简化审查结果
    """
    context = {"chapter_id": chapter_id}
    result = review_chapter(chapter_content, context)

    return {
        "chapter_id": result.chapter_id,
        "overall_score": result.overall_score,
        "pass": result.overall_score >= 60 and result.critical_issues_count == 0,
        "critical_issues": result.critical_issues_count,
        "total_issues": result.total_issues_count,
        "dimension_scores": {
            dim: (report.dimension_scores.get(dim).score if report.dimension_scores.get(dim) else report.overall_score)
            for dim, report in result.dimension_reports.items()
        }
    }
