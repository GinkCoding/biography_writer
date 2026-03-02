"""三层存储分离架构 - Storage Layer

包含三个独立存储:
1. state.json - 精简核心状态文件 (<5KB)
2. index.db - SQLite结构化数据
3. vectors.db - 向量数据独立存储
"""

from .state_manager import StateManager, ChapterMeta, CharacterSnapshot, WritingProgress, CoreState
from .index_manager import (
    IndexManager, EntityMeta, RelationshipMeta,
    TimelineEventMeta, ReviewMetricsMeta
)
from .vector_manager import VectorManager, VectorEntry, SearchResult
from .storage_manager import StorageManager, StorageStats

__all__ = [
    # State Manager
    "StateManager",
    "ChapterMeta",
    "CharacterSnapshot",
    "WritingProgress",
    "CoreState",
    # Index Manager
    "IndexManager",
    "EntityMeta",
    "RelationshipMeta",
    "TimelineEventMeta",
    "ReviewMetricsMeta",
    # Vector Manager
    "VectorManager",
    "VectorEntry",
    "SearchResult",
    # Unified Storage Manager
    "StorageManager",
    "StorageStats",
]