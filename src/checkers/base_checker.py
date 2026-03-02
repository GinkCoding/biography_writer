"""审查基类定义"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class IssueSeverity(Enum):
    """问题严重级别"""
    CRITICAL = "critical"      # 严重问题，必须修复
    HIGH = "high"              # 高优先级问题
    MEDIUM = "medium"          # 中等问题
    LOW = "low"                # 低优先级建议
    INFO = "info"              # 信息提示


@dataclass
class ReviewIssue:
    """审查发现的问题"""
    issue_id: str                           # 问题唯一标识
    dimension: str                          # 所属维度
    severity: IssueSeverity                 # 严重级别
    chapter_id: Optional[str]               # 相关章节ID
    location: Optional[str]                 # 问题位置（段落/行号）
    description: str                        # 问题描述
    suggestion: Optional[str] = None        # 修复建议
    evidence: Optional[str] = None          # 证据文本
    fix_priority: int = 5                   # 修复优先级 1-10


@dataclass
class DimensionScore:
    """维度评分"""
    dimension_name: str                     # 维度名称
    score: float                            # 分数 0-100
    weight: float = 1.0                     # 权重
    details: Dict[str, Any] = field(default_factory=dict)  # 详细评分项


@dataclass
class ReviewReport:
    """审查报告"""
    # 基本信息
    chapter_id: str
    chapter_title: Optional[str] = None
    review_timestamp: datetime = field(default_factory=datetime.now)

    # 评分
    overall_score: float = 0.0              # 综合得分 0-100
    dimension_scores: Dict[str, DimensionScore] = field(default_factory=dict)

    # 问题与建议
    issues: List[ReviewIssue] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    # 元数据
    reviewer_name: Optional[str] = None
    review_duration_ms: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_critical_issues(self) -> List[ReviewIssue]:
        """获取严重问题"""
        return [i for i in self.issues if i.severity == IssueSeverity.CRITICAL]

    def get_high_priority_issues(self) -> List[ReviewIssue]:
        """获取高优先级问题"""
        return [i for i in self.issues if i.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH)]

    def get_issues_by_dimension(self, dimension: str) -> List[ReviewIssue]:
        """按维度获取问题"""
        return [i for i in self.issues if i.dimension == dimension]

    def has_critical_issues(self) -> bool:
        """是否存在严重问题"""
        return any(i.severity == IssueSeverity.CRITICAL for i in self.issues)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "chapter_id": self.chapter_id,
            "chapter_title": self.chapter_title,
            "review_timestamp": self.review_timestamp.isoformat(),
            "overall_score": self.overall_score,
            "dimension_scores": {
                k: {
                    "dimension_name": v.dimension_name,
                    "score": v.score,
                    "weight": v.weight,
                    "details": v.details
                }
                for k, v in self.dimension_scores.items()
            },
            "issues": [
                {
                    "issue_id": i.issue_id,
                    "dimension": i.dimension,
                    "severity": i.severity.value,
                    "chapter_id": i.chapter_id,
                    "location": i.location,
                    "description": i.description,
                    "suggestion": i.suggestion,
                    "evidence": i.evidence,
                    "fix_priority": i.fix_priority
                }
                for i in self.issues
            ],
            "suggestions": self.suggestions,
            "reviewer_name": self.reviewer_name,
            "review_duration_ms": self.review_duration_ms,
            "metadata": self.metadata
        }


class BaseChecker(ABC):
    """审查器基类"""

    def __init__(self, checker_name: str, description: str = ""):
        self.checker_name = checker_name
        self.description = description
        self.config: Dict[str, Any] = {}

    def configure(self, config: Dict[str, Any]) -> 'BaseChecker':
        """配置检查器"""
        self.config.update(config)
        return self

    @abstractmethod
    def check(self, chapter_content: str, context: Dict[str, Any]) -> ReviewReport:
        """
        执行审查

        Args:
            chapter_content: 章节内容
            context: 上下文信息，包含:
                - chapter_id: 章节ID
                - chapter_title: 章节标题
                - previous_chapters: 前序章节内容列表
                - character_profiles: 人物画像
                - timeline: 时间线信息
                - book_outline: 书籍大纲
                - settings: 设定信息

        Returns:
            ReviewReport: 审查报告
        """
        pass

    def _create_report(self, chapter_id: str, chapter_title: Optional[str] = None) -> ReviewReport:
        """创建基础报告"""
        return ReviewReport(
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            reviewer_name=self.checker_name
        )

    def _add_issue(self, report: ReviewReport, issue: ReviewIssue) -> None:
        """添加问题到报告"""
        report.issues.append(issue)

    def _calculate_overall_score(self, report: ReviewReport) -> float:
        """
        计算综合得分
        基于各维度加权平均，并扣除严重问题扣分
        """
        if not report.dimension_scores:
            return 0.0

        # 加权平均分
        total_weight = sum(ds.weight for ds in report.dimension_scores.values())
        if total_weight == 0:
            return 0.0

        weighted_sum = sum(
            ds.score * ds.weight
            for ds in report.dimension_scores.values()
        )
        base_score = weighted_sum / total_weight

        # 严重问题扣分
        critical_count = len(report.get_critical_issues())
        high_count = len([i for i in report.issues if i.severity == IssueSeverity.HIGH])

        penalty = critical_count * 15 + high_count * 5
        final_score = max(0.0, base_score - penalty)

        return round(final_score, 2)

    def _generate_suggestions(self, report: ReviewReport) -> List[str]:
        """基于问题生成建议"""
        suggestions = []

        for issue in report.issues:
            if issue.suggestion:
                suggestions.append(f"[{issue.dimension}] {issue.suggestion}")

        return suggestions
