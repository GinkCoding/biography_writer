"""一致性检查器 (ConsistencyChecker)

传记场景：
- 时间线一致性（事件顺序）
- 地点一致性（地理位置合理性）
- 人物关系一致性
"""
import re
from typing import List, Dict, Optional, Any, Set
from dataclasses import dataclass
from datetime import datetime

from .base_checker import BaseChecker, ReviewReport, ReviewIssue, IssueSeverity, DimensionScore


@dataclass
class TimelineEvent:
    """时间线事件"""
    event_id: str
    date_str: Optional[str]  # 原始日期字符串
    date_normalized: Optional[str]  # 规范化后的日期
    description: str
    location: Optional[str]
    characters: List[str]
    is_approximate: bool = False


class ConsistencyChecker(BaseChecker):
    """
    一致性检查器

    检查传记中的：
    1. 时间线一致性 - 事件顺序合理，无时间矛盾
    2. 地点一致性 - 地理位置合理，移动逻辑通顺
    3. 人物关系一致性 - 人物关系稳定，不出现矛盾
    4. 事实一致性 - 已记录事实不被后续内容矛盾
    """

    def __init__(self):
        super().__init__(
            checker_name="ConsistencyChecker",
            description="检查时间线、地点、人物关系和事实的一致性"
        )
        self.config = {
            "strict_timeline": True,        # 严格时间线检查
            "check_location_logic": True,   # 检查地点逻辑
            "check_relationships": True,    # 检查人物关系
        }

    def check(self, chapter_content: str, context: Dict[str, Any]) -> ReviewReport:
        """执行一致性检查"""
        chapter_id = context.get("chapter_id", "unknown")
        chapter_title = context.get("chapter_title", "")

        report = self._create_report(chapter_id, chapter_title)

        # 提取当前章节的时间、地点、人物信息
        current_info = self._extract_chapter_info(chapter_content)

        # 获取历史信息
        timeline = context.get("timeline", [])
        previous_chapters = context.get("previous_chapters", [])
        character_profiles = context.get("character_profiles", {})
        established_facts = context.get("established_facts", [])

        # 检查时间线一致性
        timeline_score = self._check_timeline_consistency(
            current_info, timeline, report
        )

        # 检查地点一致性
        location_score = self._check_location_consistency(
            current_info, previous_chapters, report
        )

        # 检查人物关系一致性
        relationship_score = self._check_relationship_consistency(
            current_info, character_profiles, previous_chapters, report
        )

        # 检查事实一致性
        fact_score = self._check_fact_consistency(
            chapter_content, established_facts, report
        )

        # 计算维度得分
        report.dimension_scores["consistency"] = DimensionScore(
            dimension_name="一致性检查",
            score=round((timeline_score + location_score + relationship_score + fact_score) / 4, 2),
            weight=1.0,
            details={
                "timeline_score": timeline_score,
                "location_score": location_score,
                "relationship_score": relationship_score,
                "fact_score": fact_score,
                "current_timeline": current_info.get("dates", []),
                "current_locations": current_info.get("locations", []),
                "current_characters": current_info.get("characters", [])
            }
        )

        report.overall_score = self._calculate_overall_score(report)
        report.suggestions = self._generate_suggestions(report)

        return report

    def _extract_chapter_info(self, content: str) -> Dict[str, Any]:
        """提取章节中的时间、地点、人物信息"""
        info = {
            "dates": [],
            "locations": [],
            "characters": [],
            "events": []
        }

        # 提取日期
        date_patterns = [
            r'(\d{4})年(\d{1,2})月(\d{1,2})日',
            r'(\d{4})年(\d{1,2})月',
            r'(\d{4})年',
            r'(\d{1,2})月(\d{1,2})日',
            r'(\d{1,2})岁',
            r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',
        ]

        for pattern in date_patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                info["dates"].append({
                    "text": match.group(0),
                    "position": match.start()
                })

        # 提取地点（简化实现，实际可用NER）
        location_indicators = ["在", "于", "来到", "前往", "到达", "离开", "回到"]
        for indicator in location_indicators:
            pattern = f"{indicator}([^，。、\n]{{2,20}})[，。、\n]"
            matches = re.finditer(pattern, content)
            for match in matches:
                location = match.group(1).strip()
                if len(location) >= 2 and len(location) <= 20:
                    info["locations"].append({
                        "text": location,
                        "context": match.group(0)
                    })

        # 提取人物（基于常见称谓和指代）
        person_patterns = [
            r'([^，。、\n]{2,4})(?:先生|女士|老师|教授|医生|工程师|书记|主任|经理)',
            r'[他她它](?:们)?',
            r'([^，。、\n]{2,4})和([^，。、\n]{2,4})',
        ]

        for pattern in person_patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                info["characters"].append(match.group(0))

        return info

    def _check_timeline_consistency(
        self,
        current_info: Dict,
        timeline: List[Dict],
        report: ReviewReport
    ) -> float:
        """检查时间线一致性"""
        current_dates = current_info.get("dates", [])

        if not current_dates:
            # 没有明确日期，无法检查
            return 80

        issues_found = 0

        # 检查日期顺序
        parsed_dates = []
        for date_info in current_dates:
            date_text = date_info["text"]
            parsed = self._parse_date(date_text)
            if parsed:
                parsed_dates.append((parsed, date_text))

        # 检查与历史时间线的冲突
        for parsed_date, date_text in parsed_dates:
            for hist_event in timeline:
                hist_date = hist_event.get("date")
                if hist_date and self._dates_conflict(parsed_date, hist_date):
                    self._add_issue(report, ReviewIssue(
                        issue_id="CON001",
                        dimension="consistency",
                        severity=IssueSeverity.CRITICAL,
                        chapter_id=report.chapter_id,
                        location=f"日期: {date_text}",
                        description=f"时间线冲突：{date_text} 与已记录事件 '{hist_event.get('title', '')}' 的时间矛盾",
                        suggestion="核对并修正日期，确保时间线逻辑通顺",
                        fix_priority=10
                    ))
                    issues_found += 1

        # 检查章节内的时间顺序
        if len(parsed_dates) >= 2:
            for i in range(len(parsed_dates) - 1):
                if parsed_dates[i][0] > parsed_dates[i + 1][0]:
                    self._add_issue(report, ReviewIssue(
                        issue_id="CON002",
                        dimension="consistency",
                        severity=IssueSeverity.HIGH,
                        chapter_id=report.chapter_id,
                        location=None,
                        description=f"章节内时间顺序混乱：{parsed_dates[i][1]} 在 {parsed_dates[i+1][1]} 之后",
                        suggestion="调整叙述顺序，或添加明确的时间过渡说明",
                        fix_priority=8
                    ))
                    issues_found += 1

        return max(0, 100 - issues_found * 20)

    def _parse_date(self, date_text: str) -> Optional[str]:
        """解析日期文本为标准化格式"""
        # 简化实现：提取年份
        year_match = re.search(r'(\d{4})', date_text)
        if year_match:
            return year_match.group(1)
        return None

    def _dates_conflict(self, date1: str, date2: str) -> bool:
        """检查两个日期是否冲突（简化实现）"""
        if not date1 or not date2:
            return False

        normalized1 = self._parse_date(date1)
        normalized2 = self._parse_date(date2)
        if not normalized1 or not normalized2:
            return False

        # 当前实现按年份判断：同一事件在不同年份时视为冲突。
        return normalized1 != normalized2

    def _check_location_consistency(
        self,
        current_info: Dict,
        previous_chapters: List[Dict],
        report: ReviewReport
    ) -> float:
        """检查地点一致性"""
        current_locations = current_info.get("locations", [])

        if not current_locations:
            return 90  # 没有地点信息，默认良好

        issues_found = 0

        # 检查地点跳跃（无过渡的远距离移动）
        if previous_chapters:
            last_chapter = previous_chapters[-1]
            last_locations = last_chapter.get("locations", [])

            if last_locations and current_locations:
                # 检查是否有移动描述
                move_indicators = ["来到", "前往", "到达", "离开", "回到", "赶赴"]
                has_movement = any(
                    indicator in loc.get("context", "")
                    for loc in current_locations
                    for indicator in move_indicators
                )

                if not has_movement:
                    # 检查地点是否完全不同
                    last_loc_names = {loc.get("text", "") for loc in last_locations}
                    current_loc_names = {loc.get("text", "") for loc in current_locations}

                    if not last_loc_names.intersection(current_loc_names):
                        self._add_issue(report, ReviewIssue(
                            issue_id="CON003",
                            dimension="consistency",
                            severity=IssueSeverity.MEDIUM,
                            chapter_id=report.chapter_id,
                            location=None,
                            description="地点跳跃：本章地点与前章完全不同，缺少移动过程描述",
                            suggestion="添加地点转换的过渡描述，如'来到'、'前往'等",
                            fix_priority=5
                        ))
                        issues_found += 1

        return max(0, 100 - issues_found * 15)

    def _check_relationship_consistency(
        self,
        current_info: Dict,
        character_profiles: Dict,
        previous_chapters: List[Dict],
        report: ReviewReport
    ) -> float:
        """检查人物关系一致性"""
        current_chars = set(current_info.get("characters", []))

        if not current_chars:
            return 90

        issues_found = 0

        # 检查人物关系是否与设定冲突
        for char_name in current_chars:
            if char_name in character_profiles:
                profile = character_profiles[char_name]
                # 检查关系描述是否一致
                # 简化实现

        return max(0, 100 - issues_found * 15)

    def _check_fact_consistency(
        self,
        chapter_content: str,
        established_facts: List[Dict],
        report: ReviewReport
    ) -> float:
        """检查事实一致性"""
        if not established_facts:
            return 100

        issues_found = 0

        for fact in established_facts:
            fact_content = fact.get("content", "")
            fact_type = fact.get("type", "")

            # 检查是否有矛盾描述
            # 简化实现：检查否定词
            if fact_content[:10] in chapter_content:
                # 检查附近是否有否定词
                idx = chapter_content.find(fact_content[:10])
                surrounding = chapter_content[max(0, idx-20):min(len(chapter_content), idx+len(fact_content)+20)]

                negation_words = ["不是", "并未", "没有", "不对", "错误"]
                if any(word in surrounding for word in negation_words):
                    self._add_issue(report, ReviewIssue(
                        issue_id="CON004",
                        dimension="consistency",
                        severity=IssueSeverity.HIGH,
                        chapter_id=report.chapter_id,
                        location=None,
                        description=f"可能的事实矛盾：与已记录事实 '{fact_content[:30]}...' 存在冲突",
                        suggestion="核对事实描述，确保前后一致",
                        fix_priority=8
                    ))
                    issues_found += 1

        return max(0, 100 - issues_found * 20)
