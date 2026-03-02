"""向量维度一致性测试。"""

from pathlib import Path
import sqlite3

import numpy as np
import pytest


def test_embedding_dimension(embedding_dim):
    """Embedding 维度应为正整数。"""
    assert isinstance(embedding_dim, int)
    assert embedding_dim > 0


def test_vector_store_dimension(embedding_dim):
    """数据库中持久化向量的维度应与 embedding_dim 一致。"""
    db_path = Path(__file__).parent.parent / ".vector_db" / "materials.db"
    if not db_path.exists():
        pytest.skip("向量数据库不存在，跳过")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT embedding FROM materials WHERE embedding IS NOT NULL LIMIT 10")
        rows = cursor.fetchall()
        if not rows:
            pytest.skip("数据库中没有 embedding 样本，跳过")

        for (embedding_blob,) in rows:
            vector = np.frombuffer(embedding_blob, dtype=np.float32)
            assert len(vector) == embedding_dim
    finally:
        conn.close()


def test_dot_product_consistency(embedding_dim):
    """同维度向量应可正常执行点积。"""
    vec1 = np.random.rand(embedding_dim).astype(np.float32)
    vec2 = np.random.rand(embedding_dim).astype(np.float32)
    similarity = float(np.dot(vec1, vec2))
    assert similarity >= 0.0
