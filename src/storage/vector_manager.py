"""Vector Manager - 向量数据独立存储

管理 vectors.db 的读写操作：
- 章节摘要向量（父子索引）
- 场景向量
- 支持父子层级检索

从 data_ingestion.py 的 VectorStore 迁移并增强
"""

import sqlite3
import json
import logging
import hashlib
import numpy as np
from pathlib import Path
from typing import List, Optional, Dict, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import contextmanager

from src.config import settings
from src.embedding import get_embedding_manager

logger = logging.getLogger(__name__)


@dataclass
class VectorEntry:
    """向量条目"""
    id: str
    content: str  # 原始文本内容
    vector_type: str  # chapter_summary/scene/material/paragraph
    parent_id: Optional[str] = None  # 父级ID（用于层级结构）
    chapter_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SearchResult:
    """搜索结果"""
    entry: VectorEntry
    similarity: float
    rank: int


class VectorManager:
    """向量管理器 - 管理向量数据的独立存储"""

    # 向量类型定义
    TYPE_CHAPTER_SUMMARY = "chapter_summary"  # 章节摘要
    TYPE_SCENE = "scene"  # 场景
    TYPE_MATERIAL = "material"  # 原始素材
    TYPE_PARAGRAPH = "paragraph"  # 段落
    TYPE_CHARACTER_PROFILE = "character_profile"  # 人物画像

    def __init__(self, book_id: str, db_dir: Optional[Path] = None):
        self.book_id = book_id
        self.db_dir = Path(db_dir) if db_dir else Path(settings.paths.cache_dir)
        self.db_path = self.db_dir / f"{book_id}_vectors.db"

        # 初始化embedding管理器
        embedding_config = settings.embedding.get_embedding_manager_config()
        self.embedding_mgr = get_embedding_manager(embedding_config)

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
        """初始化向量数据库"""
        self.db_dir.mkdir(parents=True, exist_ok=True)

        with self._get_conn() as conn:
            cursor = conn.cursor()

            # 向量表 - 存储所有向量数据
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vectors (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    vector_type TEXT NOT NULL,
                    parent_id TEXT,
                    chapter_id TEXT,
                    metadata TEXT,  -- JSON dict
                    content_hash TEXT,  -- 用于去重
                    embedding BLOB,  -- 二进制向量数据
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 词频表 - 用于混合检索
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS word_freq (
                    word TEXT NOT NULL,
                    vector_id TEXT NOT NULL,
                    freq INTEGER DEFAULT 1,
                    PRIMARY KEY (word, vector_id),
                    FOREIGN KEY (vector_id) REFERENCES vectors(id)
                )
            """)

            # 层级索引表 - 支持父子检索
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vector_hierarchy (
                    parent_id TEXT NOT NULL,
                    child_id TEXT NOT NULL,
                    relation_type TEXT DEFAULT 'contains',
                    PRIMARY KEY (parent_id, child_id),
                    FOREIGN KEY (parent_id) REFERENCES vectors(id),
                    FOREIGN KEY (child_id) REFERENCES vectors(id)
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vectors_type ON vectors(vector_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vectors_chapter ON vectors(chapter_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vectors_parent ON vectors(parent_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_word_freq_word ON word_freq(word)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_hierarchy_parent ON vector_hierarchy(parent_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_hierarchy_child ON vector_hierarchy(child_id)")

            conn.commit()
            logger.info(f"初始化向量数据库: {self.db_path}")

    def _compute_content_hash(self, content: str) -> str:
        """计算内容哈希，用于去重"""
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _extract_keywords(self, text: str) -> Dict[str, int]:
        """提取关键词及频率"""
        import re
        words = re.findall(r'[\u4e00-\u9fa5]{2,4}', text)
        freq = {}
        for w in words:
            if len(w) >= 2:
                freq[w] = freq.get(w, 0) + 1
        return freq

    def add_entry(
        self,
        entry: VectorEntry,
        generate_embedding: bool = True
    ) -> bool:
        """
        添加向量条目

        Args:
            entry: 向量条目
            generate_embedding: 是否生成向量嵌入
        """
        # 检查是否已存在（基于内容哈希）
        content_hash = self._compute_content_hash(entry.content)

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM vectors WHERE content_hash = ?",
                (content_hash,)
            )
            if cursor.fetchone():
                logger.debug(f"内容已存在，跳过: {entry.id}")
                return False

        # 生成向量嵌入
        embedding_blob = None
        if generate_embedding:
            try:
                embedding = self.embedding_mgr.encode([entry.content])[0]
                embedding_blob = embedding.tobytes()
            except Exception as e:
                logger.error(f"生成向量嵌入失败: {e}")
                # 继续存储，但不带向量

        # 存储到数据库
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO vectors
                    (id, content, vector_type, parent_id, chapter_id, metadata, content_hash, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry.id,
                    entry.content,
                    entry.vector_type,
                    entry.parent_id,
                    entry.chapter_id,
                    json.dumps(entry.metadata, ensure_ascii=False),
                    content_hash,
                    embedding_blob
                ))

                # 提取并存储关键词（用于混合检索）
                keywords = self._extract_keywords(entry.content)
                for word, freq in keywords.items():
                    cursor.execute("""
                        INSERT OR REPLACE INTO word_freq (word, vector_id, freq)
                        VALUES (?, ?, ?)
                    """, (word, entry.id, freq))

                # 如果有父级，建立层级关系
                if entry.parent_id:
                    cursor.execute("""
                        INSERT OR REPLACE INTO vector_hierarchy (parent_id, child_id)
                        VALUES (?, ?)
                    """, (entry.parent_id, entry.id))

                conn.commit()
                logger.debug(f"添加向量条目: {entry.id} ({entry.vector_type})")
                return True

            except Exception as e:
                logger.error(f"添加向量条目失败: {e}")
                return False

    def add_entries_batch(
        self,
        entries: List[VectorEntry],
        generate_embeddings: bool = True
    ) -> int:
        """批量添加向量条目"""
        if not entries:
            return 0

        # 批量生成嵌入
        embeddings = None
        if generate_embeddings:
            try:
                contents = [e.content for e in entries]
                embeddings = self.embedding_mgr.encode(contents)
            except Exception as e:
                logger.error(f"批量生成向量嵌入失败: {e}")

        added_count = 0
        with self._get_conn() as conn:
            cursor = conn.cursor()

            for i, entry in enumerate(entries):
                # 检查是否已存在
                content_hash = self._compute_content_hash(entry.content)
                cursor.execute(
                    "SELECT id FROM vectors WHERE content_hash = ?",
                    (content_hash,)
                )
                if cursor.fetchone():
                    continue

                # 获取嵌入
                embedding_blob = None
                if embeddings is not None:
                    embedding_blob = embeddings[i].tobytes()

                try:
                    cursor.execute("""
                        INSERT INTO vectors
                        (id, content, vector_type, parent_id, chapter_id, metadata, content_hash, embedding)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        entry.id,
                        entry.content,
                        entry.vector_type,
                        entry.parent_id,
                        entry.chapter_id,
                        json.dumps(entry.metadata, ensure_ascii=False),
                        content_hash,
                        embedding_blob
                    ))

                    # 存储关键词
                    keywords = self._extract_keywords(entry.content)
                    for word, freq in keywords.items():
                        cursor.execute("""
                            INSERT OR REPLACE INTO word_freq (word, vector_id, freq)
                            VALUES (?, ?, ?)
                        """, (word, entry.id, freq))

                    # 建立层级关系
                    if entry.parent_id:
                        cursor.execute("""
                            INSERT OR REPLACE INTO vector_hierarchy (parent_id, child_id)
                            VALUES (?, ?)
                        """, (entry.parent_id, entry.id))

                    added_count += 1

                except Exception as e:
                    logger.error(f"添加条目 {entry.id} 失败: {e}")

            conn.commit()

        logger.info(f"批量添加 {added_count}/{len(entries)} 个向量条目")
        return added_count

    def search(
        self,
        query: str,
        vector_type: Optional[str] = None,
        n_results: int = 10,
        min_similarity: float = 0.5
    ) -> List[SearchResult]:
        """
        语义检索 - 基于向量相似度

        Args:
            query: 查询文本
            vector_type: 限制向量类型
            n_results: 返回结果数量
            min_similarity: 最小相似度阈值

        Returns:
            搜索结果列表
        """
        # 生成查询向量
        try:
            query_embedding = self.embedding_mgr.encode_query(query)
        except Exception as e:
            logger.error(f"生成查询向量失败: {e}")
            return self._keyword_search(query, vector_type, n_results)

        with self._get_conn() as conn:
            cursor = conn.cursor()

            # 构建查询
            sql = "SELECT * FROM vectors WHERE embedding IS NOT NULL"
            params = []
            if vector_type:
                sql += " AND vector_type = ?"
                params.append(vector_type)

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            if not rows:
                logger.warning("数据库中没有向量嵌入，回退到关键词检索")
                return self._keyword_search(query, vector_type, n_results)

            # 计算相似度
            scored_results = []
            for row in rows:
                embedding_bytes = row["embedding"]
                if not embedding_bytes:
                    continue

                doc_embedding = np.frombuffer(embedding_bytes, dtype=np.float32)

                # 计算余弦相似度（向量已归一化）
                similarity = np.dot(query_embedding, doc_embedding)

                if similarity >= min_similarity:
                    entry = VectorEntry(
                        id=row["id"],
                        content=row["content"],
                        vector_type=row["vector_type"],
                        parent_id=row["parent_id"],
                        chapter_id=row["chapter_id"],
                        metadata=json.loads(row["metadata"]) if row["metadata"] else {}
                    )
                    scored_results.append((entry, float(similarity)))

        # 按相似度排序
        scored_results.sort(key=lambda x: x[1], reverse=True)

        # 构建结果
        results = []
        for rank, (entry, similarity) in enumerate(scored_results[:n_results], 1):
            results.append(SearchResult(entry=entry, similarity=similarity, rank=rank))

        return results

    def _keyword_search(
        self,
        query: str,
        vector_type: Optional[str] = None,
        n_results: int = 10
    ) -> List[SearchResult]:
        """关键词检索（回退方案）"""
        import re

        query_keywords = set(re.findall(r'[\u4e00-\u9fa5]{2,4}', query))

        with self._get_conn() as conn:
            cursor = conn.cursor()

            if query_keywords:
                placeholders = ','.join(['?'] * len(query_keywords))
                sql = f"""
                    SELECT DISTINCT v.*, SUM(wf.freq) as keyword_score
                    FROM vectors v
                    JOIN word_freq wf ON v.id = wf.vector_id
                    WHERE wf.word IN ({placeholders})
                """
                params = list(query_keywords)

                if vector_type:
                    sql += " AND v.vector_type = ?"
                    params.append(vector_type)

                sql += f"""
                    GROUP BY v.id
                    ORDER BY keyword_score DESC
                    LIMIT {n_results * 2}
                """
                cursor.execute(sql, params)
            else:
                sql = "SELECT * FROM vectors LIMIT ?"
                params = (n_results * 2,)
                if vector_type:
                    sql = "SELECT * FROM vectors WHERE vector_type = ? LIMIT ?"
                    params = (vector_type, n_results * 2)
                cursor.execute(sql, params)

            rows = cursor.fetchall()

            results = []
            for rank, row in enumerate(rows[:n_results], 1):
                entry = VectorEntry(
                    id=row["id"],
                    content=row["content"],
                    vector_type=row["vector_type"],
                    parent_id=row["parent_id"],
                    chapter_id=row["chapter_id"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {}
                )
                # 关键词检索给固定分数
                results.append(SearchResult(entry=entry, similarity=0.3, rank=rank))

            return results

    def search_with_parent(
        self,
        query: str,
        parent_id: str,
        n_results: int = 5
    ) -> List[SearchResult]:
        """
        在指定父级下搜索子项

        Args:
            query: 查询文本
            parent_id: 父级ID
            n_results: 返回结果数量
        """
        # 获取所有子项ID
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT child_id FROM vector_hierarchy WHERE parent_id = ?",
                (parent_id,)
            )
            child_ids = [row[0] for row in cursor.fetchall()]

        if not child_ids:
            return []

        # 生成查询向量
        try:
            query_embedding = self.embedding_mgr.encode_query(query)
        except Exception as e:
            logger.error(f"生成查询向量失败: {e}")
            return []

        # 在子项中搜索
        with self._get_conn() as conn:
            cursor = conn.cursor()
            placeholders = ','.join(['?'] * len(child_ids))
            cursor.execute(f"""
                SELECT * FROM vectors
                WHERE id IN ({placeholders}) AND embedding IS NOT NULL
            """, child_ids)
            rows = cursor.fetchall()

            scored_results = []
            for row in rows:
                embedding_bytes = row["embedding"]
                if not embedding_bytes:
                    continue

                doc_embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
                similarity = np.dot(query_embedding, doc_embedding)

                entry = VectorEntry(
                    id=row["id"],
                    content=row["content"],
                    vector_type=row["vector_type"],
                    parent_id=row["parent_id"],
                    chapter_id=row["chapter_id"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {}
                )
                scored_results.append((entry, float(similarity)))

        scored_results.sort(key=lambda x: x[1], reverse=True)

        results = []
        for rank, (entry, similarity) in enumerate(scored_results[:n_results], 1):
            results.append(SearchResult(entry=entry, similarity=similarity, rank=rank))

        return results

    def get_children(self, parent_id: str) -> List[VectorEntry]:
        """获取父级的所有子项"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT v.* FROM vectors v
                JOIN vector_hierarchy h ON v.id = h.child_id
                WHERE h.parent_id = ?
            """, (parent_id,))
            rows = cursor.fetchall()

            return [
                VectorEntry(
                    id=row["id"],
                    content=row["content"],
                    vector_type=row["vector_type"],
                    parent_id=row["parent_id"],
                    chapter_id=row["chapter_id"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {}
                )
                for row in rows
            ]

    def get_by_chapter(self, chapter_id: str, vector_type: Optional[str] = None) -> List[VectorEntry]:
        """获取指定章节的所有向量条目"""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            if vector_type:
                cursor.execute(
                    "SELECT * FROM vectors WHERE chapter_id = ? AND vector_type = ?",
                    (chapter_id, vector_type)
                )
            else:
                cursor.execute(
                    "SELECT * FROM vectors WHERE chapter_id = ?",
                    (chapter_id,)
                )
            rows = cursor.fetchall()

            return [
                VectorEntry(
                    id=row["id"],
                    content=row["content"],
                    vector_type=row["vector_type"],
                    parent_id=row["parent_id"],
                    chapter_id=row["chapter_id"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {}
                )
                for row in rows
            ]

    def get_entry(self, entry_id: str) -> Optional[VectorEntry]:
        """获取单个向量条目"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vectors WHERE id = ?", (entry_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return VectorEntry(
                id=row["id"],
                content=row["content"],
                vector_type=row["vector_type"],
                parent_id=row["parent_id"],
                chapter_id=row["chapter_id"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {}
            )

    def delete_entry(self, entry_id: str) -> bool:
        """删除向量条目"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                # 删除层级关系
                cursor.execute(
                    "DELETE FROM vector_hierarchy WHERE parent_id = ? OR child_id = ?",
                    (entry_id, entry_id)
                )
                # 删除词频记录
                cursor.execute("DELETE FROM word_freq WHERE vector_id = ?", (entry_id,))
                # 删除向量条目
                cursor.execute("DELETE FROM vectors WHERE id = ?", (entry_id,))
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"删除向量条目失败: {e}")
                return False

    def clear(self):
        """清空所有向量数据"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM vector_hierarchy")
            cursor.execute("DELETE FROM word_freq")
            cursor.execute("DELETE FROM vectors")
            conn.commit()
            logger.info("清空向量数据库")

    def get_stats(self) -> Dict[str, Any]:
        """获取向量数据库统计信息"""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            stats = {}

            # 按类型统计
            cursor.execute("SELECT vector_type, COUNT(*) FROM vectors GROUP BY vector_type")
            stats["by_type"] = {row[0]: row[1] for row in cursor.fetchall()}

            # 总数
            cursor.execute("SELECT COUNT(*) FROM vectors")
            stats["total"] = cursor.fetchone()[0]

            # 有向量的条目数
            cursor.execute("SELECT COUNT(*) FROM vectors WHERE embedding IS NOT NULL")
            stats["with_embedding"] = cursor.fetchone()[0]

            # 层级关系数
            cursor.execute("SELECT COUNT(*) FROM vector_hierarchy")
            stats["hierarchy_relations"] = cursor.fetchone()[0]

            return stats
