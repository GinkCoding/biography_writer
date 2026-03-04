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
    """人物信息"""
    name: str
    relationship: str  # 与传主关系
    first_appearance: int  # 首次出场章节
    description: str = ""  # 人物描述
    status: str = "active"  # 状态: active(活跃), deceased(已故), departed(离开/断绝关系)
    status_chapter: Optional[int] = None  # 状态变更章节
    status_description: str = ""  # 状态变更说明（如"因车祸去世"、"断绝父子关系"）


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

    def update_person_status(self, name: str, status: str, chapter: int, description: str = ""):
        """
        更新人物状态

        Args:
            name: 人物姓名
            status: 新状态 (active/deceased/departed)
            chapter: 状态变更章节
            description: 状态变更说明
        """
        if name in self.persons:
            person = self.persons[name]
            person.status = status
            person.status_chapter = chapter
            person.status_description = description
            self.save()

    def check_person_usage(self, name: str, chapter: int) -> Dict:
        """
        检查某章节中人物的使用方式是否恰当

        去世/离开人物可以：回忆、追思、提及生前事迹
        去世/离开人物不能：实际互动（说话、动作、在场）

        Returns:
            {
                "can_interact": bool,      # 是否可以直接互动（说话、动作）
                "can_remember": bool,      # 是否可以回忆、提及
                "status": str,             # 人物当前状态
                "restriction": str,        # 如有限制，说明具体限制
                "guidance": str            # 给LLM的指导建议
            }
        """
        if name not in self.persons:
            return {
                "can_interact": True,
                "can_remember": True,
                "status": "new",
                "restriction": "",
                "guidance": ""
            }

        person = self.persons[name]

        # 活跃人物：可以互动也可以回忆
        if person.status == "active":
            return {
                "can_interact": True,
                "can_remember": True,
                "status": "active",
                "restriction": "",
                "guidance": ""
            }

        # 检查状态变更章节
        if person.status_chapter and chapter >= person.status_chapter:
            # 在第X章或之后，人物已去世/离开
            if person.status == "deceased":
                return {
                    "can_interact": False,
                    "can_remember": True,
                    "status": "deceased",
                    "restriction": f"已于第{person.status_chapter}章去世",
                    "guidance": f"'{name}'已去世，可以写'想起{name}'、'怀念{name}'、'回忆起{name}生前'，"
                               f"但不能写'{name}说'、'{name}看着他'、'{name}在场'等直接互动"
                }
            elif person.status == "departed":
                return {
                    "can_interact": False,
                    "can_remember": True,
                    "status": "departed",
                    "restriction": f"已于第{person.status_chapter}章离开",
                    "guidance": f"'{name}'已离开，可以提及往事，但不能再写{name}与传主直接互动"
                }

        # 状态变更前，人物仍是活跃的
        return {
            "can_interact": True,
            "can_remember": True,
            "status": person.status,
            "restriction": "",
            "guidance": ""
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
