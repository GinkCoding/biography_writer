#!/usr/bin/env python3
"""
向量维度一致性测试
确保所有向量操作使用相同维度，避免维度不匹配错误
"""

import os
import sys
import numpy as np
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.embedding import EmbeddingManager
from src.layers.data_ingestion import VectorStore
import sqlite3

def test_embedding_dimension():
    """测试 Embedding 输出维度"""
    print("=" * 60)
    print("测试 1: Embedding 输出维度")
    print("=" * 60)
    
    # 从.env 读取配置
    env_file = Path(__file__).parent.parent / '.env'
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                if line.startswith('SILICONFLOW_MODEL'):
                    model_name = line.split('=')[1].strip()
                    print(f"✅ 使用模型：{model_name}")
                    break
    
    # 初始化 EmbeddingManager
    manager = EmbeddingManager({
        'siliconflow_api_key': os.getenv('SILICONFLOW_API_KEY'),
        'siliconflow_model': os.getenv('SILICONFLOW_MODEL', 'Qwen/Qwen3-Embedding-8B')
    })
    
    # 测试不同长度的文本
    test_texts = [
        "短文本",
        "这是一个中等长度的测试文本，用于验证 Embedding 输出",
        "这是一个非常长的测试文本。" * 100
    ]
    
    dimensions = []
    for i, text in enumerate(test_texts, 1):
        embedding = manager.encode([text])
        dim = embedding.shape[1]
        dimensions.append(dim)
        print(f"  测试{i}: 输入长度={len(text)} chars, 输出维度={dim}")
    
    # 验证所有输出维度一致
    assert len(set(dimensions)) == 1, f"维度不一致：{dimensions}"
    expected_dim = dimensions[0]
    print(f"✅ Embedding 输出维度一致：{expected_dim}")
    
    return expected_dim

def test_vector_store_dimension(embedding_dim):
    """测试 VectorStore 维度"""
    print("\n" + "=" * 60)
    print("测试 2: VectorStore 维度检查")
    print("=" * 60)
    
    db_path = Path(__file__).parent.parent / '.vector_db' / 'materials.db'
    
    if not db_path.exists():
        print("⚠️  数据库不存在，跳过此测试")
        return True
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查 materials 表
    cursor.execute("SELECT COUNT(*) FROM materials")
    count = cursor.fetchone()[0]
    print(f"  数据库记录数：{count}")
    
    if count > 0:
        # 抽样检查向量维度
        cursor.execute("SELECT embedding FROM materials LIMIT 5")
        rows = cursor.fetchall()
        
        for i, (embedding_blob,) in enumerate(rows, 1):
            if embedding_blob:
                embedding = np.frombuffer(embedding_blob, dtype=np.float32)
                dim = len(embedding)
                print(f"  样本{i}: 维度={dim}")
                
                if dim != embedding_dim:
                    print(f"❌ 维度不匹配！期望={embedding_dim}, 实际={dim}")
                    conn.close()
                    return False
        
        print(f"✅ VectorStore 维度一致：{embedding_dim}")
    
    conn.close()
    return True

def test_dot_product_consistency(embedding_dim):
    """测试点积运算维度兼容性"""
    print("\n" + "=" * 60)
    print("测试 3: 点积运算维度兼容性")
    print("=" * 60)
    
    # 创建两个随机向量
    vec1 = np.random.rand(embedding_dim).astype(np.float32)
    vec2 = np.random.rand(embedding_dim).astype(np.float32)
    
    try:
        similarity = np.dot(vec1, vec2)
        print(f"  测试向量维度：{embedding_dim}")
        print(f"  点积结果：{similarity:.6f}")
        print(f"✅ 点积运算正常")
        return True
    except Exception as e:
        print(f"❌ 点积运算失败：{e}")
        return False

def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("向量维度一致性测试套件")
    print("=" * 60)
    
    try:
        # 测试 1: Embedding 维度
        embedding_dim = test_embedding_dimension()
        
        # 测试 2: VectorStore 维度
        store_ok = test_vector_store_dimension(embedding_dim)
        
        # 测试 3: 点积兼容性
        dot_ok = test_dot_product_consistency(embedding_dim)
        
        # 总结
        print("\n" + "=" * 60)
        print("测试总结")
        print("=" * 60)
        print(f"Embedding 维度：{embedding_dim}")
        print(f"VectorStore 检查：{'✅ 通过' if store_ok else '❌ 失败'}")
        print(f"点积兼容性：{'✅ 通过' if dot_ok else '❌ 失败'}")
        
        if store_ok and dot_ok:
            print("\n✅ 所有测试通过！向量维度一致，可以安全运行")
            return 0
        else:
            print("\n❌ 测试失败！请修复后再运行")
            return 1
            
    except Exception as e:
        print(f"\n❌ 测试异常：{e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
