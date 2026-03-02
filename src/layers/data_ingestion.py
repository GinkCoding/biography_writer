"""第一层：数据接入与解析层 (Data Ingestion)"""
import re
import sqlite3
import json
import hashlib
import math
import numpy as np
from pathlib import Path
from typing import List, Optional, Dict, Tuple, Any
from dataclasses import dataclass, field
from collections import Counter
from loguru import logger

from src.config import settings
from src.models import InterviewMaterial
from src.utils import extract_time_expressions, extract_entities, generate_id
from src.embedding import get_embedding_manager

# 导入新的三层存储架构
from src.storage.vector_manager import VectorManager, VectorEntry


@dataclass
class CleanedText:
    """清洗后的文本"""
    original: str
    cleaned: str
    removed_noise: List[str]


@dataclass
class SearchResult:
    """搜索结果"""
    material: InterviewMaterial
    score: float
    source: str  # "vector" | "bm25" | "hybrid" | "rerank"
    rank: int = 0  # 在对应检索中的排名


@dataclass
class HybridSearchResult:
    """混合检索结果"""
    material: InterviewMaterial
    rrf_score: float
    vector_score: float = 0.0
    bm25_score: float = 0.0
    rerank_score: float = 0.0
    vector_rank: int = -1
    bm25_rank: int = -1
    final_rank: int = 0


class DataCleaner:
    """数据清洗器"""
    
    # 口语化填充词和语气词（更精细的控制）
    FILLER_WORDS = [
        r"(?<![\u4e00-\u9fa5])(那个|这个|就是)(?![\u4e00-\u9fa5])",  # 单独的填充词
        r"^(嗯|啊|呃|哦|哈){1,}",  # 句首的语气词
    ]
    
    # 保留重要的时间标记和注释
    PRESERVE_PATTERNS = [
        r"\(\d{4}[^)]*\)",  # 包含年份的括号内容
        r"【[^】]*】",  # 方括号注释（通常是重要说明）
        r"\(.*?采访.*?\)",  # 采访场景说明
        r"\(.*?背景.*?\)",  # 背景说明
    ]
    
    def clean(self, text: str) -> CleanedText:
        """清洗文本"""
        removed = []
        cleaned = text
        
        # 先保存需要保留的内容
        preserved = {}
        for i, pattern in enumerate(self.PRESERVE_PATTERNS):
            matches = re.findall(pattern, cleaned)
            for j, match in enumerate(matches):
                placeholder = f"__PRESERVE_{i}_{j}__"
                preserved[placeholder] = match
                cleaned = cleaned.replace(match, placeholder, 1)
        
        # 1. 移除语气词和填充词
        for pattern in self.FILLER_WORDS:
            matches = re.findall(pattern, cleaned)
            if matches:
                removed.extend(matches[:3])  # 只记录前3个
                cleaned = re.sub(pattern, "", cleaned)
        
        # 2. 合并重复标点
        cleaned = re.sub(r'[。]{2,}', '。', cleaned)
        cleaned = re.sub(r'[！]{2,}', '！', cleaned)
        cleaned = re.sub(r'[,，]{2,}', '，', cleaned)
        
        # 3. 规范化空白
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = re.sub(r' +', ' ', cleaned)
        
        # 4. 段落分割优化（保留采访问答格式）
        cleaned = re.sub(r'([。！？])\s*(?=[Q|A|问|答|采访者|受访者])', r"\1\n", cleaned)
        
        # 5. 恢复保留的内容
        for placeholder, original in preserved.items():
            cleaned = cleaned.replace(placeholder, original)
        
        return CleanedText(
            original=text,
            cleaned=cleaned.strip(),
            removed_noise=removed
        )


class TopicSegmenter:
    """话题切分器 - 按话题或时间段切分文本"""
    
    # 话题转换标记（增强版）
    TOPIC_MARKERS = [
        r"接下来",
        r"说到",
        r"另外",
        r"还有",
        r"再说",
        r"后来",
        r"那时候",
        r"那段时间",
        r"再后来",
        r"再之后",
        r"又过了",
        r"转机",
        r"开始",
        r"第一次",
    ]
    
    # 时间标记（用于识别新话题）
    TIME_MARKERS = [
        r"\d{4}年",
        r"\d{2}年",
        r"(小学|初中|高中|大学)时",
        r"(出来工作|创业|结婚)后",
    ]
    
    def segment(self, text: str) -> List[dict]:
        """将文本切分成话题块"""
        segments = []
        
        # 先按段落分割
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
        
        current_segment = []
        current_topics = []
        current_time = ""
        
        for para in paragraphs:
            # 检查是否是新话题的开始
            is_new_topic = False
            
            # 检查话题标记
            if any(re.search(marker, para) for marker in self.TOPIC_MARKERS):
                is_new_topic = True
            
            # 检查时间标记（如果与前一个段落的时间不同）
            time_match = re.search(r'(\d{4})年', para)
            if time_match:
                new_time = time_match.group(1)
                if current_time and new_time != current_time:
                    is_new_topic = True
                current_time = new_time
            
            if is_new_topic and current_segment:
                # 保存当前段落组
                segment_text = '\n'.join(current_segment)
                segments.append({
                    "text": segment_text,
                    "topics": list(set(current_topics)),
                    "char_count": len(segment_text),
                    "time_period": current_time
                })
                current_segment = []
                current_topics = []
            
            current_segment.append(para)
            
            # 提取话题关键词
            topics = self._extract_topics(para)
            current_topics.extend(topics)
        
        # 保存最后一段
        if current_segment:
            segment_text = '\n'.join(current_segment)
            segments.append({
                "text": segment_text,
                "topics": list(set(current_topics)),
                "char_count": len(segment_text),
                "time_period": current_time
            })
        
        return segments
    
    def _extract_topics(self, text: str) -> List[str]:
        """提取话题关键词（增强版）"""
        topics = []
        
        topic_keywords = {
            "童年": ["小时候", "童年", "小学", "家乡", "出生", "老家"],
            "求学": ["大学", "学校", "读书", "学习", "老师", "同学", "毕业"],
            "工作": ["工作", "上班", "公司", "创业", "事业", "职位", "工厂", "打工"],
            "家庭": ["父母", "父亲", "母亲", "妻子", "丈夫", "孩子", "结婚", "老婆", "儿子"],
            "挫折": ["困难", "失败", "挫折", "低谷", "困境", "危机", "破产"],
            "转折": ["决定", "选择", "转折", "改变", "机会", "下海", "去深圳"],
            "时代": ["改革开放", "文革", "那时候", "当时", "年代"],
        }
        
        for topic, keywords in topic_keywords.items():
            if any(kw in text for kw in keywords):
                topics.append(topic)
        
        return topics


def split_text_biography(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[str]:
    """
    传记专用文本切分 - 优先保持事件完整性
    
    Args:
        text: 输入文本
        chunk_size: 目标块大小（字符数）- 增大到1000
        chunk_overlap: 重叠区域大小 - 增大到200
    
    Returns:
        切分后的文本块列表
    """
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    
    # 首先按自然段落分割
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    
    current_chunk = []
    current_size = 0
    
    for para in paragraphs:
        para_len = len(para)
        
        # 如果当前段落本身就是一个大块，需要进一步切分
        if para_len > chunk_size:
            # 先保存当前累积的内容
            if current_chunk:
                chunks.append('\n'.join(current_chunk))
                # 保留重叠内容
                overlap_text = '\n'.join(current_chunk)[-chunk_overlap:]
                current_chunk = [overlap_text] if overlap_text else []
                current_size = len(overlap_text)
            
            # 按句子切分长段落
            sentences = re.split(r'([。！？])', para)
            for i in range(0, len(sentences) - 1, 2):
                sent = sentences[i] + (sentences[i+1] if i+1 < len(sentences) else '')
                
                if current_size + len(sent) > chunk_size and current_chunk:
                    chunks.append('\n'.join(current_chunk))
                    overlap_text = '\n'.join(current_chunk)[-chunk_overlap:]
                    current_chunk = [overlap_text, sent] if overlap_text else [sent]
                    current_size = len(current_chunk[0]) + len(sent)
                else:
                    current_chunk.append(sent)
                    current_size += len(sent)
        
        # 正常段落处理
        elif current_size + para_len > chunk_size:
            # 保存当前块
            chunks.append('\n'.join(current_chunk))
            # 开始新块，保留重叠
            overlap_text = '\n'.join(current_chunk)[-chunk_overlap:] if current_chunk else ""
            current_chunk = [overlap_text, para] if overlap_text else [para]
            current_size = len(overlap_text) + para_len
        else:
            current_chunk.append(para)
            current_size += para_len
    
    # 保存最后一块
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    return chunks


class BM25Index:
    """BM25倒排索引 - 支持关键词检索"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.k1 = settings.hybrid_retrieval.bm25_k1
        self.b = settings.hybrid_retrieval.bm25_b
        self._avg_doc_length = None
        self._total_docs = None

    def _tokenize(self, text: str) -> List[str]:
        """简单分词（中文按字符，英文按单词）"""
        # 中文字符（2字以上词组）
        chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,4}', text)
        # 英文单词
        english_words = re.findall(r'[a-zA-Z]+', text.lower())
        return chinese_words + english_words

    def update_index(self, cursor, material_id: str, content: str):
        """更新BM25索引"""
        # 删除旧索引
        cursor.execute("DELETE FROM bm25_index WHERE material_id = ?", (material_id,))
        cursor.execute("DELETE FROM doc_stats WHERE material_id = ?", (material_id,))

        # 分词
        tokens = self._tokenize(content)
        doc_length = len(tokens)

        if doc_length == 0:
            return

        # 计算词频
        tf_counter = Counter(tokens)

        # 插入倒排索引
        for term, count in tf_counter.items():
            tf = count / doc_length
            cursor.execute("""
                INSERT INTO bm25_index (term, material_id, tf)
                VALUES (?, ?, ?)
            """, (term, material_id, tf))

        # 更新文档统计
        cursor.execute("""
            INSERT INTO doc_stats (material_id, doc_length)
            VALUES (?, ?)
        """, (material_id, doc_length))

    def search(
        self,
        query: str,
        top_k: int = 20,
        exclude_ids: Optional[set] = None
    ) -> List[Tuple[str, float]]:
        """
        BM25检索

        Returns:
            [(material_id, score), ...] 按分数排序
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query_terms = self._tokenize(query)
        if not query_terms:
            conn.close()
            return []

        # 获取文档总数和平均长度
        cursor.execute("SELECT COUNT(*), AVG(doc_length) FROM doc_stats")
        row = cursor.fetchone()
        total_docs = row[0] or 1
        avg_doc_length = row[1] or 1

        # 计算每个文档的BM25分数
        doc_scores = {}

        for term in set(query_terms):
            # 获取包含该词的文档
            cursor.execute("""
                SELECT b.material_id, b.tf, d.doc_length
                FROM bm25_index b
                JOIN doc_stats d ON b.material_id = d.material_id
                WHERE b.term = ?
            """, (term,))

            docs_with_term = cursor.fetchall()
            df = len(docs_with_term)

            if df == 0:
                continue

            # IDF计算
            idf = math.log((total_docs - df + 0.5) / (df + 0.5) + 1)

            for material_id, tf, doc_length in docs_with_term:
                # 排除指定ID
                if exclude_ids and material_id in exclude_ids:
                    continue

                # BM25公式
                score = idf * (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * doc_length / avg_doc_length)
                )

                if material_id not in doc_scores:
                    doc_scores[material_id] = 0
                doc_scores[material_id] += score

        conn.close()

        # 按分数排序
        sorted_results = sorted(
            doc_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return sorted_results[:top_k]


class RRFusion:
    """Reciprocal Rank Fusion - 倒数排名融合"""

    def __init__(self, k: int = 60):
        self.k = k

    def fuse(
        self,
        vector_results: List[Tuple[str, float]],
        bm25_results: List[Tuple[str, float]],
        vector_weight: float = 1.0,
        bm25_weight: float = 1.0
    ) -> Dict[str, dict]:
        """
        RRF融合

        Args:
            vector_results: [(id, score), ...] 向量检索结果
            bm25_results: [(id, score), ...] BM25检索结果
            vector_weight: 向量检索权重
            bm25_weight: BM25检索权重

        Returns:
            {id: {"score": rrf_score, "vector_score": ..., "bm25_score": ..., "vector_rank": ..., "bm25_rank": ...}}
        """
        rrf_scores = {}

        # 处理向量检索结果
        for rank, (doc_id, score) in enumerate(vector_results):
            if doc_id not in rrf_scores:
                rrf_scores[doc_id] = {
                    "score": 0,
                    "vector_score": 0,
                    "bm25_score": 0,
                    "vector_rank": -1,
                    "bm25_rank": -1
                }
            rrf_scores[doc_id]["score"] += vector_weight * (1.0 / (self.k + rank + 1))
            rrf_scores[doc_id]["vector_score"] = score
            rrf_scores[doc_id]["vector_rank"] = rank

        # 处理BM25检索结果
        for rank, (doc_id, score) in enumerate(bm25_results):
            if doc_id not in rrf_scores:
                rrf_scores[doc_id] = {
                    "score": 0,
                    "vector_score": 0,
                    "bm25_score": 0,
                    "vector_rank": -1,
                    "bm25_rank": -1
                }
            rrf_scores[doc_id]["score"] += bm25_weight * (1.0 / (self.k + rank + 1))
            rrf_scores[doc_id]["bm25_score"] = score
            rrf_scores[doc_id]["bm25_rank"] = rank

        return rrf_scores


class Reranker:
    """重排序器 - 对初步检索结果进行精排"""

    def __init__(self):
        self.provider = settings.hybrid_retrieval.rerank_provider
        self.model = settings.hybrid_retrieval.rerank_model
        self.api_key = settings.embedding.siliconflow_api_key

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: int = 10
    ) -> List[Dict[str, Any]]:
        """
        对文档进行重排序

        Returns:
            [{"index": 原始索引, "relevance_score": 相关性分数}, ...]
        """
        if not documents:
            return []

        if self.provider == "siliconflow":
            return await self._rerank_siliconflow(query, documents, top_n)
        else:
            # 本地简化版重排序（使用向量相似度）
            return await self._rerank_local(query, documents, top_n)

    async def _rerank_siliconflow(
        self,
        query: str,
        documents: List[str],
        top_n: int
    ) -> List[Dict[str, Any]]:
        """使用SiliconFlow API进行重排序"""
        try:
            import aiohttp

            url = "https://api.siliconflow.cn/v1/rerank"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model,
                "query": query,
                "documents": documents,
                "top_n": top_n,
                "return_documents": False
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("results", [])
                    else:
                        logger.warning(f"Rerank API调用失败: {response.status}")
                        return []
        except Exception as e:
            logger.warning(f"Rerank调用失败: {e}")
            return []

    async def _rerank_local(
        self,
        query: str,
        documents: List[str],
        top_n: int
    ) -> List[Dict[str, Any]]:
        """本地简化版重排序"""
        try:
            embedding_mgr = get_embedding_manager(
                settings.embedding.get_embedding_manager_config()
            )

            # 编码查询和文档
            query_embedding = embedding_mgr.encode_query(query)
            doc_embeddings = embedding_mgr.encode(documents)

            # 计算相似度
            similarities = np.dot(doc_embeddings, query_embedding)

            # 排序
            indexed_scores = [(i, float(s)) for i, s in enumerate(similarities)]
            indexed_scores.sort(key=lambda x: x[1], reverse=True)

            return [
                {"index": idx, "relevance_score": score}
                for idx, score in indexed_scores[:top_n]
            ]
        except Exception as e:
            logger.warning(f"本地重排序失败: {e}")
            return [{"index": i, "relevance_score": 0.5} for i in range(min(top_n, len(documents)))]


class VectorStore:
    """向量数据库 - 支持真实语义检索

    注意: 此类现在作为 VectorManager 的包装器，保持向后兼容。
    新的代码建议直接使用 src.storage.vector_manager.VectorManager
    """

    def __init__(self, book_id: Optional[str] = None):
        # 优先使用新的 VectorManager
        if book_id:
            self._vector_manager = VectorManager(book_id)
            self.db_path = self._vector_manager.db_path
        else:
            # 向后兼容：使用旧的数据库路径
            self.db_path = Path(settings.paths.vector_db_dir) / "materials.db"
            self._vector_manager = None

        # 从配置获取embedding管理器
        embedding_config = settings.embedding.get_embedding_manager_config()
        self.embedding_mgr = get_embedding_manager(embedding_config)

        # 初始化混合检索组件
        self.bm25_index = BM25Index(self.db_path)
        self.rrf = RRFusion(k=settings.hybrid_retrieval.rrf_k)
        self.reranker = Reranker()

        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 素材表 - 增加embedding列和父子索引支持
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS materials (
                id TEXT PRIMARY KEY,
                source_file TEXT,
                content TEXT,
                chunk_index INTEGER,
                topics TEXT,
                time_refs TEXT,
                entities TEXT,
                content_hash TEXT,
                embedding BLOB,  -- 向量嵌入
                parent_id TEXT,  -- 父块ID（用于父子索引）
                chunk_type TEXT DEFAULT 'scene',  -- 块类型: summary/scene
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 词频统计表（用于关键词检索回退）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS word_freq (
                word TEXT,
                material_id TEXT,
                freq INTEGER,
                PRIMARY KEY (word, material_id)
            )
        ''')

        # BM25倒排索引表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bm25_index (
                term TEXT,
                material_id TEXT,
                tf REAL,
                PRIMARY KEY (term, material_id)
            )
        ''')

        # 文档统计表（用于BM25）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS doc_stats (
                material_id TEXT PRIMARY KEY,
                doc_length INTEGER
            )
        ''')

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_materials_parent ON materials(parent_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_materials_type ON materials(chunk_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bm25_term ON bm25_index(term)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_word_freq_word ON word_freq(word)")

        conn.commit()
        conn.close()
    
    def _compute_content_hash(self, content: str) -> str:
        """计算内容哈希，用于去重"""
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def _extract_keywords(self, text: str) -> Dict[str, int]:
        """提取关键词及频率"""
        words = re.findall(r'[\u4e00-\u9fa5]{2,4}', text)
        freq = {}
        for w in words:
            if len(w) >= 2:
                freq[w] = freq.get(w, 0) + 1
        return freq
    
    def add_materials(
        self,
        materials: List[InterviewMaterial],
        parent_id: Optional[str] = None,
        chunk_type: str = "scene"
    ):
        """
        添加素材到数据库（含向量嵌入和BM25索引）

        Args:
            materials: 素材列表
            parent_id: 父块ID（用于父子索引）
            chunk_type: 块类型（summary/scene）
        """
        if not materials:
            return

        # 如果使用了新的 VectorManager，使用新的存储方式
        if self._vector_manager:
            self._add_materials_new(materials, parent_id, chunk_type)
        else:
            self._add_materials_legacy(materials, parent_id, chunk_type)

    def _add_materials_new(
        self,
        materials: List[InterviewMaterial],
        parent_id: Optional[str] = None,
        chunk_type: str = "scene"
    ):
        """使用新的 VectorManager 添加素材"""
        entries = []
        for m in materials:
            entry = VectorEntry(
                id=m.id,
                content=m.content,
                vector_type=chunk_type,
                parent_id=parent_id,
                metadata={
                    "source_file": m.source_file,
                    "chunk_index": m.chunk_index,
                    "topics": m.topics,
                    "time_references": m.time_references,
                    "entities": m.entities,
                }
            )
            entries.append(entry)

        added = self._vector_manager.add_entries_batch(entries)
        if added > 0:
            logger.info(f"已向向量数据库添加 {added} 个素材块")

    def _add_materials_legacy(
        self,
        materials: List[InterviewMaterial],
        parent_id: Optional[str] = None,
        chunk_type: str = "scene"
    ):
        """向后兼容：使用旧的存储方式"""
        logger.info(f"正在为 {len(materials)} 个素材生成向量嵌入...")

        # 分批生成嵌入（每批 5 个，避免 API 限制）
        import numpy as np
        BATCH_SIZE = 5
        embeddings_list = []
        contents = [m.content for m in materials]
        
        logger.info(f"分 {len(contents) // BATCH_SIZE + 1} 批生成向量嵌入...")
        
        for i in range(0, len(contents), BATCH_SIZE):
            batch_contents = contents[i:i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            logger.debug(f"  第 {batch_num} 批：{len(batch_contents)} 个文本")
            
            try:
                batch_embeddings = self.embedding_mgr.encode(batch_contents)
                embeddings_list.append(batch_embeddings)
            except Exception as e:
                logger.error(f"第 {batch_num} 批生成失败：{e}")
                import numpy as np
                zero_embeddings = np.zeros((len(batch_contents), 768))
                embeddings_list.append(zero_embeddings)
        
        # 合并所有批次
        embeddings = np.vstack(embeddings_list) if embeddings_list else None

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        added_count = 0
        for i, m in enumerate(materials):
            # 检查是否已存在（基于内容哈希）
            content_hash = self._compute_content_hash(m.content)
            cursor.execute('SELECT id FROM materials WHERE content_hash = ?', (content_hash,))
            if cursor.fetchone():
                continue

            # 序列化embedding
            embedding_blob = None
            if embeddings is not None:
                embedding_blob = embeddings[i].tobytes()

            cursor.execute('''
                INSERT INTO materials
                (id, source_file, content, chunk_index, topics, time_refs, entities, content_hash, embedding, parent_id, chunk_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                m.id,
                m.source_file,
                m.content,
                m.chunk_index,
                json.dumps(m.topics, ensure_ascii=False),
                json.dumps(m.time_references, ensure_ascii=False),
                json.dumps(m.entities, ensure_ascii=False),
                content_hash,
                embedding_blob,
                parent_id,
                chunk_type
            ))

            # 提取并存储关键词（用于混合检索）
            keywords = self._extract_keywords(m.content)
            for word, freq in keywords.items():
                cursor.execute('''
                    INSERT OR REPLACE INTO word_freq (word, material_id, freq)
                    VALUES (?, ?, ?)
                ''', (word, m.id, freq))

            # 更新BM25索引
            try:
                self.bm25_index.update_index(cursor, m.id, m.content)
            except Exception as e:
                logger.warning(f"BM25索引更新失败 for {m.id}: {e}")

            added_count += 1

        conn.commit()
        conn.close()

        if added_count > 0:
            logger.info(f"已向数据库添加 {added_count} 个素材块（含向量嵌入和BM25索引）")
    
    def vector_search(
        self,
        query: str,
        top_k: int = 20,
        chunk_type: Optional[str] = None,
        parent_id: Optional[str] = None
    ) -> List[Tuple[str, float]]:
        """
        向量检索 - 基于余弦相似度

        Returns:
            [(material_id, similarity_score), ...] 按相似度排序
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 构建查询条件
        where_clause = "WHERE embedding IS NOT NULL"
        params = []
        if chunk_type:
            where_clause += " AND chunk_type = ?"
            params.append(chunk_type)
        if parent_id:
            where_clause += " AND parent_id = ?"
            params.append(parent_id)

        cursor.execute(f'''
            SELECT id, embedding
            FROM materials {where_clause}
        ''', params)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            logger.warning("数据库中没有向量嵌入")
            return []

        # 生成查询向量
        try:
            query_embedding = self.embedding_mgr.encode_query(query)
        except Exception as e:
            logger.error(f"生成查询向量失败: {e}")
            return []

        # 计算相似度
        scored_results = []
        for row in rows:
            material_id = row[0]
            embedding_bytes = row[1]
            if embedding_bytes:
                doc_embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
                # 计算余弦相似度（向量已归一化）
                similarity = np.dot(query_embedding, doc_embedding)
                scored_results.append((material_id, float(similarity)))

        # 按相似度排序
        scored_results.sort(key=lambda x: x[1], reverse=True)
        return scored_results[:top_k]

    def bm25_search(
        self,
        query: str,
        top_k: int = 20,
        chunk_type: Optional[str] = None
    ) -> List[Tuple[str, float]]:
        """
        BM25关键词检索

        Returns:
            [(material_id, bm25_score), ...] 按分数排序
        """
        # 先获取BM25分数
        results = self.bm25_index.search(query, top_k=top_k * 2)

        if not results:
            return []

        # 如果有过滤条件，需要进一步筛选
        if chunk_type:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            filtered_results = []
            for material_id, score in results:
                cursor.execute(
                    "SELECT 1 FROM materials WHERE id = ? AND chunk_type = ?",
                    (material_id, chunk_type)
                )
                if cursor.fetchone():
                    filtered_results.append((material_id, score))

            conn.close()
            return filtered_results[:top_k]

        return results[:top_k]

    async def hybrid_search(
        self,
        query: str,
        n_results: int = 10,
        chunk_type: Optional[str] = None,
        parent_id: Optional[str] = None,
        enable_rerank: bool = None,
        vector_weight: float = 1.0,
        bm25_weight: float = 1.0
    ) -> List[HybridSearchResult]:
        """
        混合检索：向量 + BM25 + RRF融合 + Rerank

        流程:
        1. 向量检索 top_k
        2. BM25检索 top_k
        3. RRF融合
        4. Rerank精排（可选）

        Args:
            query: 查询文本
            n_results: 返回结果数量
            chunk_type: 块类型过滤
            parent_id: 父块ID过滤
            enable_rerank: 是否启用重排序（默认从配置读取）
            vector_weight: 向量检索权重
            bm25_weight: BM25检索权重

        Returns:
            HybridSearchResult列表，按最终分数排序
        """
        if enable_rerank is None:
            enable_rerank = settings.hybrid_retrieval.enable_rerank

        vector_top_k = settings.hybrid_retrieval.vector_top_k
        bm25_top_k = settings.hybrid_retrieval.bm25_top_k
        rerank_top_n = max(n_results, settings.hybrid_retrieval.rerank_top_n)

        # 1. 并行执行向量检索和BM25检索
        vector_results = self.vector_search(
            query, top_k=vector_top_k, chunk_type=chunk_type, parent_id=parent_id
        )
        bm25_results = self.bm25_search(query, top_k=bm25_top_k, chunk_type=chunk_type)

        if not vector_results and not bm25_results:
            logger.warning("向量和BM25检索均未返回结果")
            return []

        # 2. RRF融合
        rrf_scores = self.rrf.fuse(
            vector_results, bm25_results,
            vector_weight=vector_weight,
            bm25_weight=bm25_weight
        )

        # 按RRF分数排序
        sorted_ids = sorted(
            rrf_scores.items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )[:rerank_top_n * 2]

        # 3. 获取完整文档内容
        material_ids = [doc_id for doc_id, _ in sorted_ids]
        materials_map = self._get_materials_by_ids(material_ids)

        # 构建初步结果
        candidates = []
        for doc_id, scores in sorted_ids:
            if doc_id in materials_map:
                candidates.append(HybridSearchResult(
                    material=materials_map[doc_id],
                    rrf_score=scores["score"],
                    vector_score=scores["vector_score"],
                    bm25_score=scores["bm25_score"],
                    vector_rank=scores["vector_rank"],
                    bm25_rank=scores["bm25_rank"]
                ))

        # 4. Rerank精排（可选）
        if enable_rerank and candidates:
            documents = [c.material.content for c in candidates]
            try:
                rerank_results = await self.reranker.rerank(
                    query, documents, top_n=min(n_results, len(documents))
                )

                # 更新分数
                for r in rerank_results:
                    idx = r.get("index", 0)
                    if 0 <= idx < len(candidates):
                        candidates[idx].rerank_score = r.get("relevance_score", 0)

                # 按rerank分数重新排序
                candidates.sort(key=lambda x: x.rerank_score, reverse=True)
            except Exception as e:
                logger.warning(f"Rerank失败: {e}，使用RRF结果")
                candidates.sort(key=lambda x: x.rrf_score, reverse=True)
        else:
            candidates.sort(key=lambda x: x.rrf_score, reverse=True)

        # 设置最终排名
        for i, c in enumerate(candidates[:n_results]):
            c.final_rank = i + 1

        return candidates[:n_results]

    def _get_materials_by_ids(self, material_ids: List[str]) -> Dict[str, InterviewMaterial]:
        """根据ID批量获取素材"""
        if not material_ids:
            return {}

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        placeholders = ','.join(['?'] * len(material_ids))
        cursor.execute(f'''
            SELECT id, source_file, content, chunk_index, topics, time_refs, entities
            FROM materials WHERE id IN ({placeholders})
        ''', material_ids)

        rows = cursor.fetchall()
        conn.close()

        materials = {}
        for row in rows:
            material = InterviewMaterial(
                id=row[0],
                source_file=row[1],
                content=row[2],
                chunk_index=row[3],
                topics=json.loads(row[4]) if row[4] else [],
                time_references=json.loads(row[5]) if row[5] else [],
                entities=json.loads(row[6]) if row[6] else [],
            )
            materials[row[0]] = material

        return materials

    def search(
        self,
        query: str,
        n_results: int = 10,
        filter_dict: Optional[dict] = None
    ) -> List[Tuple[InterviewMaterial, float]]:
        """
        语义检索 - 基于向量相似度（向后兼容）

        Returns:
            [(material, similarity_score), ...] 按相似度排序
        """
        import asyncio

        try:
            # 尝试使用混合检索
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果在异步上下文中，创建新任务
                results = asyncio.create_task(self.hybrid_search(
                    query, n_results=n_results, enable_rerank=False
                ))
                # 这里需要等待，但如果在运行中的loop会有问题
                # 所以回退到简单向量检索
                raise RuntimeError("在异步上下文中，请直接使用hybrid_search")
            else:
                results = loop.run_until_complete(self.hybrid_search(
                    query, n_results=n_results, enable_rerank=False
                ))
                return [(r.material, r.rrf_score) for r in results]
        except Exception as e:
            logger.warning(f"混合检索失败，回退到向量检索: {e}")

        # 回退到简单向量检索
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 获取所有带embedding的素材
        cursor.execute('''
            SELECT id, source_file, content, chunk_index, topics, time_refs, entities, embedding
            FROM materials WHERE embedding IS NOT NULL
        ''')
        rows = cursor.fetchall()

        if not rows:
            logger.warning("数据库中没有向量嵌入，回退到关键词检索")
            conn.close()
            return self._keyword_search(query, n_results)

        # 生成查询向量
        try:
            query_embedding = self.embedding_mgr.encode_query(query)
        except Exception as e:
            logger.error(f"生成查询向量失败: {e}")
            conn.close()
            return self._keyword_search(query, n_results)

        # 计算相似度
        scored_results = []
        for row in rows:
            embedding_bytes = row[7]
            if embedding_bytes:
                doc_embedding = np.frombuffer(embedding_bytes, dtype=np.float32)

                # 计算余弦相似度（向量已归一化）
                similarity = np.dot(query_embedding, doc_embedding)

                # 提取元数据
                material = InterviewMaterial(
                    id=row[0],
                    source_file=row[1],
                    content=row[2],
                    chunk_index=row[3],
                    topics=json.loads(row[4]) if row[4] else [],
                    time_references=json.loads(row[5]) if row[5] else [],
                    entities=json.loads(row[6]) if row[6] else [],
                )

                scored_results.append((material, float(similarity)))

        conn.close()

        # 按相似度排序
        scored_results.sort(key=lambda x: x[1], reverse=True)

        # 返回前n个，相似度>0.5的
        return [(m, s) for m, s in scored_results[:n_results] if s > 0.5]
    
    def _keyword_search(self, query: str, n_results: int) -> List[Tuple[InterviewMaterial, float]]:
        """关键词检索（回退方案）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 提取查询关键词
        query_keywords = set(re.findall(r'[\u4e00-\u9fa5]{2,4}', query))
        
        # 基于关键词匹配召回候选
        if query_keywords:
            placeholders = ','.join(['?'] * len(query_keywords))
            cursor.execute(f'''
                SELECT DISTINCT m.*, SUM(wf.freq) as keyword_score
                FROM materials m
                JOIN word_freq wf ON m.id = wf.material_id
                WHERE wf.word IN ({placeholders})
                GROUP BY m.id
                ORDER BY keyword_score DESC
                LIMIT {n_results * 2}
            ''', list(query_keywords))
        else:
            cursor.execute('SELECT * FROM materials LIMIT ?', (n_results * 2,))
        
        rows = cursor.fetchall()
        
        results = []
        for row in rows:
            material = InterviewMaterial(
                id=row[0],
                source_file=row[1],
                content=row[2],
                chunk_index=row[3],
                topics=json.loads(row[4]) if row[4] else [],
                time_references=json.loads(row[5]) if row[5] else [],
                entities=json.loads(row[6]) if row[6] else [],
            )
            # 关键词检索给固定分数
            results.append((material, 0.3))
        
        conn.close()
        return results[:n_results]
    
    def search_by_time(self, year: str) -> List[InterviewMaterial]:
        """按时间检索素材"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM materials
            WHERE time_refs LIKE ?
            ORDER BY chunk_index
        ''', (f'%"{year}"%',))

        rows = cursor.fetchall()

        materials = []
        for row in rows:
            materials.append(InterviewMaterial(
                id=row[0],
                source_file=row[1],
                content=row[2],
                chunk_index=row[3],
                topics=json.loads(row[4]) if row[4] else [],
                time_references=json.loads(row[5]) if row[5] else [],
                entities=json.loads(row[6]) if row[6] else [],
            ))

        conn.close()
        return materials

    async def search_with_parent_backtrack(
        self,
        query: str,
        n_results: int = 5,
        chunk_type: str = "scene"
    ) -> List[HybridSearchResult]:
        """
        带父块回溯的检索

        流程:
        1. 检索子块（scene）
        2. 获取这些子块的父块（summary）
        3. 合并返回

        Returns:
            合并后的结果列表（父块在前，子块在后）
        """
        # 1. 检索子块
        child_results = await self.hybrid_search(
            query,
            n_results=n_results * 2,
            chunk_type=chunk_type
        )

        if not child_results:
            return []

        # 2. 获取父块ID
        parent_ids = set()
        for r in child_results:
            # 从数据库查询parent_id
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT parent_id FROM materials WHERE id = ?",
                (r.material.id,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                parent_ids.add(row[0])
            conn.close()

        # 3. 获取父块
        parent_results = []
        if parent_ids:
            parents_map = self._get_materials_by_ids(list(parent_ids))
            for parent_id, material in parents_map.items():
                parent_results.append(HybridSearchResult(
                    material=material,
                    rrf_score=0.0,  # 父块不参与排序
                    source="parent"
                ))

        # 4. 合并结果（父块在前，子块在后）
        merged = parent_results + child_results[:n_results]

        # 更新排名
        for i, r in enumerate(merged):
            r.final_rank = i + 1

        return merged

    def get_stats(self) -> Dict[str, int]:
        """获取检索系统统计信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 向量数量
        cursor.execute("SELECT COUNT(*) FROM materials")
        total_materials = cursor.fetchone()[0]

        # 有向量的素材数量
        cursor.execute("SELECT COUNT(*) FROM materials WHERE embedding IS NOT NULL")
        vector_count = cursor.fetchone()[0]

        # BM25索引的term数量
        cursor.execute("SELECT COUNT(DISTINCT term) FROM bm25_index")
        bm25_terms = cursor.fetchone()[0]

        # 父子索引统计
        cursor.execute("SELECT COUNT(*) FROM materials WHERE chunk_type = 'summary'")
        summary_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM materials WHERE chunk_type = 'scene'")
        scene_count = cursor.fetchone()[0]

        conn.close()

        return {
            "total_materials": total_materials,
            "vector_count": vector_count,
            "bm25_terms": bm25_terms,
            "summary_count": summary_count,
            "scene_count": scene_count
        }

    def clear(self):
        """清空数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM materials')
        cursor.execute('DELETE FROM word_freq')
        cursor.execute('DELETE FROM bm25_index')
        cursor.execute('DELETE FROM doc_stats')
        conn.commit()
        conn.close()
        logger.info("已清空所有检索数据")


class HybridRetriever:
    """混合检索器 - 封装混合检索功能的高级接口"""

    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store

    async def retrieve(
        self,
        query: str,
        n_results: int = 10,
        chunk_type: Optional[str] = None,
        use_parent_backtrack: bool = False,
        enable_rerank: bool = None
    ) -> List[HybridSearchResult]:
        """
        执行混合检索

        Args:
            query: 查询文本
            n_results: 返回结果数量
            chunk_type: 块类型过滤 (summary/scene)
            use_parent_backtrack: 是否启用父块回溯
            enable_rerank: 是否启用重排序

        Returns:
            HybridSearchResult列表
        """
        if use_parent_backtrack:
            return await self.vector_store.search_with_parent_backtrack(
                query, n_results=n_results, chunk_type=chunk_type or "scene"
            )
        else:
            return await self.vector_store.hybrid_search(
                query,
                n_results=n_results,
                chunk_type=chunk_type,
                enable_rerank=enable_rerank
            )

    def retrieve_sync(
        self,
        query: str,
        n_results: int = 10,
        chunk_type: Optional[str] = None
    ) -> List[Tuple[InterviewMaterial, float]]:
        """
        同步检索接口（向后兼容）

        Returns:
            [(material, score), ...]
        """
        return self.vector_store.search(query, n_results=n_results)


class DataIngestionLayer:
    """数据接入与解析层主类"""

    def __init__(self):
        self.cleaner = DataCleaner()
        self.segmenter = TopicSegmenter()
        self.vector_store = VectorStore()
        self.retriever = HybridRetriever(self.vector_store)
    
    async def process_interview(
        self,
        file_path: Path,
        subject_hint: Optional[str] = None
    ) -> List[InterviewMaterial]:
        """
        处理单个采访文件
        """
        logger.info(f"开始处理采访文件: {file_path}")
        
        # 1. 读取文件
        text = self._read_file(file_path)
        
        # 2. 数据清洗
        logger.info("正在清洗数据...")
        cleaned = self.cleaner.clean(text)
        logger.info(f"清洗完成，移除噪音词 {len(cleaned.removed_noise)} 个")
        
        # 3. 话题切分
        logger.info("正在切分话题...")
        segments = self.segmenter.segment(cleaned.cleaned)
        logger.info(f"切分为 {len(segments)} 个话题段落")
        
        # 4. 进一步切分为检索块（使用传记专用切分，增大到1000字）
        logger.info("正在生成检索块...")
        materials = []
        chunk_idx = 0
        
        for seg_idx, segment in enumerate(segments):
            # 将话题段落进一步切分（传记专用策略，增大chunk_size）
            chunks = split_text_biography(
                segment["text"],
                chunk_size=1000,  # 增大到1000字
                chunk_overlap=200  # 增大重叠
            )
            
            for chunk_text in chunks:
                # 提取元数据
                time_refs = extract_time_expressions(chunk_text)
                entities = extract_entities(chunk_text)
                
                material = InterviewMaterial(
                    id=generate_id(file_path.name, chunk_idx),
                    source_file=file_path.name,
                    content=chunk_text,
                    chunk_index=chunk_idx,
                    topics=segment["topics"],
                    time_references=[t["text"] for t in time_refs],
                    entities=[e["text"] for e in entities]
                )
                
                materials.append(material)
                chunk_idx += 1
        
        logger.info(f"生成 {len(materials)} 个检索块")
        
        # 5. 存入数据库（含向量嵌入）
        logger.info("正在存入数据库并生成向量嵌入...")
        self.vector_store.add_materials(materials)
        
        return materials
    
    def _read_file(self, file_path: Path) -> str:
        """读取文件内容"""
        suffix = file_path.suffix.lower()
        
        if suffix == ".txt":
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        
        elif suffix == ".md":
            with open(file_path, "r", encoding="utf-8") as f:
                # 简单移除markdown标记，但保留内容
                content = f.read()
                # 保留标题内容，只移除标记符号
                content = re.sub(r'^(#{1,6})\s+', r'\1 ', content, flags=re.MULTILINE)
                content = re.sub(r'\*\*|__', '', content)  # 移除加粗
                return content
        
        else:
            raise ValueError(f"不支持的文件格式: {suffix}")
    
    async def retrieve_for_chapter(
        self,
        chapter_title: str,
        chapter_summary: str,
        time_period: Optional[str] = None,
        n_results: int = 10,
        use_hybrid: bool = True,
        use_parent_backtrack: bool = False
    ) -> List[InterviewMaterial]:
        """
        为特定章节检索相关素材

        Args:
            chapter_title: 章节标题
            chapter_summary: 章节摘要
            time_period: 时间段（可选）
            n_results: 返回结果数量
            use_hybrid: 是否使用混合检索
            use_parent_backtrack: 是否启用父块回溯

        Returns:
            InterviewMaterial列表
        """
        # 构建多维度查询
        query_parts = [chapter_title, chapter_summary]
        if time_period:
            query_parts.append(time_period)

        query = " ".join(query_parts)

        materials = []

        if use_hybrid:
            # 使用混合检索
            results = await self.retriever.retrieve(
                query,
                n_results=n_results,
                use_parent_backtrack=use_parent_backtrack
            )
            materials = [r.material for r in results]
        else:
            # 使用传统向量检索（向后兼容）
            results = self.vector_store.search(query, n_results=n_results)
            materials = [m for m, s in results]

        # 如果结果不足，补充时间检索
        if len(materials) < n_results and time_period and len(time_period) >= 4:
            year = time_period[:4]
            time_results = self.vector_store.search_by_time(year)

            # 合并去重
            existing_ids = {m.id for m in materials}
            for m in time_results:
                if m.id not in existing_ids:
                    materials.append(m)

        return materials[:n_results]

    def get_retrieval_stats(self) -> Dict[str, int]:
        """获取检索系统统计信息"""
        return self.vector_store.get_stats()
