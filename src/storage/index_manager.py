"""Index Manager - SQLite结构化数据管理

管理 index.db 的读写操作：
- 实体表（人物、地点、组织）
- 关系表（人物关系网络）
- 时间线表（事件时间轴）
- 审查指标表
"""

import sqlite3
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import datetime

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class EntityMeta:
    """实体元数据"""
    id: str
    type: str  # person/location/organization/event
    name: str
    aliases: List[str] = field(default_factory=list)
    description: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    first_appearance_chapter: int = 0
    last_appearance_chapter: int = 0
    importance: str = "minor"  # major/supporting/minor
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class RelationshipMeta:
    """关系元数据"""
    id: str
    source_id: str
    target_id: str
    relation_type: str  # family/colleague/friend/enemy/other
    description: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    evidence_chapters: List[int] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class TimelineEventMeta:
    """时间线事件元数据"""
    id: str
    date: Optional[str] = None  # YYYY-MM-DD or YYYY-MM or YYYY
    date_approximate: bool = False
    title: str = ""
    description: str = ""
    location: str = ""
    characters_involved: List[str] = field(default_factory=list)
    importance: int = 5  # 1-10
    event_type: str = "life_event"  # life_event/turning_point/crisis/achievement/daily
    chapter_id: Optional[str] = None
    source_material_ids: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ReviewMetricsMeta:
    """审查指标元数据"""
    id: str
    chapter_id: str
    review_time: str = field(default_factory=lambda: datetime.now().isoformat())
    overall_score: float = 0.0
    dimension_scores: Dict[str, float] = field(default_factory=dict)
    issues: List[Dict[str, Any]] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


class IndexManager:
    """索引管理器 - 管理SQLite结构化数据"""

    def __init__(self, book_id: str, db_dir: Optional[Path] = None):
        self.book_id = book_id
        self.db_dir = Path(db_dir) if db_dir else Path(settings.paths.cache_dir)
        self.db_path = self.db_dir / f"{book_id}_index.db"
        self._init_db()

    @contextmanager
    def _get_conn(self):
        """获取数据库连接上下文"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """初始化数据库表"""
        self.db_dir.mkdir(parents=True, exist_ok=True)

        with self._get_conn() as conn:
            cursor = conn.cursor()

            # 实体表 - 人物、地点、组织
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    aliases TEXT,  -- JSON list
                    description TEXT,
                    attributes TEXT,  -- JSON dict
                    first_appearance_chapter INTEGER DEFAULT 0,
                    last_appearance_chapter INTEGER DEFAULT 0,
                    importance TEXT DEFAULT 'minor',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 关系表 - 人物关系网络
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS relationships (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    description TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    evidence_chapters TEXT,  -- JSON list
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES entities(id),
                    FOREIGN KEY (target_id) REFERENCES entities(id)
                )
            """)

            # 时间线事件表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS timeline_events (
                    id TEXT PRIMARY KEY,
                    date TEXT,
                    date_approximate INTEGER DEFAULT 0,
                    title TEXT NOT NULL,
                    description TEXT,
                    location TEXT,
                    characters_involved TEXT,  -- JSON list
                    importance INTEGER DEFAULT 5,
                    event_type TEXT DEFAULT 'life_event',
                    chapter_id TEXT,
                    source_material_ids TEXT,  -- JSON list
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 实体出场记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entity_appearances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    mention_count INTEGER DEFAULT 1,
                    context_snippets TEXT,  -- JSON list of text snippets
                    FOREIGN KEY (entity_id) REFERENCES entities(id)
                )
            """)

            # 审查指标表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS review_metrics (
                    id TEXT PRIMARY KEY,
                    chapter_id TEXT NOT NULL,
                    review_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    overall_score REAL DEFAULT 0.0,
                    dimension_scores TEXT,  -- JSON dict
                    issues TEXT,  -- JSON list
                    suggestions TEXT  -- JSON list
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_relations_source ON relationships(source_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_relations_target ON relationships(target_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_timeline_date ON timeline_events(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_timeline_chapter ON timeline_events(chapter_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_appearances_entity ON entity_appearances(entity_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_appearances_chapter ON entity_appearances(chapter_id)")

            conn.commit()
            logger.info(f"初始化索引数据库: {self.db_path}")

    # ==================== 实体管理 ====================

    def add_entity(self, entity: EntityMeta) -> bool:
        """添加实体"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO entities
                    (id, type, name, aliases, description, attributes,
                     first_appearance_chapter, last_appearance_chapter, importance, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entity.id,
                    entity.type,
                    entity.name,
                    json.dumps(entity.aliases, ensure_ascii=False),
                    entity.description,
                    json.dumps(entity.attributes, ensure_ascii=False),
                    entity.first_appearance_chapter,
                    entity.last_appearance_chapter,
                    entity.importance,
                    datetime.now().isoformat()
                ))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"添加实体失败: {e}")
                return False

    def get_entity(self, entity_id: str) -> Optional[EntityMeta]:
        """获取实体"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return EntityMeta(
                id=row["id"],
                type=row["type"],
                name=row["name"],
                aliases=json.loads(row["aliases"]) if row["aliases"] else [],
                description=row["description"] or "",
                attributes=json.loads(row["attributes"]) if row["attributes"] else {},
                first_appearance_chapter=row["first_appearance_chapter"] or 0,
                last_appearance_chapter=row["last_appearance_chapter"] or 0,
                importance=row["importance"] or "minor"
            )

    def get_entities_by_type(self, entity_type: str) -> List[EntityMeta]:
        """按类型获取实体"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM entities WHERE type = ?", (entity_type,))
            rows = cursor.fetchall()

            return [
                EntityMeta(
                    id=row["id"],
                    type=row["type"],
                    name=row["name"],
                    aliases=json.loads(row["aliases"]) if row["aliases"] else [],
                    description=row["description"] or "",
                    attributes=json.loads(row["attributes"]) if row["attributes"] else {},
                    first_appearance_chapter=row["first_appearance_chapter"] or 0,
                    last_appearance_chapter=row["last_appearance_chapter"] or 0,
                    importance=row["importance"] or "minor"
                )
                for row in rows
            ]

    def search_entities(self, keyword: str) -> List[EntityMeta]:
        """搜索实体"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM entities
                WHERE name LIKE ? OR description LIKE ? OR aliases LIKE ?
            """, (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"))
            rows = cursor.fetchall()

            return [
                EntityMeta(
                    id=row["id"],
                    type=row["type"],
                    name=row["name"],
                    aliases=json.loads(row["aliases"]) if row["aliases"] else [],
                    description=row["description"] or "",
                    attributes=json.loads(row["attributes"]) if row["attributes"] else {},
                    first_appearance_chapter=row["first_appearance_chapter"] or 0,
                    last_appearance_chapter=row["last_appearance_chapter"] or 0,
                    importance=row["importance"] or "minor"
                )
                for row in rows
            ]

    def update_entity_appearance(self, entity_id: str, chapter_id: str):
        """更新实体出场信息"""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # 获取当前实体信息
            cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
            row = cursor.fetchone()
            if not row:
                return

            # 解析章节序号
            try:
                chapter_num = int(chapter_id.split("_")[-1]) if "_" in chapter_id else 0
            except:
                chapter_num = 0

            # 更新首次和最后出场
            first_app = row["first_appearance_chapter"] or 9999
            last_app = row["last_appearance_chapter"] or 0

            if chapter_num > 0:
                first_app = min(first_app, chapter_num)
                last_app = max(last_app, chapter_num)

            cursor.execute("""
                UPDATE entities
                SET first_appearance_chapter = ?,
                    last_appearance_chapter = ?,
                    updated_at = ?
                WHERE id = ?
            """, (first_app if first_app != 9999 else 0, last_app, datetime.now().isoformat(), entity_id))

            # 记录出场
            cursor.execute("""
                INSERT OR REPLACE INTO entity_appearances
                (entity_id, chapter_id, mention_count)
                VALUES (?, ?, COALESCE(
                    (SELECT mention_count + 1 FROM entity_appearances
                     WHERE entity_id = ? AND chapter_id = ?), 1
                ))
            """, (entity_id, chapter_id, entity_id, chapter_id))

            conn.commit()

    # ==================== 关系管理 ====================

    def add_relationship(self, relationship: RelationshipMeta) -> bool:
        """添加关系"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO relationships
                    (id, source_id, target_id, relation_type, description,
                     start_date, end_date, evidence_chapters)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    relationship.id,
                    relationship.source_id,
                    relationship.target_id,
                    relationship.relation_type,
                    relationship.description,
                    relationship.start_date,
                    relationship.end_date,
                    json.dumps(relationship.evidence_chapters)
                ))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"添加关系失败: {e}")
                return False

    def get_relationships(self, entity_id: str) -> List[Tuple[RelationshipMeta, str]]:
        """获取实体的所有关系，返回(关系, 对方实体名称)"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.*, e.name as other_name
                FROM relationships r
                JOIN entities e ON (
                    CASE
                        WHEN r.source_id = ? THEN r.target_id = e.id
                        ELSE r.source_id = e.id
                    END
                )
                WHERE r.source_id = ? OR r.target_id = ?
            """, (entity_id, entity_id, entity_id))
            rows = cursor.fetchall()

            results = []
            for row in rows:
                rel = RelationshipMeta(
                    id=row["id"],
                    source_id=row["source_id"],
                    target_id=row["target_id"],
                    relation_type=row["relation_type"],
                    description=row["description"] or "",
                    start_date=row["start_date"],
                    end_date=row["end_date"],
                    evidence_chapters=json.loads(row["evidence_chapters"]) if row["evidence_chapters"] else []
                )
                results.append((rel, row["other_name"]))
            return results

    def get_relationship_graph(self) -> Dict[str, List[Dict]]:
        """获取关系图谱"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.*, s.name as source_name, t.name as target_name
                FROM relationships r
                JOIN entities s ON r.source_id = s.id
                JOIN entities t ON r.target_id = t.id
            """)
            rows = cursor.fetchall()

            nodes = {}
            edges = []

            for row in rows:
                source_id = row["source_id"]
                target_id = row["target_id"]

                if source_id not in nodes:
                    nodes[source_id] = {"id": source_id, "name": row["source_name"]}
                if target_id not in nodes:
                    nodes[target_id] = {"id": target_id, "name": row["target_name"]}

                edges.append({
                    "source": source_id,
                    "target": target_id,
                    "type": row["relation_type"],
                    "description": row["description"]
                })

            return {
                "nodes": list(nodes.values()),
                "edges": edges
            }

    # ==================== 时间线管理 ====================

    def add_timeline_event(self, event: TimelineEventMeta) -> bool:
        """添加时间线事件"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO timeline_events
                    (id, date, date_approximate, title, description, location,
                     characters_involved, importance, event_type, chapter_id, source_material_ids)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.id,
                    event.date,
                    1 if event.date_approximate else 0,
                    event.title,
                    event.description,
                    event.location,
                    json.dumps(event.characters_involved, ensure_ascii=False),
                    event.importance,
                    event.event_type,
                    event.chapter_id,
                    json.dumps(event.source_material_ids, ensure_ascii=False)
                ))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"添加时间线事件失败: {e}")
                return False

    def get_timeline_events(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        event_type: Optional[str] = None,
        min_importance: int = 0
    ) -> List[TimelineEventMeta]:
        """获取时间线事件"""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM timeline_events WHERE 1=1"
            params = []

            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            if min_importance > 0:
                query += " AND importance >= ?"
                params.append(min_importance)

            query += " ORDER BY date"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [
                TimelineEventMeta(
                    id=row["id"],
                    date=row["date"],
                    date_approximate=bool(row["date_approximate"]),
                    title=row["title"],
                    description=row["description"] or "",
                    location=row["location"] or "",
                    characters_involved=json.loads(row["characters_involved"]) if row["characters_involved"] else [],
                    importance=row["importance"],
                    event_type=row["event_type"],
                    chapter_id=row["chapter_id"],
                    source_material_ids=json.loads(row["source_material_ids"]) if row["source_material_ids"] else []
                )
                for row in rows
            ]

    def get_timeline_by_period(self, period: str) -> List[TimelineEventMeta]:
        """按时期获取时间线（如"1980s", "1990-1995"）"""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # 解析时期
            if "s" in period.lower():  # 年代格式 1980s
                year = period.lower().replace("s", "")
                cursor.execute(
                    "SELECT * FROM timeline_events WHERE date LIKE ? ORDER BY date",
                    (f"{year}%",)
                )
            elif "-" in period:  # 范围格式 1990-1995
                start, end = period.split("-")
                cursor.execute(
                    "SELECT * FROM timeline_events WHERE date >= ? AND date <= ? ORDER BY date",
                    (start, end)
                )
            else:  # 具体年份
                cursor.execute(
                    "SELECT * FROM timeline_events WHERE date LIKE ? ORDER BY date",
                    (f"{period}%",)
                )

            rows = cursor.fetchall()
            return [
                TimelineEventMeta(
                    id=row["id"],
                    date=row["date"],
                    date_approximate=bool(row["date_approximate"]),
                    title=row["title"],
                    description=row["description"] or "",
                    location=row["location"] or "",
                    characters_involved=json.loads(row["characters_involved"]) if row["characters_involved"] else [],
                    importance=row["importance"],
                    event_type=row["event_type"],
                    chapter_id=row["chapter_id"],
                    source_material_ids=json.loads(row["source_material_ids"]) if row["source_material_ids"] else []
                )
                for row in rows
            ]

    # ==================== 审查指标 ====================

    def add_review_metrics(self, metrics: ReviewMetricsMeta) -> bool:
        """添加审查指标"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO review_metrics
                    (id, chapter_id, review_time, overall_score,
                     dimension_scores, issues, suggestions)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    metrics.id,
                    metrics.chapter_id,
                    metrics.review_time,
                    metrics.overall_score,
                    json.dumps(metrics.dimension_scores, ensure_ascii=False),
                    json.dumps(metrics.issues, ensure_ascii=False),
                    json.dumps(metrics.suggestions, ensure_ascii=False)
                ))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"添加审查指标失败: {e}")
                return False

    def get_review_metrics(self, chapter_id: str) -> Optional[ReviewMetricsMeta]:
        """获取章节审查指标"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM review_metrics WHERE chapter_id = ? ORDER BY review_time DESC LIMIT 1",
                (chapter_id,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            return ReviewMetricsMeta(
                id=row["id"],
                chapter_id=row["chapter_id"],
                review_time=row["review_time"],
                overall_score=row["overall_score"],
                dimension_scores=json.loads(row["dimension_scores"]) if row["dimension_scores"] else {},
                issues=json.loads(row["issues"]) if row["issues"] else [],
                suggestions=json.loads(row["suggestions"]) if row["suggestions"] else []
            )

    def get_quality_trend(self, last_n_chapters: int = 10) -> Dict[str, Any]:
        """获取质量趋势"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT chapter_id, overall_score, dimension_scores, review_time
                FROM review_metrics
                ORDER BY review_time DESC
                LIMIT ?
            """, (last_n_chapters,))
            rows = cursor.fetchall()

            if not rows:
                return {"trend": [], "average_score": 0.0}

            scores = [row["overall_score"] for row in rows]
            return {
                "trend": [
                    {
                        "chapter_id": row["chapter_id"],
                        "score": row["overall_score"],
                        "time": row["review_time"]
                    }
                    for row in reversed(rows)
                ],
                "average_score": sum(scores) / len(scores),
                "latest_score": scores[0]
            }

    # ==================== 统计信息 ====================

    def get_stats(self) -> Dict[str, Any]:
        """获取数据库统计信息"""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            stats = {}

            # 实体统计
            cursor.execute("SELECT type, COUNT(*) FROM entities GROUP BY type")
            stats["entities"] = {row[0]: row[1] for row in cursor.fetchall()}

            # 关系统计
            cursor.execute("SELECT relation_type, COUNT(*) FROM relationships GROUP BY relation_type")
            stats["relationships"] = {row[0]: row[1] for row in cursor.fetchall()}

            # 时间线事件统计
            cursor.execute("SELECT event_type, COUNT(*) FROM timeline_events GROUP BY event_type")
            stats["timeline_events"] = {row[0]: row[1] for row in cursor.fetchall()}

            # 审查次数
            cursor.execute("SELECT COUNT(*) FROM review_metrics")
            stats["review_count"] = cursor.fetchone()[0]

            return stats
