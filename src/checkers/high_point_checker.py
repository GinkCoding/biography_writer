"""高潮检查器 (HighPointChecker)

传记场景：情感高潮、人生转折点、关键决策时刻
检查：高潮密度（每章至少1个）、高潮质量（是否有铺垫和释放）
"""
import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime

from .base_checker import BaseChecker, ReviewReport, ReviewIssue, IssueSeverity, DimensionScore


@dataclass
class HighPoint:
    """高潮点"""
    point_type: str                         # 高潮类型
    description: str                        # 描述
    location: str                           # 位置
    has_setup: bool = False                 # 是否有铺垫
    has_release: bool = False               # 是否有释放
    emotional_intensity: int = 5            # 情感强度 1-10
    quality_grade: str = "C"                # 质量等级 A/B/C/F


class HighPointChecker(BaseChecker):
    """
    高潮检查器

    针对传记文学的特点，检查：
    1. 情感高潮 - 情感爆发、内心转变
    2. 人生转折点 - 命运改变的关键时刻
    3. 关键决策时刻 - 重大选择的瞬间
    4. 冲突高潮 - 矛盾激化的顶点
    """

    # 高潮类型定义
    HIGH_POINT_TYPES = {
        "emotional": "情感高潮",           # 情感爆发、内心转变
        "turning_point": "人生转折",       # 命运改变的关键时刻
        "decision": "关键决策",            # 重大选择的瞬间
        "conflict": "冲突高潮",            # 矛盾激化的顶点
        "achievement": "成就高光",         # 重要成就/胜利时刻
        "revelation": "真相揭示",          # 重要真相的揭露
        "reunion": "重逢时刻",             # 重要人物重逢
        "farewell": "离别时刻",            # 重要离别场景
    }

    # 情感高潮信号词
    EMOTIONAL_SIGNALS = [
        "泪水", "眼泪", "哭泣", "哽咽", "泪如雨下",
        "激动", "激动不已", "心潮澎湃", "百感交集",
        "震撼", "震惊", "呆立当场", "无法相信",
        "终于", "恍然大悟", "豁然开朗", "如梦初醒",
        "内心", "心底", "内心深处", "心中",
    ]

    # 转折点信号词
    TURNING_SIGNALS = [
        "转折点", "命运的转折", "人生转折", "从此",
        "那一刻", "那一瞬间", "从那天起", "从那以后",
        "改变了一生", "改变了命运", "人生轨迹",
        "分水岭", "里程碑", "新的篇章", "新的起点",
    ]

    # 决策信号词
    DECISION_SIGNALS = [
        "决定", "下定决心", "毅然", "毅然决然",
        "选择", "抉择", "权衡", "深思熟虑",
        "咬紧牙关", "豁出去", "孤注一掷",
        "无论如何", "不管怎样", "哪怕是",
    ]

    # 冲突信号词
    CONFLICT_SIGNALS = [
        "冲突", "矛盾", "对立", "争执", "争吵",
        "对抗", "较量", "针锋相对", "剑拔弩张",
        "危机", "危急", "千钧一发", "生死攸关",
        "爆发", "激化", "升级", "白热化",
    ]

    def __init__(self):
        super().__init__(
            checker_name="HighPointChecker",
            description="检查传记场景中的情感高潮、人生转折点和关键决策时刻"
        )
        self.config = {
            "min_highpoints_per_chapter": 1,    # 每章最少高潮数
            "max_highpoints_per_chapter": 5,    # 每章最多高潮数（避免过度堆砌）
            "min_emotional_intensity": 5,       # 最小情感强度
            "setup_required": True,             # 是否需要铺垫
        }

    def check(self, chapter_content: str, context: Dict[str, Any]) -> ReviewReport:
        """执行高潮检查"""
        chapter_id = context.get("chapter_id", "unknown")
        chapter_title = context.get("chapter_title", "")

        report = self._create_report(chapter_id, chapter_title)

        # 识别高潮点
        high_points = self._identify_high_points(chapter_content)

        # 检查高潮密度
        density_score = self._check_density(high_points, report)

        # 检查高潮质量
        quality_score = self._check_quality(high_points, chapter_content, report)

        # 检查高潮多样性
        diversity_score = self._check_diversity(high_points, report)

        # 计算维度得分
        report.dimension_scores["highpoint"] = DimensionScore(
            dimension_name="高潮检查",
            score=round((density_score + quality_score + diversity_score) / 3, 2),
            weight=1.2,  # 高潮检查权重较高
            details={
                "density_score": density_score,
                "quality_score": quality_score,
                "diversity_score": diversity_score,
                "high_point_count": len(high_points),
                "high_points": [
                    {
                        "type": hp.point_type,
                        "description": hp.description[:50] + "..." if len(hp.description) > 50 else hp.description,
                        "quality_grade": hp.quality_grade,
                        "emotional_intensity": hp.emotional_intensity
                    }
                    for hp in high_points
                ]
            }
        )

        # 计算综合得分
        report.overall_score = self._calculate_overall_score(report)
        report.suggestions = self._generate_suggestions(report)

        return report

    def _identify_high_points(self, content: str) -> List[HighPoint]:
        """识别章节中的高潮点"""
        high_points = []

        # 按段落分析
        paragraphs = content.split("\n\n")

        for i, para in enumerate(paragraphs):
            location = f"第{i+1}段"

            # 检查情感高潮
            emotional_score = self._count_signals(para, self.EMOTIONAL_SIGNALS)
            if emotional_score >= 2:
                hp = HighPoint(
                    point_type="emotional",
                    description=para[:100],
                    location=location,
                    emotional_intensity=min(10, emotional_score * 2)
                )
                high_points.append(hp)

            # 检查人生转折
            turning_score = self._count_signals(para, self.TURNING_SIGNALS)
            if turning_score >= 1:
                hp = HighPoint(
                    point_type="turning_point",
                    description=para[:100],
                    location=location,
                    emotional_intensity=min(10, 5 + turning_score * 2)
                )
                high_points.append(hp)

            # 检查关键决策
            decision_score = self._count_signals(para, self.DECISION_SIGNALS)
            if decision_score >= 2:
                hp = HighPoint(
                    point_type="decision",
                    description=para[:100],
                    location=location,
                    emotional_intensity=min(10, 4 + decision_score)
                )
                high_points.append(hp)

            # 检查冲突高潮
            conflict_score = self._count_signals(para, self.CONFLICT_SIGNALS)
            if conflict_score >= 2:
                hp = HighPoint(
                    point_type="conflict",
                    description=para[:100],
                    location=location,
                    emotional_intensity=min(10, 5 + conflict_score)
                )
                high_points.append(hp)

        # 评估每个高潮点的质量
        for hp in high_points:
            hp.quality_grade = self._assess_quality(hp, content)
            hp.has_setup = self._check_setup(hp, content)
            hp.has_release = self._check_release(hp, content)

        return high_points

    def _count_signals(self, text: str, signals: List[str]) -> int:
        """计数信号词出现次数"""
        count = 0
        for signal in signals:
            count += len(re.findall(signal, text))
        return count

    def _assess_quality(self, high_point: HighPoint, content: str) -> str:
        """评估高潮点质量"""
        score = 0

        # 情感强度评分
        if high_point.emotional_intensity >= 7:
            score += 3
        elif high_point.emotional_intensity >= 5:
            score += 2
        else:
            score += 1

        # 铺垫检查
        if high_point.has_setup:
            score += 3

        # 释放检查
        if high_point.has_release:
            score += 2

        # 转换为等级
        if score >= 6:
            return "A"
        elif score >= 4:
            return "B"
        elif score >= 2:
            return "C"
        else:
            return "F"

    def _check_setup(self, high_point: HighPoint, content: str) -> bool:
        """检查是否有铺垫"""
        # 简化实现：检查前文是否有相关描述
        # 实际实现可以更复杂，检查前文的情绪积累、伏笔等
        paragraphs = content.split("\n\n")
        hp_para = high_point.location.replace("第", "").replace("段", "")
        try:
            hp_index = int(hp_para) - 1
        except:
            return False

        # 检查前2段是否有铺垫
        if hp_index > 0:
            prev_content = " ".join(paragraphs[max(0, hp_index-2):hp_index])
            # 如果有情感铺垫或背景描述，认为有铺垫
            setup_signals = ["一直", "始终", "多年来", "从小", "曾经", "过去"]
            return any(signal in prev_content for signal in setup_signals)

        return False

    def _check_release(self, high_point: HighPoint, content: str) -> bool:
        """检查是否有情感释放"""
        paragraphs = content.split("\n\n")
        hp_para = high_point.location.replace("第", "").replace("段", "")
        try:
            hp_index = int(hp_para) - 1
        except:
            return False

        # 检查后1段是否有释放
        if hp_index < len(paragraphs) - 1:
            next_content = paragraphs[hp_index + 1]
            release_signals = ["终于", "从此", "之后", "后来", "结果"]
            return any(signal in next_content for signal in release_signals)

        return False

    def _check_density(self, high_points: List[HighPoint], report: ReviewReport) -> float:
        """检查高潮密度"""
        count = len(high_points)
        min_required = self.config["min_highpoints_per_chapter"]
        max_allowed = self.config["max_highpoints_per_chapter"]

        if count < min_required:
            self._add_issue(report, ReviewIssue(
                issue_id="HP001",
                dimension="highpoint",
                severity=IssueSeverity.HIGH,
                chapter_id=report.chapter_id,
                location=None,
                description=f"高潮点密度不足，本章仅有{count}个高潮点，建议至少{min_required}个",
                suggestion="添加情感高潮、人生转折点或关键决策场景的描写",
                fix_priority=8
            ))
            return max(0, count * 30)

        if count > max_allowed:
            self._add_issue(report, ReviewIssue(
                issue_id="HP002",
                dimension="highpoint",
                severity=IssueSeverity.MEDIUM,
                chapter_id=report.chapter_id,
                location=None,
                description=f"高潮点过于密集，本章有{count}个高潮点，可能造成情感疲劳",
                suggestion="适当分散高潮点，给读者情感缓冲的空间",
                fix_priority=5
            ))
            return 70

        # 理想密度得分
        return min(100, 60 + count * 10)

    def _check_quality(self, high_points: List[HighPoint], content: str, report: ReviewReport) -> float:
        """检查高潮质量"""
        if not high_points:
            return 0

        grade_scores = {"A": 100, "B": 80, "C": 60, "F": 40}
        total_score = sum(grade_scores.get(hp.quality_grade, 50) for hp in high_points)
        avg_score = total_score / len(high_points)

        # 检查质量问题
        low_quality_count = sum(1 for hp in high_points if hp.quality_grade in ["C", "F"])
        if low_quality_count > 0:
            self._add_issue(report, ReviewIssue(
                issue_id="HP003",
                dimension="highpoint",
                severity=IssueSeverity.MEDIUM,
                chapter_id=report.chapter_id,
                location=None,
                description=f"存在{low_quality_count}个低质量高潮点，缺少铺垫或情感释放",
                suggestion="为高潮场景添加充分的铺垫铺垫和后续的情感释放描写",
                fix_priority=6
            ))

        # 检查缺少铺垫的高潮
        no_setup_count = sum(1 for hp in high_points if not hp.has_setup)
        if no_setup_count > 0:
            self._add_issue(report, ReviewIssue(
                issue_id="HP004",
                dimension="highpoint",
                severity=IssueSeverity.MEDIUM,
                chapter_id=report.chapter_id,
                location=None,
                description=f"有{no_setup_count}个高潮点缺少铺垫，显得突兀",
                suggestion="在高潮前添加情绪积累、背景交代或伏笔铺垫",
                fix_priority=6
            ))

        return avg_score

    def _check_diversity(self, high_points: List[HighPoint], report: ReviewReport) -> float:
        """检查高潮类型多样性"""
        if not high_points:
            return 0

        type_counts = {}
        for hp in high_points:
            type_counts[hp.point_type] = type_counts.get(hp.point_type, 0) + 1

        # 计算多样性得分
        total = len(high_points)
        if total == 1:
            return 80  # 单高潮默认良好

        # 如果所有高潮都是同一类型，多样性差
        max_count = max(type_counts.values())
        if max_count == total:
            self._add_issue(report, ReviewIssue(
                issue_id="HP005",
                dimension="highpoint",
                severity=IssueSeverity.LOW,
                chapter_id=report.chapter_id,
                location=None,
                description=f"高潮类型单一，全部为{self.HIGH_POINT_TYPES.get(list(type_counts.keys())[0])}",
                suggestion="尝试加入不同类型的高潮，如情感高潮、决策时刻、转折点等",
                fix_priority=4
            ))
            return 60

        # 多样性良好
        unique_types = len(type_counts)
        return min(100, 70 + unique_types * 10)
