"""节奏检查器 (PacingChecker)

传记场景：
- 叙事节奏分布（快/慢章节比例）
- 避免连续多章平淡叙述
- 检查时间跳跃合理性
"""
import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .base_checker import BaseChecker, ReviewReport, ReviewIssue, IssueSeverity, DimensionScore


class PacingType(Enum):
    """节奏类型"""
    FAST = "fast"           # 快节奏 - 事件密集
    MODERATE = "moderate"   # 中等节奏
    SLOW = "slow"           # 慢节奏 - 描写细腻
    REFLECTIVE = "reflective"  # 反思型 - 内心独白


@dataclass
class PacingSegment:
    """节奏段落"""
    segment_type: PacingType
    start_pos: int
    end_pos: int
    word_count: int
    description: str


class PacingChecker(BaseChecker):
    """
    节奏检查器

    检查传记叙事的：
    1. 节奏分布 - 快慢节奏的平衡
    2. 时间跳跃 - 时间跨度的合理性
    3. 叙事密度 - 事件与描写的比例
    4. 节奏变化 - 避免单调
    """

    def __init__(self):
        super().__init__(
            checker_name="PacingChecker",
            description="检查叙事节奏分布、时间跳跃合理性和叙事密度"
        )
        self.config = {
            "ideal_fast_ratio": 0.3,        # 理想快节奏比例
            "ideal_slow_ratio": 0.3,        # 理想慢节奏比例
            "max_time_jump_years": 10,      # 最大时间跳跃（年）
            "min_event_density": 0.3,       # 最小事件密度
        }

    def check(self, chapter_content: str, context: Dict[str, Any]) -> ReviewReport:
        """执行节奏检查"""
        chapter_id = context.get("chapter_id", "unknown")
        chapter_title = context.get("chapter_title", "")

        report = self._create_report(chapter_id, chapter_title)

        # 分析节奏分布
        pacing_segments = self._analyze_pacing(chapter_content)

        # 检查节奏平衡
        balance_score = self._check_pacing_balance(pacing_segments, chapter_content, report)

        # 检查时间跳跃
        time_jump_score = self._check_time_jumps(chapter_content, context, report)

        # 检查叙事密度
        density_score = self._check_narrative_density(chapter_content, report)

        # 检查节奏变化
        variation_score = self._check_pacing_variation(pacing_segments, report)

        # 计算维度得分
        report.dimension_scores["pacing"] = DimensionScore(
            dimension_name="节奏检查",
            score=round((balance_score + time_jump_score + density_score + variation_score) / 4, 2),
            weight=1.0,
            details={
                "balance_score": balance_score,
                "time_jump_score": time_jump_score,
                "density_score": density_score,
                "variation_score": variation_score,
                "pacing_segments": [
                    {
                        "type": seg.segment_type.value,
                        "word_count": seg.word_count,
                        "description": seg.description[:50]
                    }
                    for seg in pacing_segments
                ]
            }
        )

        report.overall_score = self._calculate_overall_score(report)
        report.suggestions = self._generate_suggestions(report)

        return report

    def _analyze_pacing(self, content: str) -> List[PacingSegment]:
        """分析章节节奏分布"""
        segments = []
        paragraphs = content.split("\n\n")

        current_pos = 0
        for para in paragraphs:
            para_len = len(para)

            # 判断段落节奏类型
            pacing_type = self._classify_pacing(para)

            segments.append(PacingSegment(
                segment_type=pacing_type,
                start_pos=current_pos,
                end_pos=current_pos + para_len,
                word_count=len(para),
                description=para[:100]
            ))

            current_pos += para_len + 2  # +2 for "\n\n"

        return segments

    def _classify_pacing(self, paragraph: str) -> PacingType:
        """分类段落节奏"""
        # 快节奏指标
        fast_indicators = [
            "突然", "立刻", "马上", "立即", "瞬间",
            "紧接着", "随后", "然后", "接着",
            "战斗", "冲突", "争执", "对抗",
            "决定", "宣布", "宣布", "发布",
        ]

        # 慢节奏指标
        slow_indicators = [
            "缓缓", "慢慢", "渐渐", "逐渐",
            "细致", "细腻", "详尽", "详细",
            "描写", "描绘", "刻画", "渲染",
            "环境", "景色", "风景", "氛围",
        ]

        # 反思型指标
        reflective_indicators = [
            "思考", "思索", "反思", "回想",
            "内心", "心中", "心底", "思绪",
            "感悟", "领悟", "体会", "感受",
            "回忆", "追忆", "怀念", "想起",
        ]

        fast_count = sum(1 for ind in fast_indicators if ind in paragraph)
        slow_count = sum(1 for ind in slow_indicators if ind in paragraph)
        reflective_count = sum(1 for ind in reflective_indicators if ind in paragraph)

        # 根据指标判断
        if fast_count > slow_count and fast_count > reflective_count:
            return PacingType.FAST
        elif slow_count > fast_count and slow_count > reflective_count:
            return PacingType.SLOW
        elif reflective_count > fast_count and reflective_count > slow_count:
            return PacingType.REFLECTIVE
        else:
            return PacingType.MODERATE

    def _check_pacing_balance(
        self,
        segments: List[PacingSegment],
        content: str,
        report: ReviewReport
    ) -> float:
        """检查节奏平衡"""
        if not segments:
            return 50

        total_words = sum(seg.word_count for seg in segments)
        if total_words == 0:
            return 50

        # 计算各类型比例
        fast_words = sum(seg.word_count for seg in segments if seg.segment_type == PacingType.FAST)
        slow_words = sum(seg.word_count for seg in segments if seg.segment_type == PacingType.SLOW)
        reflective_words = sum(seg.word_count for seg in segments if seg.segment_type == PacingType.REFLECTIVE)

        fast_ratio = fast_words / total_words
        slow_ratio = slow_words / total_words
        reflective_ratio = reflective_words / total_words

        # 检查是否过于单调
        if fast_ratio > 0.7:
            self._add_issue(report, ReviewIssue(
                issue_id="PAC001",
                dimension="pacing",
                severity=IssueSeverity.MEDIUM,
                chapter_id=report.chapter_id,
                location=None,
                description=f"节奏过快，快节奏内容占比{fast_ratio:.1%}，读者可能感到疲劳",
                suggestion="适当加入慢节奏描写，让读者有喘息空间",
                fix_priority=5
            ))
            return 60

        if slow_ratio > 0.7:
            self._add_issue(report, ReviewIssue(
                issue_id="PAC002",
                dimension="pacing",
                severity=IssueSeverity.MEDIUM,
                chapter_id=report.chapter_id,
                location=None,
                description=f"节奏过慢，慢节奏描写占比{slow_ratio:.1%}，可能影响阅读兴趣",
                suggestion="适当加快叙事节奏，增加事件推进",
                fix_priority=5
            ))
            return 60

        if reflective_ratio > 0.5:
            self._add_issue(report, ReviewIssue(
                issue_id="PAC003",
                dimension="pacing",
                severity=IssueSeverity.LOW,
                chapter_id=report.chapter_id,
                location=None,
                description=f"反思内容过多，占比{reflective_ratio:.1%}",
                suggestion="适当减少内心独白，增加行动和对话",
                fix_priority=4
            ))
            return 70

        # 理想平衡
        return 90

    def _check_time_jumps(self, content: str, context: Dict, report: ReviewReport) -> float:
        """检查时间跳跃合理性"""
        # 提取时间跳跃描述
        time_jump_patterns = [
            r'(\d+)年后',
            r'(\d+)个月后',
            r'(\d+)天后',
            r'转眼(.*?)(?:年|月|日)',
            r'时光飞逝',
            r'岁月如梭',
            r'转眼间',
            r'若干年后',
        ]

        issues_found = 0
        max_jump = 0

        for pattern in time_jump_patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                # 提取时间跨度
                try:
                    if '年' in match.group(0):
                        years = int(re.search(r'(\d+)', match.group(0)).group(1))
                        max_jump = max(max_jump, years)

                        if years > self.config["max_time_jump_years"]:
                            self._add_issue(report, ReviewIssue(
                                issue_id="PAC004",
                                dimension="pacing",
                                severity=IssueSeverity.HIGH,
                                chapter_id=report.chapter_id,
                                location=f"时间跳跃: {match.group(0)}",
                                description=f"时间跳跃过大：{years}年，可能造成叙事断裂",
                                suggestion="添加过渡段落，简要说明这段时间的重要变化",
                                fix_priority=7
                            ))
                            issues_found += 1
                except:
                    pass

        # 检查历史上下文中的连续平淡章节
        previous_chapters = context.get("previous_chapters", [])
        if len(previous_chapters) >= 3:
            # 简化检查：如果前3章都是慢节奏
            slow_count = sum(
                1 for ch in previous_chapters[-3:]
                if ch.get("pacing_type") == "slow"
            )
            if slow_count >= 3:
                self._add_issue(report, ReviewIssue(
                    issue_id="PAC005",
                    dimension="pacing",
                    severity=IssueSeverity.MEDIUM,
                    chapter_id=report.chapter_id,
                    location=None,
                    description="连续多章节奏平淡，可能造成读者流失",
                    suggestion="本章应增加事件推进或情感高潮",
                    fix_priority=6
                ))
                issues_found += 1

        return max(0, 100 - issues_found * 15)

    def _check_narrative_density(self, content: str, report: ReviewReport) -> float:
        """检查叙事密度"""
        # 统计事件相关词汇
        event_words = [
            "决定", "选择", "行动", "开始", "完成", "实现",
            "达成", "获得", "失去", "改变", "转变", "成为",
            "创建", "建立", "成立", "发起", "组织", "领导",
            "遇见", "认识", "结识", "分别", "重逢",
        ]

        # 统计描写相关词汇
        description_words = [
            "美丽", "壮观", "宁静", "热闹", "繁华",
            "高大", "宽敞", "明亮", "昏暗", "整洁",
            "穿着", "打扮", "容貌", "相貌", "身材",
        ]

        event_count = sum(content.count(word) for word in event_words)
        description_count = sum(content.count(word) for word in description_words)

        total_content_words = len(content)

        if total_content_words == 0:
            return 50

        event_density = event_count / (total_content_words / 100)  # 每百字事件词数

        if event_density < 0.5:
            self._add_issue(report, ReviewIssue(
                issue_id="PAC006",
                dimension="pacing",
                severity=IssueSeverity.MEDIUM,
                chapter_id=report.chapter_id,
                location=None,
                description=f"叙事密度偏低（每百字{event_density:.1f}个事件词），事件推进不足",
                suggestion="增加具体事件和行动描写，减少空泛叙述",
                fix_priority=6
            ))
            return 60

        return min(100, 70 + event_density * 10)

    def _check_pacing_variation(self, segments: List[PacingSegment], report: ReviewReport) -> float:
        """检查节奏变化"""
        if len(segments) < 3:
            return 80  # 段落太少，无法判断

        # 检查节奏变化频率
        changes = 0
        for i in range(1, len(segments)):
            if segments[i].segment_type != segments[i-1].segment_type:
                changes += 1

        change_ratio = changes / (len(segments) - 1)

        if change_ratio < 0.2:
            self._add_issue(report, ReviewIssue(
                issue_id="PAC007",
                dimension="pacing",
                severity=IssueSeverity.LOW,
                chapter_id=report.chapter_id,
                location=None,
                description="节奏变化过少，叙事可能显得单调",
                suggestion="适当调整节奏，在快慢之间切换",
                fix_priority=3
            ))
            return 70

        return min(100, 60 + change_ratio * 50)
