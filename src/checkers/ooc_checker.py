"""OOC检查器 (OOCChecker - Out of Character)

传记场景：
- 人物言行是否符合人设
- 语言风格是否一致
- 决策是否符合人物性格
"""
import re
from typing import List, Dict, Optional, Any, Set
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .base_checker import BaseChecker, ReviewReport, ReviewIssue, IssueSeverity, DimensionScore


class OOCLevel(Enum):
    """OOC级别"""
    NONE = "none"           # 无OOC
    MINOR = "minor"         # 轻微偏离
    MODERATE = "moderate"   # 中度失真
    SEVERE = "severe"       # 严重崩坏


@dataclass
class CharacterBehavior:
    """人物行为记录"""
    character_name: str
    behavior_type: str      # action/dialogue/emotion
    content: str
    location: str
    ooc_level: OOCLevel = OOCLevel.NONE
    deviation_reason: Optional[str] = None


class OOCChecker(BaseChecker):
    """
    OOC检查器 (Out of Character)

    检查传记中人物：
    1. 言行是否符合人设 - 行为与人设的一致性
    2. 语言风格是否一致 - 说话方式是否稳定
    3. 决策是否符合性格 - 选择是否符合人物特点
    4. 人物发展vsOOC - 区分合理成长与性格崩坏
    """

    def __init__(self):
        super().__init__(
            checker_name="OOCChecker",
            description="检查人物言行是否符合人设，区分合理成长与OOC"
        )
        self.config = {
            "strict_mode": False,           # 严格模式
            "allow_crisis_deviation": True, # 允许危机时刻的性格偏离
            "track_development": True,      # 追踪人物发展
        }

    def check(self, chapter_content: str, context: Dict[str, Any]) -> ReviewReport:
        """执行OOC检查"""
        chapter_id = context.get("chapter_id", "unknown")
        chapter_title = context.get("chapter_title", "")

        report = self._create_report(chapter_id, chapter_title)

        # 获取人物画像
        character_profiles = context.get("character_profiles", {})
        subject_profile = context.get("subject_profile", {})  # 传主画像

        # 提取人物行为
        behaviors = self._extract_behaviors(chapter_content, character_profiles)

        # 检查言行一致性
        behavior_score = self._check_behavior_consistency(
            behaviors, character_profiles, report
        )

        # 检查语言风格
        speech_score = self._check_speech_patterns(
            chapter_content, character_profiles, report
        )

        # 检查决策合理性
        decision_score = self._check_decision_consistency(
            chapter_content, character_profiles, report
        )

        # 检查人物发展
        development_score = self._check_character_development(
            chapter_content, context, report
        )

        # 计算维度得分
        report.dimension_scores["ooc"] = DimensionScore(
            dimension_name="OOC检查",
            score=round((behavior_score + speech_score + decision_score + development_score) / 4, 2),
            weight=1.1,  # OOC检查权重略高
            details={
                "behavior_score": behavior_score,
                "speech_score": speech_score,
                "decision_score": decision_score,
                "development_score": development_score,
                "behavior_samples": [
                    {
                        "character": b.character_name,
                        "type": b.behavior_type,
                        "ooc_level": b.ooc_level.value,
                        "content": b.content[:50] + "..." if len(b.content) > 50 else b.content
                    }
                    for b in behaviors[:5]  # 只显示前5个
                ]
            }
        )

        report.overall_score = self._calculate_overall_score(report)
        report.suggestions = self._generate_suggestions(report)

        return report

    def _extract_behaviors(
        self,
        content: str,
        character_profiles: Dict
    ) -> List[CharacterBehavior]:
        """提取人物行为"""
        behaviors = []

        # 提取对话
        dialogue_pattern = r'["""]([^"""]+)["""]'
        for match in re.finditer(dialogue_pattern, content):
            dialogue = match.group(1)
            # 尝试识别说话人（简化实现）
            speaker = self._identify_speaker(content, match.start())

            behaviors.append(CharacterBehavior(
                character_name=speaker,
                behavior_type="dialogue",
                content=dialogue,
                location=f"位置{match.start()}"
            ))

        # 提取动作描述
        action_patterns = [
            r'([^，。、\n]{2,8})(?:猛地|突然|缓缓|轻轻|重重)([^，。、\n]+)',
            r'([^，。、\n]{2,8})(?:站|坐|走|跑|看|说|想)([^，。、\n]+)',
        ]

        for pattern in action_patterns:
            for match in re.finditer(pattern, content):
                subject = match.group(1)
                action = match.group(2) if len(match.groups()) > 1 else ""

                behaviors.append(CharacterBehavior(
                    character_name=subject,
                    behavior_type="action",
                    content=match.group(0),
                    location=f"位置{match.start()}"
                ))

        return behaviors

    def _identify_speaker(self, content: str, position: int) -> str:
        """识别说话人（简化实现）"""
        # 向前查找可能的说话人
        before_text = content[max(0, position-50):position]

        # 常见模式：XXX说/道/问
        speaker_pattern = r'([^，。、\n"""]{2,8})(?:说|道|问|回答|喊道|轻声道)'
        match = re.search(speaker_pattern, before_text)
        if match:
            return match.group(1)

        return "未知"

    def _check_behavior_consistency(
        self,
        behaviors: List[CharacterBehavior],
        character_profiles: Dict,
        report: ReviewReport
    ) -> float:
        """检查行为一致性"""
        if not behaviors:
            return 80

        issues_found = 0

        for behavior in behaviors:
            profile = character_profiles.get(behavior.character_name, {})
            if not profile:
                continue

            # 获取人物性格特征
            personality = profile.get("personality_traits", [])
            emotional_patterns = profile.get("emotional_patterns", {})

            # 检查行为是否符合性格
            ooc_level = self._assess_ooc_level(behavior, personality, emotional_patterns)
            behavior.ooc_level = ooc_level

            if ooc_level == OOCLevel.SEVERE:
                self._add_issue(report, ReviewIssue(
                    issue_id="OOC001",
                    dimension="ooc",
                    severity=IssueSeverity.CRITICAL,
                    chapter_id=report.chapter_id,
                    location=behavior.location,
                    description=f"严重OOC：{behavior.character_name}的行为 '{behavior.content[:30]}...' 与性格 '{', '.join(personality[:2])}' 严重不符",
                    suggestion="修改行为描写，使其符合人物性格，或添加合理的触发原因",
                    evidence=behavior.content,
                    fix_priority=10
                ))
                issues_found += 2

            elif ooc_level == OOCLevel.MODERATE:
                self._add_issue(report, ReviewIssue(
                    issue_id="OOC002",
                    dimension="ooc",
                    severity=IssueSeverity.MEDIUM,
                    chapter_id=report.chapter_id,
                    location=behavior.location,
                    description=f"中度OOC：{behavior.character_name}的行为缺少充分动机",
                    suggestion="添加内心描写或外部刺激，解释行为动机",
                    fix_priority=6
                ))
                issues_found += 1

        return max(0, 100 - issues_found * 15)

    def _assess_ooc_level(
        self,
        behavior: CharacterBehavior,
        personality: List[str],
        emotional_patterns: Dict
    ) -> OOCLevel:
        """评估OOC级别"""
        # 简化实现：基于关键词匹配
        content = behavior.content

        # 性格关键词映射
        personality_keywords = {
            "冷静": ["冷静", "沉着", "镇定", "从容"],
            "冲动": ["冲动", "急躁", "鲁莽", "冒失"],
            "谨慎": ["谨慎", "小心", "慎重", "周密"],
            "果断": ["果断", "坚决", "果敢", "决断"],
            "温和": ["温和", "温柔", "和善", "亲切"],
            "严厉": ["严厉", "严肃", "苛刻", "严格"],
        }

        # 检查行为是否与性格冲突
        conflicts = 0
        for trait in personality:
            keywords = personality_keywords.get(trait, [])
            # 检查相反行为
            opposite_behavior = self._get_opposite_behavior(trait)
            if opposite_behavior and opposite_behavior in content:
                conflicts += 1

        if conflicts >= 2:
            return OOCLevel.SEVERE
        elif conflicts == 1:
            return OOCLevel.MODERATE

        return OOCLevel.NONE

    def _get_opposite_behavior(self, trait: str) -> Optional[str]:
        """获取相反行为关键词"""
        opposites = {
            "冷静": "暴怒",
            "冲动": "深思熟虑",
            "谨慎": "鲁莽",
            "果断": "犹豫不决",
            "温和": "暴躁",
            "严厉": "温柔",
        }
        return opposites.get(trait)

    def _check_speech_patterns(
        self,
        content: str,
        character_profiles: Dict,
        report: ReviewReport
    ) -> float:
        """检查语言风格一致性"""
        issues_found = 0

        for char_name, profile in character_profiles.items():
            speaking_style = profile.get("speaking_style", "")
            catchphrases = profile.get("catchphrases", [])

            if not speaking_style and not catchphrases:
                continue

            # 检查说话风格是否一致
            # 简化实现：检查是否有不符合风格的表现

            # 示例：如果人物设定为"言简意赅"，但对话过长
            if "言简意赅" in speaking_style or "简洁" in speaking_style:
                dialogues = self._extract_character_dialogues(content, char_name)
                for dialogue in dialogues:
                    if len(dialogue) > 100:  # 过长对话
                        self._add_issue(report, ReviewIssue(
                            issue_id="OOC003",
                            dimension="ooc",
                            severity=IssueSeverity.LOW,
                            chapter_id=report.chapter_id,
                            location=None,
                            description=f"{char_name}的对话过长，与'言简意赅'的设定不符",
                            suggestion="精简对话，使用更简洁的表达方式",
                            fix_priority=4
                        ))
                        issues_found += 0.5

        return max(0, 100 - issues_found * 10)

    def _extract_character_dialogues(self, content: str, char_name: str) -> List[str]:
        """提取特定人物的对话"""
        dialogues = []
        # 简化实现：使用中文引号
        pattern = f"{char_name}[^\"]*[\"]([^\"]+)[\"]"
        matches = re.finditer(pattern, content)
        for match in matches:
            dialogues.append(match.group(1))
        return dialogues

    def _check_decision_consistency(
        self,
        content: str,
        character_profiles: Dict,
        report: ReviewReport
    ) -> float:
        """检查决策一致性"""
        # 提取决策描述
        decision_patterns = [
            r'(?:决定|决心|决意|选择|抉择)([^，。、\n]+)',
            r'(?:下定决心|拿定主意|做出决定)([^，。、\n]+)',
        ]

        issues_found = 0

        for pattern in decision_patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                decision = match.group(0)

                # 检查决策是否符合人物价值观
                for char_name, profile in character_profiles.items():
                    core_values = profile.get("core_values", [])

                    # 检查决策是否与价值观冲突
                    # 简化实现
                    if "诚信" in core_values and ("欺骗" in decision or "隐瞒" in decision):
                        self._add_issue(report, ReviewIssue(
                            issue_id="OOC004",
                            dimension="ooc",
                            severity=IssueSeverity.HIGH,
                            chapter_id=report.chapter_id,
                            location=f"决策: {decision[:30]}",
                            description=f"{char_name}的决策 '{decision[:30]}...' 与核心价值观 '{', '.join(core_values[:2])}' 冲突",
                            suggestion="修改决策，或添加充分的内心挣扎和理由",
                            fix_priority=8
                        ))
                        issues_found += 1

        return max(0, 100 - issues_found * 15)

    def _check_character_development(
        self,
        content: str,
        context: Dict,
        report: ReviewReport
    ) -> float:
        """检查人物发展合理性"""
        # 获取历史性格记录
        previous_chapters = context.get("previous_chapters", [])

        if len(previous_chapters) < 5:
            # 章节太少，无法判断发展
            return 85

        # 检查性格转变是否有铺垫
        # 简化实现

        issues_found = 0

        # 检查是否有突然的性格转变
        sudden_change_patterns = [
            r'(?:突然|忽然|一下子|瞬间)([^，。、\n]{0,10})(?:变得|变了|改变|转变)',
            r'(?:像变了个人|判若两人|截然不同)',
        ]

        for pattern in sudden_change_patterns:
            if re.search(pattern, content):
                # 检查前文是否有铺垫
                has_setup = self._check_development_setup(previous_chapters)

                if not has_setup:
                    self._add_issue(report, ReviewIssue(
                        issue_id="OOC005",
                        dimension="ooc",
                        severity=IssueSeverity.MEDIUM,
                        chapter_id=report.chapter_id,
                        location=None,
                        description="人物性格转变过于突然，缺少渐进式铺垫",
                        suggestion="在前几章添加性格变化的伏笔和铺垫",
                        fix_priority=6
                    ))
                    issues_found += 1

        return max(0, 100 - issues_found * 15)

    def _check_development_setup(self, previous_chapters: List[Dict]) -> bool:
        """检查人物发展是否有铺垫"""
        # 简化实现：检查前3章是否有相关描述
        for ch in previous_chapters[-3:]:
            content = ch.get("content", "")
            setup_signals = ["开始", "逐渐", "慢慢", "越来越", "有所改变"]
            if any(signal in content for signal in setup_signals):
                return True
        return False
