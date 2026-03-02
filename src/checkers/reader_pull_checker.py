"""阅读吸引力检查器 (ReaderPullChecker)

传记场景：
- 开头钩子强度
- 悬念设置
- 章节结尾吸引力
"""
import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .base_checker import BaseChecker, ReviewReport, ReviewIssue, IssueSeverity, DimensionScore


class HookType(Enum):
    """钩子类型"""
    CRISIS = "crisis"           # 危机钩 - 危险逼近
    MYSTERY = "mystery"         # 悬念钩 - 信息缺口
    EMOTION = "emotion"         # 情绪钩 - 强情绪触发
    CHOICE = "choice"           # 选择钩 - 两难抉择
    DESIRE = "desire"           # 渴望钩 - 好事将至


class HookStrength(Enum):
    """钩子强度"""
    STRONG = "strong"           # 强钩子
    MEDIUM = "medium"           # 中等
    WEAK = "weak"               # 弱钩子
    NONE = "none"               # 无钩子


@dataclass
class Hook:
    """钩子"""
    hook_type: HookType
    strength: HookStrength
    content: str
    location: str


@dataclass
class MicroPayoff:
    """微兑现"""
    payoff_type: str            # 兑现类型
    content: str
    location: str


class ReaderPullChecker(BaseChecker):
    """
    阅读吸引力检查器

    检查传记的：
    1. 开头钩子强度 - 能否吸引读者继续阅读
    2. 悬念设置 - 信息缺口的设置
    3. 章节结尾吸引力 - 章末是否有吸引力
    4. 微兑现 - 承诺的兑现情况
    """

    # 钩子类型识别词
    HOOK_PATTERNS = {
        HookType.CRISIS: ["危险", "危机", "威胁", "逼近", "即将", "千钧一发", "生死攸关"],
        HookType.MYSTERY: ["秘密", "真相", "谜团", "疑问", "为什么", "怎么回事", "究竟"],
        HookType.EMOTION: ["愤怒", "震惊", "心痛", "激动", "难以置信", "无法接受"],
        HookType.CHOICE: ["抉择", "选择", "两难", "纠结", "权衡", "取舍"],
        HookType.DESIRE: ["期待", "希望", "即将实现", "梦寐以求", "等待已久"],
    }

    def __init__(self):
        super().__init__(
            checker_name="ReaderPullChecker",
            description="检查开头钩子、悬念设置和章节结尾吸引力"
        )
        self.config = {
            "require_opening_hook": True,   # 要求开头钩子
            "require_ending_hook": True,    # 要求结尾钩子
            "min_micropayoffs": 1,          # 最少微兑现数
            "min_hook_strength": "medium",  # 最小钩子强度
        }

    def check(self, chapter_content: str, context: Dict[str, Any]) -> ReviewReport:
        """执行阅读吸引力检查"""
        chapter_id = context.get("chapter_id", "unknown")
        chapter_title = context.get("chapter_title", "")

        report = self._create_report(chapter_id, chapter_title)

        # 检查开头钩子
        opening_score = self._check_opening_hook(chapter_content, report)

        # 检查悬念设置
        suspense_score = self._check_suspense_setup(chapter_content, report)

        # 检查章节结尾
        ending_score = self._check_ending_hook(chapter_content, report)

        # 检查微兑现
        payoff_score = self._check_micropayoffs(chapter_content, context, report)

        # 计算维度得分
        report.dimension_scores["reader_pull"] = DimensionScore(
            dimension_name="阅读吸引力检查",
            score=round((opening_score + suspense_score + ending_score + payoff_score) / 4, 2),
            weight=1.2,  # 阅读吸引力权重较高
            details={
                "opening_score": opening_score,
                "suspense_score": suspense_score,
                "ending_score": ending_score,
                "payoff_score": payoff_score,
                "hooks_found": self._extract_hooks(chapter_content),
                "micropayoffs_found": self._extract_micropayoffs(chapter_content)
            }
        )

        report.overall_score = self._calculate_overall_score(report)
        report.suggestions = self._generate_suggestions(report)

        return report

    def _check_opening_hook(self, content: str, report: ReviewReport) -> float:
        """检查开头钩子"""
        # 提取开头段落（前300字）
        opening = content[:300]

        # 识别钩子
        hooks = self._identify_hooks_in_text(opening)

        if not hooks:
            self._add_issue(report, ReviewIssue(
                issue_id="RP001",
                dimension="reader_pull",
                severity=IssueSeverity.HIGH,
                chapter_id=report.chapter_id,
                location="章节开头",
                description="章节开头缺少钩子，可能无法吸引读者",
                suggestion="在开头添加悬念、冲突或引人注目的场景",
                fix_priority=9
            ))
            return 40

        # 评估最强钩子
        strongest_hook = max(hooks, key=lambda h: self._hook_strength_score(h.strength))

        if strongest_hook.strength == HookStrength.WEAK:
            self._add_issue(report, ReviewIssue(
                issue_id="RP002",
                dimension="reader_pull",
                severity=IssueSeverity.MEDIUM,
                chapter_id=report.chapter_id,
                location="章节开头",
                description="开头钩子强度较弱，吸引力不足",
                suggestion="强化开头钩子，增加危机感、悬念或情绪冲击",
                fix_priority=6
            ))
            return 60

        if strongest_hook.strength == HookStrength.STRONG:
            return 95

        return 80

    def _check_suspense_setup(self, content: str, report: ReviewReport) -> float:
        """检查悬念设置"""
        # 识别悬念设置
        suspense_signals = [
            r'(?:不知道|不清楚|不明白|疑问|疑惑)([^，。、\n]+)',
            r'(?:秘密|真相|谜团|答案)([^，。、\n]+)',
            r'(?:究竟|到底|为何|为什么)([^，。、\n]+)',
        ]

        suspense_count = 0
        for pattern in suspense_signals:
            matches = re.finditer(pattern, content)
            suspense_count += len(list(matches))

        # 评估悬念密度
        content_length = len(content)
        suspense_density = suspense_count / (content_length / 1000)  # 每千字悬念数

        if suspense_count == 0:
            self._add_issue(report, ReviewIssue(
                issue_id="RP003",
                dimension="reader_pull",
                severity=IssueSeverity.MEDIUM,
                chapter_id=report.chapter_id,
                location=None,
                description="本章缺少悬念设置，叙事可能过于平铺直叙",
                suggestion="添加信息缺口，设置悬念吸引读者",
                fix_priority=5
            ))
            return 50

        if suspense_density < 1:
            self._add_issue(report, ReviewIssue(
                issue_id="RP004",
                dimension="reader_pull",
                severity=IssueSeverity.LOW,
                chapter_id=report.chapter_id,
                location=None,
                description="悬念设置较少，建议增加",
                suggestion="适当增加悬念点，保持读者好奇心",
                fix_priority=4
            ))
            return 70

        return min(100, 70 + suspense_density * 10)

    def _check_ending_hook(self, content: str, report: ReviewReport) -> float:
        """检查章节结尾吸引力"""
        # 提取结尾段落（后300字）
        ending = content[-300:] if len(content) >= 300 else content

        # 识别结尾钩子
        hooks = self._identify_hooks_in_text(ending)

        # 检查结尾类型
        ending_patterns = {
            "cliffhanger": ["未完待续", "接下来", "下一章", "等待", "即将"],
            "resolution": ["终于", "结果", "最终", "结束", "完成"],
            "reflection": ["思考", "感悟", "明白", "领悟"],
            "transition": ["第二天", "次日", "很快", "不久后"],
        }

        ending_type = None
        for etype, patterns in ending_patterns.items():
            if any(p in ending for p in patterns):
                ending_type = etype
                break

        if not hooks and ending_type != "resolution":
            self._add_issue(report, ReviewIssue(
                issue_id="RP005",
                dimension="reader_pull",
                severity=IssueSeverity.HIGH,
                chapter_id=report.chapter_id,
                location="章节结尾",
                description="章节结尾缺少钩子，读者缺乏阅读下一章的动力",
                suggestion="在结尾设置悬念、预告或情绪钩子",
                fix_priority=8
            ))
            return 45

        # 评估结尾强度
        if ending_type == "cliffhanger":
            return 95
        elif hooks and max(hooks, key=lambda h: self._hook_strength_score(h.strength)).strength == HookStrength.STRONG:
            return 90
        elif ending_type == "resolution":
            # 解决型结尾需要更强的钩子补偿
            if hooks:
                return 75
            else:
                self._add_issue(report, ReviewIssue(
                    issue_id="RP006",
                    dimension="reader_pull",
                    severity=IssueSeverity.MEDIUM,
                    chapter_id=report.chapter_id,
                    location="章节结尾",
                    description="本章以解决收尾，但缺少新的悬念引导",
                    suggestion="在解决问题的同时，设置新的期待或挑战",
                    fix_priority=6
                ))
                return 60

        return 80

    def _check_micropayoffs(self, content: str, context: Dict, report: ReviewReport) -> float:
        """检查微兑现"""
        # 提取微兑现
        micropayoffs = self._extract_micropayoffs(content)

        # 检查前章承诺
        previous_chapters = context.get("previous_chapters", [])
        prev_hooks = []
        if previous_chapters:
            last_chapter = previous_chapters[-1]
            prev_content = last_chapter.get("content", "")
            prev_hooks = self._identify_hooks_in_text(prev_content[-200:])  # 上章结尾钩子

        # 检查承诺兑现
        fulfilled_count = 0
        for hook in prev_hooks:
            if self._is_hook_fulfilled(hook, content):
                fulfilled_count += 1

        # 计算兑现率
        if prev_hooks:
            fulfillment_rate = fulfilled_count / len(prev_hooks)
        else:
            fulfillment_rate = 1.0

        # 评估微兑现数量
        min_required = self.config["min_micropayoffs"]
        if len(micropayoffs) < min_required:
            self._add_issue(report, ReviewIssue(
                issue_id="RP007",
                dimension="reader_pull",
                severity=IssueSeverity.MEDIUM,
                chapter_id=report.chapter_id,
                location=None,
                description=f"微兑现不足，本章仅有{len(micropayoffs)}个，建议至少{min_required}个",
                suggestion="添加信息揭示、能力提升或认可获得等微兑现",
                fix_priority=5
            ))
            return max(0, 50 + fulfillment_rate * 30)

        return min(100, 60 + fulfillment_rate * 30 + len(micropayoffs) * 5)

    def _identify_hooks_in_text(self, text: str) -> List[Hook]:
        """在文本中识别钩子"""
        hooks = []

        for hook_type, patterns in self.HOOK_PATTERNS.items():
            for pattern in patterns:
                if pattern in text:
                    # 计算强度
                    strength = self._calculate_hook_strength(text, pattern)

                    # 找到具体位置
                    idx = text.find(pattern)
                    context_start = max(0, idx - 20)
                    context_end = min(len(text), idx + 50)
                    content = text[context_start:context_end]

                    hooks.append(Hook(
                        hook_type=hook_type,
                        strength=strength,
                        content=content,
                        location=f"位置{idx}"
                    ))

        return hooks

    def _calculate_hook_strength(self, text: str, pattern: str) -> HookStrength:
        """计算钩子强度"""
        # 强度指标
        strong_indicators = ["必须", "一定", "即将", "马上", "立刻", "危险", "生死"]
        weak_indicators = ["也许", "可能", "或许", "将来", "以后"]

        # 找到pattern附近的文本
        idx = text.find(pattern)
        surrounding = text[max(0, idx-30):min(len(text), idx+30)]

        strong_count = sum(1 for ind in strong_indicators if ind in surrounding)
        weak_count = sum(1 for ind in weak_indicators if ind in surrounding)

        if strong_count > 0:
            return HookStrength.STRONG
        elif weak_count > 0:
            return HookStrength.WEAK
        else:
            return HookStrength.MEDIUM

    def _hook_strength_score(self, strength: HookStrength) -> int:
        """钩子强度分数"""
        scores = {
            HookStrength.STRONG: 3,
            HookStrength.MEDIUM: 2,
            HookStrength.WEAK: 1,
            HookStrength.NONE: 0
        }
        return scores.get(strength, 0)

    def _extract_micropayoffs(self, content: str) -> List[MicroPayoff]:
        """提取微兑现"""
        micropayoffs = []

        # 微兑现类型识别
        payoff_patterns = {
            "信息兑现": ["原来", "终于明白", "恍然大悟", "真相是", "得知"],
            "关系兑现": ["认可", "接受", "信任", "友谊", "感情"],
            "能力兑现": ["突破", "提升", "掌握", "成功", "完成"],
            "资源兑现": ["获得", "得到", "拥有", "收获"],
            "认可兑现": ["赞赏", "表扬", "肯定", "认同", "尊重"],
            "情绪兑现": ["释怀", "欣慰", "满足", "喜悦", "感动"],
        }

        for payoff_type, patterns in payoff_patterns.items():
            for pattern in patterns:
                if pattern in content:
                    idx = content.find(pattern)
                    micropayoffs.append(MicroPayoff(
                        payoff_type=payoff_type,
                        content=content[max(0, idx-20):min(len(content), idx+30)],
                        location=f"位置{idx}"
                    ))

        return micropayoffs

    def _is_hook_fulfilled(self, hook: Hook, content: str) -> bool:
        """检查钩子是否兑现"""
        # 简化实现：检查钩子关键词是否在内容中
        hook_keywords = hook.content[:10]

        fulfillment_signals = ["果然", "正如", "终于", "结果", "最终", "完成"]

        return hook_keywords in content and any(signal in content for signal in fulfillment_signals)

    def _extract_hooks(self, content: str) -> List[Dict]:
        """提取所有钩子信息（用于报告）"""
        hooks = self._identify_hooks_in_text(content)
        return [
            {
                "type": h.hook_type.value,
                "strength": h.strength.value,
                "content": h.content[:50] + "..." if len(h.content) > 50 else h.content
            }
            for h in hooks[:5]  # 只返回前5个
        ]
