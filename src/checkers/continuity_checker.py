"""连贯性检查器 (ContinuityChecker)

传记场景：
- 章节间过渡流畅度
- 时间/地点/情绪的连贯
- 前文伏笔是否有回应
"""
import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .base_checker import BaseChecker, ReviewReport, ReviewIssue, IssueSeverity, DimensionScore


class ForeshadowingType(Enum):
    """伏笔类型"""
    SHORT_TERM = "short_term"      # 短期伏笔 1-3章
    MID_TERM = "mid_term"          # 中期伏笔 4-10章
    LONG_TERM = "long_term"        # 长期伏笔 10+章


@dataclass
class Foreshadowing:
    """伏笔记录"""
    setup_chapter: str
    setup_content: str
    foreshadowing_type: ForeshadowingType
    payoff_chapter: Optional[str] = None
    is_resolved: bool = False
    chapters_since_setup: int = 0


@dataclass
class PlotThread:
    """情节线索"""
    thread_id: str
    description: str
    introduced_chapter: str
    last_mentioned_chapter: str
    status: str = "active"  # active/resolved/dormant/forgotten


class ContinuityChecker(BaseChecker):
    """
    连贯性检查器

    检查传记叙事的：
    1. 场景转换流畅度 - 章节间过渡是否自然
    2. 情节线索连贯 - 线索是否有始有终
    3. 伏笔管理 - 伏笔是否得到回收
    4. 逻辑流畅性 - 因果关系是否清晰
    """

    def __init__(self):
        super().__init__(
            checker_name="ContinuityChecker",
            description="检查章节间过渡流畅度、情节线索连贯性和伏笔回收"
        )
        self.config = {
            "max_dormant_chapters": 15,     # 线索休眠最大章节数
            "foreshadowing_warning": 10,    # 伏笔警告章节数
            "strict_transitions": True,     # 严格过渡检查
        }

    def check(self, chapter_content: str, context: Dict[str, Any]) -> ReviewReport:
        """执行连贯性检查"""
        chapter_id = context.get("chapter_id", "unknown")
        chapter_title = context.get("chapter_title", "")

        report = self._create_report(chapter_id, chapter_title)

        # 获取前序章节
        previous_chapters = context.get("previous_chapters", [])
        last_chapter = previous_chapters[-1] if previous_chapters else None

        # 获取活跃线索
        active_threads = context.get("active_plot_threads", [])

        # 检查场景转换
        transition_score = self._check_scene_transitions(
            chapter_content, last_chapter, report
        )

        # 检查情节线索
        thread_score = self._check_plot_threads(
            chapter_content, active_threads, previous_chapters, report
        )

        # 检查伏笔回收
        foreshadowing_score = self._check_foreshadowing(
            chapter_content, previous_chapters, report
        )

        # 检查逻辑流畅性
        logic_score = self._check_logical_flow(chapter_content, report)

        # 计算维度得分
        report.dimension_scores["continuity"] = DimensionScore(
            dimension_name="连贯性检查",
            score=round((transition_score + thread_score + foreshadowing_score + logic_score) / 4, 2),
            weight=1.0,
            details={
                "transition_score": transition_score,
                "thread_score": thread_score,
                "foreshadowing_score": foreshadowing_score,
                "logic_score": logic_score,
                "active_threads_count": len(active_threads),
                "previous_chapters_count": len(previous_chapters)
            }
        )

        report.overall_score = self._calculate_overall_score(report)
        report.suggestions = self._generate_suggestions(report)

        return report

    def _check_scene_transitions(
        self,
        chapter_content: str,
        last_chapter: Optional[Dict],
        report: ReviewReport
    ) -> float:
        """检查场景转换流畅度"""
        if not last_chapter:
            return 90  # 首章无过渡问题

        issues_found = 0

        # 提取当前章节开头
        current_opening = chapter_content[:200]

        # 提取上章结尾
        last_content = last_chapter.get("content", "")
        last_ending = last_content[-200:] if last_content else ""

        # 检查时间过渡
        time_markers = ["第二天", "次日", "几天后", "一周后", "一个月后", "一年后", "与此同时", "很快"]
        has_time_transition = any(marker in current_opening for marker in time_markers)

        # 检查地点过渡
        location_markers = ["来到", "前往", "到达", "回到", "离开", "在"]
        has_location_transition = any(marker in current_opening for marker in location_markers)

        # 检查情绪过渡
        emotion_markers = ["心情", "情绪", "感觉", "心中", "仍然", "依旧"]
        has_emotion_continuation = any(marker in current_opening for marker in emotion_markers)

        # 评估过渡质量
        transition_quality = 0
        if has_time_transition:
            transition_quality += 30
        if has_location_transition:
            transition_quality += 30
        if has_emotion_continuation:
            transition_quality += 20

        # 检查是否有突兀的跳跃
        abrupt_jumps = self._detect_abrupt_jumps(last_ending, current_opening)
        if abrupt_jumps:
            self._add_issue(report, ReviewIssue(
                issue_id="CONTI001",
                dimension="continuity",
                severity=IssueSeverity.MEDIUM,
                chapter_id=report.chapter_id,
                location="章节开头",
                description="章节间过渡突兀，可能存在时间或地点跳跃",
                suggestion="添加过渡段落，说明时间流逝或地点转换",
                fix_priority=6
            ))
            issues_found += 1

        # 检查情绪连贯
        emotion_gap = self._check_emotion_gap(last_ending, current_opening)
        if emotion_gap:
            self._add_issue(report, ReviewIssue(
                issue_id="CONTI002",
                dimension="continuity",
                severity=IssueSeverity.LOW,
                chapter_id=report.chapter_id,
                location="章节开头",
                description="情绪转换过于突兀，缺少过渡",
                suggestion="添加情绪过渡描写，承接上章情绪",
                fix_priority=4
            ))
            issues_found += 0.5

        return max(0, transition_quality - issues_found * 15)

    def _detect_abrupt_jumps(self, last_ending: str, current_opening: str) -> bool:
        """检测突兀跳跃"""
        # 提取地点信息
        location_indicators = ["在", "于", "来到", "前往"]

        last_locations = []
        current_locations = []

        for indicator in location_indicators:
            if indicator in last_ending:
                idx = last_ending.find(indicator)
                last_locations.append(last_ending[idx:idx+10])
            if indicator in current_opening:
                idx = current_opening.find(indicator)
                current_locations.append(current_opening[idx:idx+10])

        # 如果地点完全不同且没有过渡词
        if last_locations and current_locations:
            transition_words = ["来到", "前往", "到达", "随后", "之后", "第二天"]
            has_transition = any(word in current_opening for word in transition_words)

            if not has_transition:
                return True

        return False

    def _check_emotion_gap(self, last_ending: str, current_opening: str) -> bool:
        """检查情绪断层"""
        # 上章结尾情绪
        ending_emotions = self._extract_emotions(last_ending)
        opening_emotions = self._extract_emotions(current_opening)

        # 如果上章情绪强烈而本章完全无情绪承接
        strong_emotions = ["愤怒", "悲伤", "激动", "震惊", "绝望"]
        if any(emo in ending_emotions for emo in strong_emotions):
            if not opening_emotions:
                return True

        return False

    def _extract_emotions(self, text: str) -> List[str]:
        """提取情绪词"""
        emotion_words = [
            "高兴", "开心", "快乐", "兴奋", "激动",
            "悲伤", "难过", "痛苦", "伤心", "绝望",
            "愤怒", "生气", "恼火", "气愤", "暴怒",
            "害怕", "恐惧", "担心", "焦虑", "紧张",
            "平静", "安心", "放松", "欣慰", "满足"
        ]
        return [word for word in emotion_words if word in text]

    def _check_plot_threads(
        self,
        chapter_content: str,
        active_threads: List[PlotThread],
        previous_chapters: List[Dict],
        report: ReviewReport
    ) -> float:
        """检查情节线索连贯性"""
        issues_found = 0
        resolved_count = 0

        for thread in active_threads:
            # 检查线索是否在本章提及
            if thread.description[:10] in chapter_content:
                thread.last_mentioned_chapter = report.chapter_id
                if self._is_thread_resolved(thread, chapter_content):
                    thread.status = "resolved"
                    resolved_count += 1
            else:
                # 计算休眠章节数
                try:
                    current_num = int(report.chapter_id.replace("ch", "").replace("章", ""))
                    last_num = int(thread.last_mentioned_chapter.replace("ch", "").replace("章", ""))
                    dormant_chapters = current_num - last_num
                except:
                    dormant_chapters = len(previous_chapters)

                if dormant_chapters > self.config["max_dormant_chapters"]:
                    self._add_issue(report, ReviewIssue(
                        issue_id="CONTI003",
                        dimension="continuity",
                        severity=IssueSeverity.MEDIUM,
                        chapter_id=report.chapter_id,
                        location=None,
                        description=f"情节线索 '{thread.description[:30]}...' 已休眠{dormant_chapters}章，可能被遗忘",
                        suggestion="在本章提及该线索进展，或安排回收",
                        fix_priority=6
                    ))
                    thread.status = "dormant"
                    issues_found += 1

        # 检查是否有新线索
        new_threads = self._identify_new_threads(chapter_content)

        return max(0, 100 - issues_found * 10 + resolved_count * 5)

    def _is_thread_resolved(self, thread: PlotThread, content: str) -> bool:
        """检查线索是否已解决"""
        resolution_signals = ["终于", "最终", "结果", "完成", "结束", "解决", "达成"]
        return any(signal in content for signal in resolution_signals)

    def _identify_new_threads(self, content: str) -> List[PlotThread]:
        """识别新线索"""
        new_threads = []

        # 新线索信号
        setup_patterns = [
            r'(?:不久后|将来|以后| upcoming|即将到来)',
            r'(?:悬念|疑问|谜团|未解之谜)',
            r'(?:等待|期待|悬念)',
        ]

        for pattern in setup_patterns:
            if re.search(pattern, content):
                # 简化实现
                pass

        return new_threads

    def _check_foreshadowing(
        self,
        chapter_content: str,
        previous_chapters: List[Dict],
        report: ReviewReport
    ) -> float:
        """检查伏笔回收"""
        if len(previous_chapters) < 3:
            return 90

        issues_found = 0
        resolved_count = 0

        # 检查前几章设置的伏笔
        for i, ch in enumerate(previous_chapters[-10:]):  # 检查最近10章
            ch_content = ch.get("content", "")
            ch_id = ch.get("chapter_id", f"ch-{i}")

            # 识别伏笔
            foreshadowings = self._extract_foreshadowings(ch_content, ch_id)

            for fs in foreshadowings:
                # 检查是否在本章回收
                if self._is_foreshadowing_payoff(fs, chapter_content):
                    resolved_count += 1
                else:
                    fs.chapters_since_setup += 1

                    # 长期伏笔警告
                    if fs.foreshadowing_type == ForeshadowingType.LONG_TERM:
                        if fs.chapters_since_setup > self.config["foreshadowing_warning"]:
                            self._add_issue(report, ReviewIssue(
                                issue_id="CONTI004",
                                dimension="continuity",
                                severity=IssueSeverity.LOW,
                                chapter_id=report.chapter_id,
                                location=None,
                                description=f"长期伏笔 '{fs.setup_content[:30]}...' 已{fs.chapters_since_setup}章未回收",
                                suggestion="考虑在本章或近期回收该伏笔",
                                fix_priority=4
                            ))
                            issues_found += 0.5

        return max(0, 100 - issues_found * 10 + resolved_count * 10)

    def _extract_foreshadowings(self, content: str, chapter_id: str) -> List[Foreshadowing]:
        """提取伏笔"""
        foreshadowings = []

        # 伏笔信号词
        foreshadowing_signals = [
            r'(?:不知|没想到|未曾想|谁也没想到)([^，。、\n]+)',
            r'(?:伏笔|暗示|预示|征兆)([^，。、\n]+)',
            r'(?:日后|将来|以后|未来)([^，。、\n]+)',
        ]

        for pattern in foreshadowing_signals:
            matches = re.finditer(pattern, content)
            for match in matches:
                fs = Foreshadowing(
                    setup_chapter=chapter_id,
                    setup_content=match.group(0),
                    foreshadowing_type=ForeshadowingType.MID_TERM
                )
                foreshadowings.append(fs)

        return foreshadowings

    def _is_foreshadowing_payoff(self, foreshadowing: Foreshadowing, content: str) -> bool:
        """检查伏笔是否回收"""
        # 简化实现：检查相关内容是否出现
        setup_keywords = foreshadowing.setup_content[:10]
        payoff_signals = ["果然", "正如", "原来", "终于明白", "恍然大悟"]

        return setup_keywords in content and any(signal in content for signal in payoff_signals)

    def _check_logical_flow(self, chapter_content: str, report: ReviewReport) -> float:
        """检查逻辑流畅性"""
        issues_found = 0

        # 检查因果关系
        causality_issues = self._check_causality(chapter_content)
        issues_found += causality_issues

        # 检查逻辑矛盾
        contradiction_issues = self._check_contradictions(chapter_content)
        issues_found += contradiction_issues

        # 检查拖沓
        drag_issues = self._check_pacing_drag(chapter_content, report)
        issues_found += drag_issues

        return max(0, 100 - issues_found * 10)

    def _check_causality(self, content: str) -> int:
        """检查因果关系"""
        issues = 0

        # 检查突然发生的事件
        sudden_patterns = [
            r'(?:突然|忽然|猛然|骤然)([^，。、\n]+)(?:没有|毫无|不知)([^，。、\n]+)',
        ]

        for pattern in sudden_patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                # 检查是否有前置原因
                # 简化实现
                pass

        return issues

    def _check_contradictions(self, content: str) -> int:
        """检查逻辑矛盾"""
        issues = 0

        # 检查前后矛盾的描述
        # 简化实现

        return issues

    def _check_pacing_drag(self, content: str, report: ReviewReport) -> int:
        """检查节奏拖沓"""
        paragraphs = content.split("\n\n")

        # 检查是否有连续多段无实质内容
        empty_paragraphs = 0
        for para in paragraphs:
            if len(para.strip()) < 50:  # 过短段落
                empty_paragraphs += 1

        if empty_paragraphs > len(paragraphs) * 0.3:
            self._add_issue(report, ReviewIssue(
                issue_id="CONTI005",
                dimension="continuity",
                severity=IssueSeverity.LOW,
                chapter_id=report.chapter_id,
                location=None,
                description=f"章节内容较空，有{empty_paragraphs}段内容过少",
                suggestion="合并或扩展简短段落，增加实质内容",
                fix_priority=3
            ))
            return 1

        return 0
