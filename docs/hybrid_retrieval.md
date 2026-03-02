# 混合检索架构实现文档

## 概述

将biography_writer的向量检索升级为混合检索架构，参考webnovel-writer的rag_adapter.py实现。

## 架构组成

### 1. BM25检索 (BM25Index)
- **文件**: `src/layers/data_ingestion.py`
- **类**: `BM25Index`
- **功能**:
  - 建立倒排索引 (`bm25_index`表)
  - 支持中文分词（2-4字词组）和英文单词
  - 实现标准BM25评分公式

**BM25公式**:
```
score = IDF * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_length / avg_doc_length))
IDF = log((N - df + 0.5) / (df + 0.5) + 1)
```

### 2. RRF融合 (RRFusion)
- **类**: `RRFusion`
- **算法**: Reciprocal Rank Fusion
- **公式**:
```python
score = Σ(1.0 / (k + rank))  # k默认取60
```
- **特点**: 无参数融合，对向量检索和BM25检索结果进行加权融合

### 3. Reranker重排序
- **类**: `Reranker`
- **支持**:
  - SiliconFlow API (默认): `BAAI/bge-reranker-v2-m3`
  - 本地向量相似度回退

### 4. 父子索引结构
- **数据库表扩展**:
  - `parent_id`: 父块ID（用于关联）
  - `chunk_type`: 块类型 (`summary`/`scene`)
- **功能**:
  - 摘要向量（父）关联场景向量（子）
  - 支持层级检索 (`search_with_parent_backtrack`)

## 配置项

在 `src/config.py` 中新增 `HybridRetrievalConfig`:

```python
class HybridRetrievalConfig(BaseSettings):
    rrf_k: int = 60                    # RRF融合参数
    vector_top_k: int = 20             # 向量检索召回数
    bm25_top_k: int = 20               # BM25检索召回数
    rerank_top_n: int = 10             # 最终返回结果数
    bm25_k1: float = 1.5               # BM25词频饱和度
    bm25_b: float = 0.75               # BM25长度归一化
    enable_rerank: bool = True         # 是否启用重排序
    rerank_provider: str = "siliconflow"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    enable_parent_child: bool = True   # 是否启用父子索引
```

## 使用方式

### 基础混合检索
```python
from src.layers.data_ingestion import DataIngestionLayer

layer = DataIngestionLayer()
results = await layer.retriever.retrieve(
    query="张三的童年",
    n_results=10,
    enable_rerank=True
)
```

### 带父块回溯的检索
```python
results = await layer.retriever.retrieve(
    query="张三的童年",
    n_results=10,
    use_parent_backtrack=True
)
# 返回: [父块(summary), 子块1(scene), 子块2(scene), ...]
```

### 为章节检索素材
```python
materials = await layer.retrieve_for_chapter(
    chapter_title="第一章：童年",
    chapter_summary="讲述张三的童年生活...",
    time_period="1980-1990",
    n_results=10,
    use_hybrid=True,
    use_parent_backtrack=False
)
```

## 数据库表结构

### materials表（扩展）
```sql
CREATE TABLE materials (
    id TEXT PRIMARY KEY,
    source_file TEXT,
    content TEXT,
    chunk_index INTEGER,
    topics TEXT,
    time_refs TEXT,
    entities TEXT,
    content_hash TEXT,
    embedding BLOB,
    parent_id TEXT,              -- 新增：父块ID
    chunk_type TEXT DEFAULT 'scene',  -- 新增：块类型
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### bm25_index表（新增）
```sql
CREATE TABLE bm25_index (
    term TEXT,
    material_id TEXT,
    tf REAL,
    PRIMARY KEY (term, material_id)
);
```

### doc_stats表（新增）
```sql
CREATE TABLE doc_stats (
    material_id TEXT PRIMARY KEY,
    doc_length INTEGER
);
```

## 依赖安装

```bash
pip install rank-bm25  # 已在requirements.txt中添加
```

## 向后兼容

- `VectorStore.search()` 方法保持向后兼容
- 同步接口 `retrieve_sync()` 可用
- 原有代码无需修改即可运行

## 性能优化

1. **并行检索**: 向量检索和BM25检索可并行执行
2. **索引优化**: 为parent_id、chunk_type、term添加索引
3. **分层召回**: 先RRF融合取Top-K，再Rerank精排

## 测试

核心逻辑测试通过:
- BM25索引构建与检索
- RRF融合算法验证
- 父子索引结构验证

## 参考

- 参考项目: `/Users/guoquan/work/Kimi/webnovel-writer/.claude/scripts/data_modules/rag_adapter.py`
