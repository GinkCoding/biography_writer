"""
轻量级事实数据库 - JSON存储

维护传记生成过程中的关键事实，作为LLM的"记忆护栏"
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class Person:
    """
    人物信息

    关系是动态的，通过clues（线索）记录每次互动，
    由LLM综合判断当前关系状态，而非硬编码状态机
    """
    name: str
    relationship: str  # 与传主关系（初始关系，如"父亲"、"朋友"）
    first_appearance: int  # 首次出场章节
    description: str = ""  # 人物描述

    # 动态线索记录（取代硬编码status）
    relationship_clues: List[Dict] = field(default_factory=list)
    # 每个clue: {chapter, type, description, context}
    # type可以是任何描述性词语："去世"、"决裂"、"大吵"、"和解"、"疏远"等

    # 物理状态（客观事实）
    physical_status: str = "alive"  # alive, deceased（仅记录是否在世，不涉关系）
    death_chapter: Optional[int] = None

    def add_clue(self, chapter: int, clue_type: str, description: str, context: str = ""):
        """添加关系线索"""
        self.relationship_clues.append({
            "chapter": chapter,
            "type": clue_type,
            "description": description,
            "context": context
        })

    def get_clues_after(self, chapter: int) -> List[Dict]:
        """获取某章之后的所有线索"""
        return [c for c in self.relationship_clues if c["chapter"] >= chapter]

    def get_latest_clue(self) -> Optional[Dict]:
        """获取最新线索"""
        if not self.relationship_clues:
            return None
        return max(self.relationship_clues, key=lambda x: x["chapter"])


@dataclass
class Event:
    """事件信息"""
    name: str
    year: Optional[int]
    month: Optional[int]
    location: str
    chapter: int  # 出现在第几章
    section: Optional[int] = None
    description: str = ""


@dataclass
class Location:
    """地点信息"""
    name: str
    first_appearance: int
    description: str = ""


@dataclass
class TimelineGap:
    """时间空档（可推断区域）"""
    start_year: int
    end_year: int
    gap_type: str  # "youth", "career", "family"等
    inference_notes: str = ""


@dataclass
class KeyNumber:
    """关键数字（年龄、金额等）"""
    category: str  # "age", "money", "quantity"
    value: str
    year: Optional[int]
    context: str = ""


class FactsDatabase:
    """
    轻量级事实数据库

    功能：
    1. 存储人物清单（避免前后文不一致）
    2. 维护时间线（确保时间顺序正确）
    3. 记录关键数字（避免矛盾）
    4. 标记时间空档（指导推断内容）
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # 数据存储
        self.persons: Dict[str, Person] = {}
        self.events: List[Event] = []
        self.locations: Dict[str, Location] = {}
        self.timeline_gaps: List[TimelineGap] = []
        self.key_numbers: List[KeyNumber] = []
        self.subject_birth_year: Optional[int] = None

        # 加载已有数据
        self._load()

    def _load(self):
        """从JSON加载"""
        if not self.db_path.exists():
            return

        try:
            data = json.loads(self.db_path.read_text(encoding='utf-8'))

            self.persons = {
                k: Person(**v) for k, v in data.get('persons', {}).items()
            }
            self.events = [Event(**e) for e in data.get('events', [])]
            self.locations = {
                k: Location(**v) for k, v in data.get('locations', {}).items()
            }
            self.timeline_gaps = [
                TimelineGap(**g) for g in data.get('timeline_gaps', [])
            ]
            self.key_numbers = [
                KeyNumber(**n) for n in data.get('key_numbers', [])
            ]
            self.subject_birth_year = data.get('subject_birth_year')

        except Exception as e:
            print(f"加载事实库失败: {e}，将创建新库")

    def save(self):
        """保存到JSON"""
        data = {
            'persons': {k: asdict(v) for k, v in self.persons.items()},
            'events': [asdict(e) for e in self.events],
            'locations': {k: asdict(v) for k, v in self.locations.items()},
            'timeline_gaps': [asdict(g) for g in self.timeline_gaps],
            'key_numbers': [asdict(n) for n in self.key_numbers],
            'subject_birth_year': self.subject_birth_year,
            'updated_at': datetime.now().isoformat()
        }

        self.db_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

    def add_person(self, name: str, relationship: str, chapter: int, description: str = ""):
        """添加人物"""
        if name not in self.persons:
            self.persons[name] = Person(
                name=name,
                relationship=relationship,
                first_appearance=chapter,
                description=description
            )
            self.save()

    def add_relationship_clue(self, name: str, chapter: int, clue_type: str, description: str, context: str = ""):
        """
        添加关系线索（取代硬编码状态更新）

        Args:
            name: 人物姓名
            chapter: 线索所在章节
            clue_type: 线索类型（可以是任意描述："去世"、"大吵"、"和解"、"疏远"等）
            description: 具体描述
            context: 上下文片段
        """
        if name in self.persons:
            self.persons[name].add_clue(chapter, clue_type, description, context)
            self.save()

    def update_physical_status(self, name: str, status: str, chapter: int):
        """
        更新人物物理状态（客观事实）

        Args:
            name: 人物姓名
            status: "alive" 或 "deceased"
            chapter: 状态变更章节
        """
        if name in self.persons:
            person = self.persons[name]
            person.physical_status = status
            if status == "deceased":
                person.death_chapter = chapter
            self.save()

    def check_person_usage(self, name: str, chapter: int) -> Dict:
        """
        获取人物在指定章节的使用上下文（供LLM判断）

        不再硬编码规则，而是提供完整线索让LLM理解关系动态

        Returns:
            {
                "physical_status": str,     # alive / deceased（客观事实）
                "death_chapter": int,       # 如去世，记录章节
                "clues_before": list,       # 本章之前的所有关系线索
                "clues_after": list,        # 本章及之后的线索（用于判断本章状态）
                "latest_clue": dict,        # 最新线索
                "relationship_history": str # 格式化的关系历史摘要
            }
        """
        if name not in self.persons:
            return {
                "physical_status": "unknown",
                "death_chapter": None,
                "clues_before": [],
                "clues_after": [],
                "latest_clue": None,
                "relationship_history": "新人物，无历史记录"
            }

        person = self.persons[name]

        clues_before = [c for c in person.relationship_clues if c["chapter"] < chapter]
        clues_after = [c for c in person.relationship_clues if c["chapter"] >= chapter]
        latest = person.get_latest_clue()

        # 构建关系历史文本
        history_lines = []
        for clue in sorted(person.relationship_clues, key=lambda x: x["chapter"]):
            history_lines.append(f"第{clue['chapter']}章: {clue['type']} - {clue['description']}")

        return {
            "physical_status": person.physical_status,
            "death_chapter": person.death_chapter,
            "clues_before": clues_before,
            "clues_after": clues_after,
            "latest_clue": latest,
            "relationship_history": "\n".join(history_lines) if history_lines else "无显著关系变化记录"
        }

    def add_event(self, name: str, year: Optional[int], location: str, chapter: int,
                  month: Optional[int] = None, description: str = ""):
        """添加事件"""
        self.events.append(Event(
            name=name,
            year=year,
            month=month,
            location=location,
            chapter=chapter,
            description=description
        ))
        self.events.sort(key=lambda e: (e.year or 0, e.month or 0))
        self.save()

    def add_location(self, name: str, chapter: int, description: str = ""):
        """添加地点"""
        if name not in self.locations:
            self.locations[name] = Location(
                name=name,
                first_appearance=chapter,
                description=description
            )
            self.save()

    def add_key_number(self, category: str, value: str, year: Optional[int] = None, context: str = ""):
        """添加关键数字"""
        self.key_numbers.append(KeyNumber(
            category=category,
            value=value,
            year=year,
            context=context
        ))
        self.save()

    def set_subject_birth_year(self, year: int):
        """设置传主出生年份"""
        self.subject_birth_year = year
        self.save()

    def get_age_at_year(self, year: int) -> Optional[int]:
        """计算某年的年龄"""
        if self.subject_birth_year:
            return year - self.subject_birth_year
        return None

    def find_timeline_gaps(self) -> List[TimelineGap]:
        """识别时间空档"""
        if len(self.events) < 2:
            return []

        gaps = []
        sorted_events = sorted(self.events, key=lambda e: e.year or 0)

        for i in range(len(sorted_events) - 1):
            curr_event = sorted_events[i]
            next_event = sorted_events[i + 1]

            if curr_event.year and next_event.year:
                gap_years = next_event.year - curr_event.year
                if gap_years > 2:  # 超过2年的空档
                    gaps.append(TimelineGap(
                        start_year=curr_event.year,
                        end_year=next_event.year,
                        gap_type=self._classify_gap_period(curr_event.year),
                        inference_notes=f"{curr_event.year}年后到{next_event.year}年前"
                    ))

        self.timeline_gaps = gaps
        return gaps

    def _classify_gap_period(self, year: int) -> str:
        """分类空档时期"""
        if self.subject_birth_year:
            age = year - self.subject_birth_year
            if age < 18:
                return "youth"
            elif age < 30:
                return "early_career"
            elif age < 50:
                return "prime_years"
            else:
                return "mature_years"
        return "unknown"

    def check_fact_consistency(self, fact_type: str, fact_value: str, context: str = "") -> Dict:
        """
        检查事实一致性

        Returns:
            {
                "consistent": bool,
                "conflicts": [冲突的事实],
                "suggestion": "建议"
            }
        """
        conflicts = []

        if fact_type == "person":
            # 检查人物关系是否矛盾
            if fact_value in self.persons:
                person = self.persons[fact_value]
                conflicts.append(f"人物'{fact_value}'已在第{person.first_appearance}章出现，关系为'{person.relationship}'")

        elif fact_type == "event_year":
            # 检查事件年份是否矛盾
            for event in self.events:
                if event.name in context and event.year:
                    if abs(event.year - int(fact_value)) > 1:
                        conflicts.append(f"事件年份矛盾：数据库记录为{event.year}年，新信息为{fact_value}年")

        elif fact_type == "location":
            # 地点通常不检查矛盾，只记录
            pass

        return {
            "consistent": len(conflicts) == 0,
            "conflicts": conflicts,
            "suggestion": "请核实事实" if conflicts else ""
        }

    def get_summary_for_llm(self) -> str:
        """生成给LLM的事实摘要"""
        lines = ["=== 已确认事实 ==="]

        if self.subject_birth_year:
            lines.append(f"传主出生年份: {self.subject_birth_year}")

        lines.append(f"\n人物清单（{len(self.persons)}人）:")
        for name, person in self.persons.items():
            status_str = ""
            if person.status == "deceased":
                status_str = f" [已故，第{person.status_chapter}章]"
            elif person.status == "departed":
                status_str = f" [已离开，第{person.status_chapter}章]"
            lines.append(f"  - {name}: {person.relationship} (第{person.first_appearance}章出场){status_str}")
            if person.status_description:
                lines.append(f"    说明: {person.status_description}")

        lines.append(f"\n关键事件（{len(self.events)}件）:")
        for event in self.events[:10]:  # 只显示前10个
            year_str = f"{event.year}年" if event.year else "时间不详"
            lines.append(f"  - {year_str}: {event.name} ({event.location})")

        lines.append(f"\n主要地点（{len(self.locations)}个）:")
        for name, loc in self.locations.items():
            lines.append(f"  - {name}")

        if self.timeline_gaps:
            lines.append(f"\n时间空档（可推断区域）:")
            for gap in self.timeline_gaps:
                lines.append(f"  - {gap.start_year}-{gap.end_year}: {gap.inference_notes}")

        return "\n".join(lines)

    def export_for_fact_checker(self) -> Dict:
        """导出给FactChecker使用的结构化数据"""
        return {
            "persons": {k: asdict(v) for k, v in self.persons.items()},
            "events": [asdict(e) for e in self.events],
            "locations": {k: asdict(v) for k, v in self.locations.items()},
            "key_numbers": [asdict(n) for n in self.key_numbers],
            "subject_birth_year": self.subject_birth_year
        }
