"""六维并行审查系统

六维审查体系:
1. 高潮检查 (HighPointChecker) - 情感高潮、人生转折点、关键决策时刻
2. 一致性检查 (ConsistencyChecker) - 时间线、地点、人物关系一致性
3. 节奏检查 (PacingChecker) - 叙事节奏分布、时间跳跃合理性
4. OOC检查 (OOCChecker) - 人物言行是否符合人设
5. 连贯性检查 (ContinuityChecker) - 章节间过渡流畅度
6. 阅读吸引力检查 (ReaderPullChecker) - 开头钩子、悬念设置
"""

from .base_checker import BaseChecker, ReviewReport, ReviewIssue, IssueSeverity
from .high_point_checker import HighPointChecker
from .consistency_checker import ConsistencyChecker
from .pacing_checker import PacingChecker
from .ooc_checker import OOCChecker
from .continuity_checker import ContinuityChecker
from .reader_pull_checker import ReaderPullChecker
from .parallel_review import ParallelReview, ParallelReviewResult, ReviewDimension, quick_review, review_chapter

__all__ = [
    'BaseChecker',
    'ReviewReport',
    'ReviewIssue',
    'IssueSeverity',
    'HighPointChecker',
    'ConsistencyChecker',
    'PacingChecker',
    'OOCChecker',
    'ContinuityChecker',
    'ReaderPullChecker',
    'ParallelReview',
    'ParallelReviewResult',
    'ReviewDimension',
]
