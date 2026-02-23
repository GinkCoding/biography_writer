"""第一层：数据接入与解析层 (Data Ingestion)"""
import re
import sqlite3
import json
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
from loguru import logger

from src.config import settings
from src.models import InterviewMaterial
from src.utils import split_text_into_chunks, extract_time_expressions, extract_entities, generate_id


@dataclass
class CleanedText:
    """清洗后的文本"""
    original: str
    cleaned: str
    removed_noise: List[str]


class DataCleaner:
    """数据清洗器"""
    
    # 口语化填充词和语气词
    FILLER_WORDS = [
        r"那个", r"这个", r"就是", r"然后", r"嗯", r"啊", r"呃", r"哦",
        r"对吧", r"是吧", r"你知道", r"我觉得", r"怎么说呢",
        r"[嗯啊呃哦哈]{1,}",  # 连续的语气词
        r"\(.*?\)",  # 括号内的内容（通常是采访者备注）
        r"\[.*?\]",  # 方括号内容
    ]
    
    # 重复标记
    REPEAT_PATTERNS = [
        r"(.{3,20})\1{1,}",  # 重复3-20字符的片段
    ]
    
    def clean(self, text: str) -> CleanedText:
        """清洗文本"""
        removed = []
        cleaned = text
        
        # 1. 移除语气词和填充词
        for pattern in self.FILLER_WORDS:
            matches = re.findall(pattern, cleaned)
            if matches:
                removed.extend(matches[:5])  # 只记录前5个
                cleaned = re.sub(pattern, "", cleaned)
        
        # 2. 合并重复标点
        cleaned = re.sub(r'[。]{2,}', '。', cleaned)
        cleaned = re.sub(r'[！]{2,}', '！', cleaned)
        
        # 3. 合并重复内容
        for pattern in self.REPEAT_PATTERNS:
            cleaned = re.sub(pattern, r"\1", cleaned)
        
        # 4. 规范化空白
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = re.sub(r' +', ' ', cleaned)
        
        # 5. 段落分割优化
        cleaned = re.sub(r'([。！？])\s*', r"\1\n", cleaned)
        
        return CleanedText(
            original=text,
            cleaned=cleaned.strip(),
            removed_noise=removed
        )


class TopicSegmenter:
    """话题切分器 - 按话题或时间段切分文本"""
    
    # 话题转换标记
    TOPIC_MARKERS = [
        r"接下来",
        r"说到",
        r"另外",
        r"还有",
        r"再说",
        r"后来",
        r"那时候",
        r"那段时间",
    ]
    
    def segment(self, text: str) -> List[dict]:
        """将文本切分成话题块"""
        segments = []
        
        # 先按段落分割
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
        
        current_segment = []
        current_topics = []
        
        for para in paragraphs:
            # 检查是否是新话题的开始
            is_new_topic = any(re.search(marker, para) for marker in self.TOPIC_MARKERS)
            
            if is_new_topic and current_segment:
                # 保存当前段落组
                segment_text = '\n'.join(current_segment)
                segments.append({
                    "text": segment_text,
                    "topics": current_topics.copy(),
                    "char_count": len(segment_text)
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
                "char_count": len(segment_text)
            })
        
        return segments
    
    def _extract_topics(self, text: str) -> List[str]:
        """提取话题关键词"""
        topics = []
        
        # 简单关键词匹配
        topic_keywords = {
            "童年": ["小时候", "童年", "小学", "家乡"],
            "求学": ["大学", "学校", "读书", "学习", "老师", "同学"],
            "工作": ["工作", "上班", "公司", "创业", "事业", "职位"],
            "家庭": ["父母", "父亲", "母亲", "妻子", "丈夫", "孩子", "结婚"],
            "挫折": ["困难", "失败", "挫折", "低谷", "困境"],
            "转折": ["决定", "选择", "转折", "改变", "机会"],
        }
        
        for topic, keywords in topic_keywords.items():
            if any(kw in text for kw in keywords):
                topics.append(topic)
        
        return topics


class VectorStore:
    """向量数据库存储 - 使用SQLite简化版"""
    
    def __init__(self):
        self.db_path = Path(settings.paths.vector_db_dir) / "materials.db"
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS materials (
                id TEXT PRIMARY KEY,
                source_file TEXT,
                content TEXT,
                chunk_index INTEGER,
                topics TEXT,
                time_refs TEXT,
                entities TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_materials(self, materials: List[InterviewMaterial]):
        """添加素材到数据库"""
        if not materials:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for m in materials:
            cursor.execute('''
                INSERT OR REPLACE INTO materials 
                (id, source_file, content, chunk_index, topics, time_refs, entities)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                m.id,
                m.source_file,
                m.content,
                m.chunk_index,
                json.dumps(m.topics, ensure_ascii=False),
                json.dumps(m.time_references, ensure_ascii=False),
                json.dumps(m.entities, ensure_ascii=False)
            ))
        
        conn.commit()
        conn.close()
        
        logger.info(f"已向数据库添加 {len(materials)} 个素材块")
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        filter_dict: Optional[dict] = None
    ) -> List[InterviewMaterial]:
        """检索相关素材 - 简化的关键词匹配"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 提取查询关键词
        keywords = query.split()
        
        # 简单的全文检索：匹配content中包含关键词的记录
        results = []
        cursor.execute('SELECT * FROM materials')
        rows = cursor.fetchall()
        
        scored_results = []
        for row in rows:
            content = row[2]  # content列
            score = 0
            for kw in keywords:
                if kw in content:
                    score += 1
                if kw in row[4]:  # topics
                    score += 2
                if kw in row[5]:  # time_refs
                    score += 1
            
            if score > 0:
                scored_results.append((score, row))
        
        # 按分数排序，取前n个
        scored_results.sort(key=lambda x: x[0], reverse=True)
        
        materials = []
        for _, row in scored_results[:n_results]:
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
        
        Args:
            file_path: 采访文件路径
            subject_hint: 传主姓名提示
        
        Returns:
            处理后的素材列表
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
        
        # 4. 进一步切分为检索块
        logger.info("正在生成检索块...")
        materials = []
        chunk_idx = 0
        
        for seg_idx, segment in enumerate(segments):
            # 将话题段落进一步切分
            chunks = split_text_into_chunks(
                segment["text"],
                chunk_size=settings.vector_db.chunk_size,
                chunk_overlap=settings.vector_db.chunk_overlap
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
        
        # 5. 存入数据库
        logger.info("正在存入数据库...")
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
                # 简单移除markdown标记
                content = f.read()
                content = re.sub(r'#+ ', '', content)  # 标题
                content = re.sub(r'\*\*|__', '', content)  # 加粗
                return content
        
        else:
            raise ValueError(f"不支持的文件格式: {suffix}")
    
    def retrieve_for_chapter(
        self,
        chapter_title: str,
        chapter_summary: str,
        n_results: int = 10
    ) -> List[InterviewMaterial]:
        """为特定章节检索相关素材"""
        query = f"{chapter_title} {chapter_summary}"
        return self.vector_store.search(query, n_results=n_results)