"""第一层：数据接入与解析层 (Data Ingestion)"""
import re
import sqlite3
import json
import hashlib
import numpy as np
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from loguru import logger

from src.config import settings
from src.models import InterviewMaterial
from src.utils import extract_time_expressions, extract_entities, generate_id
from src.embedding import get_embedding_manager


@dataclass
class CleanedText:
    """清洗后的文本"""
    original: str
    cleaned: str
    removed_noise: List[str]


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


class VectorStore:
    """向量数据库 - 支持真实语义检索"""
    
    def __init__(self):
        self.db_path = Path(settings.paths.vector_db_dir) / "materials.db"
        # 从配置获取embedding管理器
        embedding_config = settings.embedding.get_embedding_manager_config()
        self.embedding_mgr = get_embedding_manager(embedding_config)
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 素材表 - 增加embedding列
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
                embedding BLOB  -- 新增：向量嵌入
            )
        ''')
        
        # 词频统计表（用于混合检索）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS word_freq (
                word TEXT,
                material_id TEXT,
                freq INTEGER,
                PRIMARY KEY (word, material_id)
            )
        ''')
        
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
    
    def add_materials(self, materials: List[InterviewMaterial]):
        """添加素材到数据库（含向量嵌入）"""
        if not materials:
            return
        
        logger.info(f"正在为 {len(materials)} 个素材生成向量嵌入...")
        
        # 批量生成嵌入
        contents = [m.content for m in materials]
        try:
            embeddings = self.embedding_mgr.encode(contents)
        except Exception as e:
            logger.error(f"生成向量嵌入失败: {e}")
            # 失败时回退到关键词检索模式
            embeddings = None
        
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
                (id, source_file, content, chunk_index, topics, time_refs, entities, content_hash, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                m.id,
                m.source_file,
                m.content,
                m.chunk_index,
                json.dumps(m.topics, ensure_ascii=False),
                json.dumps(m.time_references, ensure_ascii=False),
                json.dumps(m.entities, ensure_ascii=False),
                content_hash,
                embedding_blob
            ))
            
            # 提取并存储关键词（用于混合检索）
            keywords = self._extract_keywords(m.content)
            for word, freq in keywords.items():
                cursor.execute('''
                    INSERT OR REPLACE INTO word_freq (word, material_id, freq)
                    VALUES (?, ?, ?)
                ''', (word, m.id, freq))
            
            added_count += 1
        
        conn.commit()
        conn.close()
        
        if added_count > 0:
            logger.info(f"已向数据库添加 {added_count} 个素材块（含向量嵌入）")
    
    def search(
        self,
        query: str,
        n_results: int = 10,
        filter_dict: Optional[dict] = None
    ) -> List[Tuple[InterviewMaterial, float]]:
        """
        语义检索 - 基于向量相似度
        
        Returns:
            [(material, similarity_score), ...] 按相似度排序
        """
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
    
    def clear(self):
        """清空数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM materials')
        cursor.execute('DELETE FROM word_freq')
        conn.commit()
        conn.close()


class DataIngestionLayer:
    """数据接入与解析层主类"""
    
    def __init__(self):
        self.cleaner = DataCleaner()
        self.segmenter = TopicSegmenter()
        self.vector_store = VectorStore()
    
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
    
    def retrieve_for_chapter(
        self,
        chapter_title: str,
        chapter_summary: str,
        time_period: Optional[str] = None,
        n_results: int = 10
    ) -> List[InterviewMaterial]:
        """为特定章节检索相关素材"""
        # 构建多维度查询
        query_parts = [chapter_title, chapter_summary]
        if time_period:
            query_parts.append(time_period)
        
        query = " ".join(query_parts)
        
        # 使用语义检索
        results = self.vector_store.search(query, n_results=n_results)
        
        # 解包结果（material, score）
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
