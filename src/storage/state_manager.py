"""State Manager - 精简核心状态管理

管理 state.json 的读写操作：
- 进度跟踪（current_chapter, current_section）
- 人物状态快照
- 章节元数据列表
- 断点续传所需的最小信息

设计原则：
- state.json 保持精简（<5KB）
- 大数据存储在 index.db 和 vectors.db
"""

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ChapterMeta:
    """章节元数据（精简版，存储在state.json）"""
    id: str
    order: int
    title: str
    word_count: int = 0
    status: str = "pending"  # pending/writing/completed
    summary: str = ""  # 章节摘要（用于上下文）
    time_period: str = ""  # 时间段


@dataclass
class CharacterSnapshot:
    """人物状态快照"""
    name: str
    age: Optional[int] = None
    key_traits: List[str] = field(default_factory=list)
    current_status: str = ""  # 当前状态描述
    last_appearance_chapter: int = 0


@dataclass
class WritingProgress:
    """写作进度"""
    current_chapter: int = 0
    current_section: int = 0
    total_chapters: int = 0
    total_words: int = 0
    last_save_time: str = ""


@dataclass
class CoreState:
    """核心状态（存储在state.json）"""
    book_id: str
    book_title: str = ""
    subject_name: str = ""
    writing_style: str = "literary"

    # 进度跟踪
    progress: WritingProgress = field(default_factory=WritingProgress)

    # 章节元数据列表（仅存储基本信息）
    chapters: List[ChapterMeta] = field(default_factory=list)

    # 人物状态快照（仅核心人物）
    character_snapshots: Dict[str, CharacterSnapshot] = field(default_factory=dict)

    # 全局记忆摘要（最近3章）
    recent_summaries: List[str] = field(default_factory=list)

    # 版本信息
    version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoreState":
        """从字典创建"""
        # 处理嵌套dataclass
        progress_data = data.get("progress", {})
        progress = WritingProgress(**progress_data)

        chapters = [ChapterMeta(**c) for c in data.get("chapters", [])]
        characters = {
            k: CharacterSnapshot(**v)
            for k, v in data.get("character_snapshots", {}).items()
        }

        return cls(
            book_id=data.get("book_id", ""),
            book_title=data.get("book_title", ""),
            subject_name=data.get("subject_name", ""),
            writing_style=data.get("writing_style", "literary"),
            progress=progress,
            chapters=chapters,
            character_snapshots=characters,
            recent_summaries=data.get("recent_summaries", []),
            version=data.get("version", "1.0"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )


class StateManager:
    """状态管理器 - 管理精简的state.json"""

    def __init__(self, book_id: str, state_dir: Optional[Path] = None):
        self.book_id = book_id
        self.state_dir = Path(state_dir) if state_dir else Path(settings.paths.cache_dir)
        self.state_file = self.state_dir / f"{book_id}_state.json"
        self.state: Optional[CoreState] = None

    def init_state(
        self,
        book_title: str,
        subject_name: str,
        writing_style: str = "literary",
        total_chapters: int = 25
    ) -> CoreState:
        """初始化新状态"""
        self.state = CoreState(
            book_id=self.book_id,
            book_title=book_title,
            subject_name=subject_name,
            writing_style=writing_style,
            progress=WritingProgress(
                current_chapter=0,
                current_section=0,
                total_chapters=total_chapters,
                total_words=0,
                last_save_time=datetime.now().isoformat()
            )
        )
        self.save()
        logger.info(f"初始化状态文件: {self.state_file}")
        return self.state

    def load(self) -> Optional[CoreState]:
        """从文件加载状态"""
        if not self.state_file.exists():
            logger.warning(f"状态文件不存在: {self.state_file}")
            return None

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.state = CoreState.from_dict(data)
            logger.info(f"加载状态文件: {self.state_file}")
            return self.state
        except Exception as e:
            logger.error(f"加载状态文件失败: {e}")
            return None

    def save(self):
        """保存状态到文件"""
        if self.state is None:
            logger.warning("状态为空，无法保存")
            return

        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state.updated_at = datetime.now().isoformat()
        self.state.progress.last_save_time = datetime.now().isoformat()

        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state.to_dict(), f, ensure_ascii=False, indent=2)
            logger.debug(f"保存状态文件: {self.state_file}")
        except Exception as e:
            logger.error(f"保存状态文件失败: {e}")
            raise

    def update_progress(self, chapter: int, section: int = 0, word_count: int = 0):
        """更新写作进度"""
        if self.state is None:
            raise ValueError("状态未初始化")

        self.state.progress.current_chapter = chapter
        self.state.progress.current_section = section
        if word_count > 0:
            self.state.progress.total_words += word_count
        self.save()

    def add_chapter_meta(self, chapter_meta: ChapterMeta):
        """添加章节元数据"""
        if self.state is None:
            raise ValueError("状态未初始化")

        # 检查是否已存在
        for i, ch in enumerate(self.state.chapters):
            if ch.id == chapter_meta.id:
                self.state.chapters[i] = chapter_meta
                self.save()
                return

        self.state.chapters.append(chapter_meta)
        self.save()

    def update_chapter_status(self, chapter_id: str, status: str, word_count: int = 0):
        """更新章节状态"""
        if self.state is None:
            raise ValueError("状态未初始化")

        for ch in self.state.chapters:
            if ch.id == chapter_id:
                ch.status = status
                if word_count > 0:
                    ch.word_count = word_count
                self.save()
                return

    def add_character_snapshot(self, snapshot: CharacterSnapshot):
        """添加人物状态快照"""
        if self.state is None:
            raise ValueError("状态未初始化")

        self.state.character_snapshots[snapshot.name] = snapshot
        self.save()

    def update_recent_summaries(self, summary: str, max_keep: int = 3):
        """更新最近章节摘要"""
        if self.state is None:
            raise ValueError("状态未初始化")

        self.state.recent_summaries.append(summary)
        if len(self.state.recent_summaries) > max_keep:
            self.state.recent_summaries = self.state.recent_summaries[-max_keep:]
        self.save()

    def get_resume_point(self) -> Dict[str, Any]:
        """获取断点续传信息"""
        if self.state is None:
            return {"can_resume": False}

        return {
            "can_resume": True,
            "book_id": self.state.book_id,
            "book_title": self.state.book_title,
            "subject_name": self.state.subject_name,
            "current_chapter": self.state.progress.current_chapter,
            "current_section": self.state.progress.current_section,
            "total_chapters": self.state.progress.total_chapters,
            "total_words": self.state.progress.total_words,
            "completed_chapters": len([c for c in self.state.chapters if c.status == "completed"]),
            "recent_summaries": self.state.recent_summaries,
        }

    def get_state_size(self) -> int:
        """获取状态文件大小（字节）"""
        if not self.state_file.exists():
            return 0
        return self.state_file.stat().st_size

    def is_state_valid(self) -> bool:
        """检查状态是否有效"""
        if self.state is None:
            return False
        return (
            self.state.book_id == self.book_id
            and self.state.progress.total_chapters > 0
        )
