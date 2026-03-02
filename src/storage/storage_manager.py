"""统一存储管理器 - 整合三层存储架构

提供统一的接口来管理：
1. state.json - 精简核心状态
2. index.db - SQLite结构化数据
3. vectors.db - 向量数据

使用示例:
    storage = StorageManager("book_001")
    storage.init_book("传主传记", "张三")

    # 保存章节
    storage.save_chapter(chapter_data)

    # 检索素材
    results = storage.search_materials("创业初期")

    # 获取人物关系
    relations = storage.get_character_relations("张三")
"""

import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass

from src.config import settings
from src.models import InterviewMaterial, ChapterOutline

from .state_manager import StateManager, ChapterMeta, CharacterSnapshot
from .index_manager import (
    IndexManager, EntityMeta, RelationshipMeta,
    TimelineEventMeta, ReviewMetricsMeta
)
from .vector_manager import VectorManager, VectorEntry, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class StorageStats:
    """存储统计信息"""
    state_size_bytes: int
    index_db_size_bytes: int
    vector_db_size_bytes: int
    entity_count: int
    relationship_count: int
    timeline_event_count: int
    vector_entry_count: int


class StorageManager:
    """统一存储管理器

    整合三层存储架构，提供统一的访问接口。
    """

    def __init__(self, book_id: str, storage_dir: Optional[Path] = None):
        self.book_id = book_id
        self.storage_dir = Path(storage_dir) if storage_dir else Path(settings.paths.cache_dir)

        # 初始化三层存储
        self.state = StateManager(book_id, self.storage_dir)
        self.index = IndexManager(book_id, self.storage_dir)
        self.vectors = VectorManager(book_id, self.storage_dir)

        logger.info(f"初始化存储管理器: {book_id}")

    def init_book(
        self,
        book_title: str,
        subject_name: str,
        writing_style: str = "literary",
        total_chapters: int = 25
    ):
        """初始化书籍存储"""
        # 初始化状态
        self.state.init_state(
            book_title=book_title,
            subject_name=subject_name,
            writing_style=writing_style,
            total_chapters=total_chapters
        )

        # 添加传主实体
        subject_entity = EntityMeta(
            id=f"person_{subject_name}",
            type="person",
            name=subject_name,
            importance="major"
        )
        self.index.add_entity(subject_entity)

        logger.info(f"初始化书籍存储: {book_title}")

    # ==================== 章节管理 ====================

    def save_chapter_meta(self, chapter: ChapterMeta):
        """保存章节元数据"""
        self.state.add_chapter_meta(chapter)

    def update_chapter_progress(self, chapter_idx: int, section_idx: int = 0, word_count: int = 0):
        """更新章节进度"""
        self.state.update_progress(chapter_idx, section_idx, word_count)

    def get_chapter_meta(self, chapter_id: str) -> Optional[ChapterMeta]:
        """获取章节元数据"""
        if self.state.state is None:
            return None
        for ch in self.state.state.chapters:
            if ch.id == chapter_id:
                return ch
        return None

    # ==================== 实体管理 ====================

    def add_character(self, entity: EntityMeta) -> bool:
        """添加人物实体"""
        entity.type = "person"
        return self.index.add_entity(entity)

    def add_location(self, entity: EntityMeta) -> bool:
        """添加地点实体"""
        entity.type = "location"
        return self.index.add_entity(entity)

    def add_organization(self, entity: EntityMeta) -> bool:
        """添加组织实体"""
        entity.type = "organization"
        return self.index.add_entity(entity)

    def get_entity(self, entity_id: str) -> Optional[EntityMeta]:
        """获取实体"""
        return self.index.get_entity(entity_id)

    def search_entities(self, keyword: str) -> List[EntityMeta]:
        """搜索实体"""
        return self.index.search_entities(keyword)

    def get_characters(self) -> List[EntityMeta]:
        """获取所有人物"""
        return self.index.get_entities_by_type("person")

    def get_locations(self) -> List[EntityMeta]:
        """获取所有地点"""
        return self.index.get_entities_by_type("location")

    # ==================== 关系管理 ====================

    def add_relationship(self, relationship: RelationshipMeta) -> bool:
        """添加关系"""
        return self.index.add_relationship(relationship)

    def get_character_relations(self, character_name: str) -> List[Tuple[RelationshipMeta, str]]:
        """获取人物关系"""
        # 先查找实体ID
        entities = self.index.search_entities(character_name)
        if not entities:
            return []

        entity_id = entities[0].id
        return self.index.get_relationships(entity_id)

    def get_relationship_graph(self) -> Dict[str, List[Dict]]:
        """获取关系图谱"""
        return self.index.get_relationship_graph()

    # ==================== 时间线管理 ====================

    def add_timeline_event(self, event: TimelineEventMeta) -> bool:
        """添加时间线事件"""
        return self.index.add_timeline_event(event)

    def get_timeline(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[TimelineEventMeta]:
        """获取时间线事件"""
        return self.index.get_timeline_events(start_date, end_date)

    def get_timeline_by_period(self, period: str) -> List[TimelineEventMeta]:
        """按时期获取时间线"""
        return self.index.get_timeline_by_period(period)

    # ==================== 向量存储管理 ====================

    def add_material_vector(self, material: InterviewMaterial, parent_id: Optional[str] = None) -> bool:
        """添加素材向量"""
        entry = VectorEntry(
            id=material.id,
            content=material.content,
            vector_type=VectorManager.TYPE_MATERIAL,
            parent_id=parent_id,
            metadata={
                "source_file": material.source_file,
                "chunk_index": material.chunk_index,
                "topics": material.topics,
                "time_references": material.time_references,
                "entities": material.entities,
            }
        )
        return self.vectors.add_entry(entry)

    def add_chapter_summary_vector(self, chapter_id: str, summary: str) -> bool:
        """添加章节摘要向量"""
        entry = VectorEntry(
            id=f"summary_{chapter_id}",
            content=summary,
            vector_type=VectorManager.TYPE_CHAPTER_SUMMARY,
            chapter_id=chapter_id,
            metadata={"chapter_id": chapter_id}
        )
        return self.vectors.add_entry(entry)

    def add_scene_vector(self, scene_id: str, content: str, chapter_id: str, parent_id: Optional[str] = None) -> bool:
        """添加场景向量"""
        entry = VectorEntry(
            id=scene_id,
            content=content,
            vector_type=VectorManager.TYPE_SCENE,
            chapter_id=chapter_id,
            parent_id=parent_id,
            metadata={"chapter_id": chapter_id}
        )
        return self.vectors.add_entry(entry)

    def search_materials(self, query: str, n_results: int = 10) -> List[SearchResult]:
        """搜索素材"""
        return self.vectors.search(
            query,
            vector_type=VectorManager.TYPE_MATERIAL,
            n_results=n_results
        )

    def search_chapter_summaries(self, query: str, n_results: int = 5) -> List[SearchResult]:
        """搜索章节摘要"""
        return self.vectors.search(
            query,
            vector_type=VectorManager.TYPE_CHAPTER_SUMMARY,
            n_results=n_results
        )

    def search_in_chapter(self, chapter_id: str, query: str, n_results: int = 5) -> List[SearchResult]:
        """在指定章节内搜索"""
        # 获取章节下的所有向量
        entries = self.vectors.get_by_chapter(chapter_id)
        if not entries:
            return []

        # 在子项中搜索
        # 这里简化处理，实际应该使用 search_with_parent
        return self.vectors.search(query, n_results=n_results)

    # ==================== 审查指标 ====================

    def add_review_metrics(self, metrics: ReviewMetricsMeta) -> bool:
        """添加审查指标"""
        return self.index.add_review_metrics(metrics)

    def get_chapter_quality(self, chapter_id: str) -> Optional[ReviewMetricsMeta]:
        """获取章节质量指标"""
        return self.index.get_review_metrics(chapter_id)

    def get_quality_trend(self, last_n_chapters: int = 10) -> Dict[str, Any]:
        """获取质量趋势"""
        return self.index.get_quality_trend(last_n_chapters)

    # ==================== 断点续传 ====================

    def get_resume_point(self) -> Dict[str, Any]:
        """获取断点续传信息"""
        return self.state.get_resume_point()

    def can_resume(self) -> bool:
        """检查是否可以断点续传"""
        resume_info = self.get_resume_point()
        return resume_info.get("can_resume", False)

    # ==================== 统计信息 ====================

    def get_stats(self) -> StorageStats:
        """获取存储统计信息"""
        # 获取文件大小
        state_size = self.state.get_state_size()

        index_size = 0
        if self.index.db_path.exists():
            index_size = self.index.db_path.stat().st_size

        vector_size = 0
        if self.vectors.db_path.exists():
            vector_size = self.vectors.db_path.stat().st_size

        # 获取数据库统计
        index_stats = self.index.get_stats()
        vector_stats = self.vectors.get_stats()

        return StorageStats(
            state_size_bytes=state_size,
            index_db_size_bytes=index_size,
            vector_db_size_bytes=vector_size,
            entity_count=sum(index_stats.get("entities", {}).values()),
            relationship_count=sum(index_stats.get("relationships", {}).values()),
            timeline_event_count=sum(index_stats.get("timeline_events", {}).values()),
            vector_entry_count=vector_stats.get("total", 0)
        )

    def print_stats(self):
        """打印存储统计信息"""
        stats = self.get_stats()

        print(f"\n=== 存储统计: {self.book_id} ===")
        print(f"State文件大小: {stats.state_size_bytes / 1024:.2f} KB")
        print(f"Index数据库大小: {stats.index_db_size_bytes / 1024:.2f} KB")
        print(f"Vector数据库大小: {stats.vector_db_size_bytes / 1024:.2f} KB")
        print(f"实体数量: {stats.entity_count}")
        print(f"关系数量: {stats.relationship_count}")
        print(f"时间线事件: {stats.timeline_event_count}")
        print(f"向量条目: {stats.vector_entry_count}")

    # ==================== 备份与清理 ====================

    def backup(self, backup_dir: Optional[Path] = None) -> Path:
        """备份所有存储"""
        import shutil
        from datetime import datetime

        if backup_dir is None:
            backup_dir = self.storage_dir / "backups"

        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{self.book_id}_{timestamp}"
        backup_path.mkdir(exist_ok=True)

        # 备份 state.json
        if self.state.state_file.exists():
            shutil.copy2(self.state.state_file, backup_path / self.state.state_file.name)

        # 备份 index.db
        if self.index.db_path.exists():
            shutil.copy2(self.index.db_path, backup_path / self.index.db_path.name)

        # 备份 vectors.db
        if self.vectors.db_path.exists():
            shutil.copy2(self.vectors.db_path, backup_path / self.vectors.db_path.name)

        logger.info(f"备份完成: {backup_path}")
        return backup_path

    def clear_all(self):
        """清空所有存储（危险操作）"""
        logger.warning(f"清空所有存储: {self.book_id}")

        # 清空向量存储
        self.vectors.clear()

        # 注意：index.db 和 state.json 的清空需要谨慎处理
        # 这里只清空向量数据，保留结构

        logger.info("存储已清空")
