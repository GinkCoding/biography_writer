"""
轻量级向量存储 - JSON持久化

用于章节重复检测，存储已生成章节的向量表示
"""
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict
import numpy as np


@dataclass
class ChapterEmbedding:
    """章节向量表示"""
    chapter_num: int
    title: str
    content_hash: str  # 内容哈希
    embedding: List[float]  # 简化的向量表示（关键词权重）
    summary: str  # 内容摘要
    key_events: List[str]  # 关键事件


class SimpleVectorStore:
    """
    轻量级向量存储

    不依赖外部向量数据库，使用JSON文件存储简化的向量表示
    基于TF-IDF思路，计算内容相似度
    """

    def __init__(self, store_path: Path):
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        self.chapters: Dict[int, ChapterEmbedding] = {}
        self._load()

    def _load(self):
        """加载存储"""
        if not self.store_path.exists():
            return

        try:
            data = json.loads(self.store_path.read_text(encoding='utf-8'))
            for item in data.get('chapters', []):
                ch = ChapterEmbedding(**item)
                self.chapters[ch.chapter_num] = ch
        except Exception as e:
            print(f"加载向量存储失败: {e}")

    def save(self):
        """保存存储"""
        data = {
            'chapters': [asdict(ch) for ch in self.chapters.values()]
        }
        self.store_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

    def _compute_hash(self, content: str) -> str:
        """计算内容哈希"""
        return hashlib.md5(content.encode('utf-8')).hexdigest()[:16]

    def _extract_keywords(self, content: str) -> Dict[str, float]:
        """
        提取关键词及其权重（简化版TF）

        不使用复杂NLP，基于：
        1. 年份数字（高权重）
        2. 人物姓名（中高权重）
        3. 地点名称（中权重）
        4. 事件动词（中权重）
        """
        import re

        keywords = {}

        # 提取年份（高权重）
        years = re.findall(r'19\d{2}|20\d{2}', content)
        for year in years:
            keywords[year] = keywords.get(year, 0) + 2.0

        # 提取可能的姓名（2-4个中文字符）
        names = re.findall(r'[\u4e00-\u9fa5]{2,4}', content)
        for name in names:
            if len(name) >= 2 and len(name) <= 4:
                # 过滤常见词
                if name not in ['我们', '他们', '但是', '因为', '所以', '这个', '那个']:
                    keywords[name] = keywords.get(name, 0) + 1.0

        # 提取地点后缀词
        location_patterns = ['市', '省', '县', '镇', '村', '街', '路', '厂', '公司']
        for pattern in location_patterns:
            matches = re.findall(rf'[\u4e00-\u9fa5]{{1,5}}{pattern}', content)
            for match in matches:
                keywords[match] = keywords.get(match, 0) + 1.5

        # 提取数字（可能是金额、数量）
        numbers = re.findall(r'\d+万|\d+千|\d+百|\d+元', content)
        for num in numbers:
            keywords[num] = keywords.get(num, 0) + 1.2

        return keywords

    def _keywords_to_vector(self, keywords: Dict[str, float], dim: int = 128) -> List[float]:
        """将关键词映射到固定维度的向量"""
        vector = [0.0] * dim

        for keyword, weight in keywords.items():
            # 使用哈希确定位置
            hash_val = int(hashlib.md5(keyword.encode()).hexdigest(), 16)
            idx = hash_val % dim
            vector[idx] += weight

        # 归一化
        norm = sum(x ** 2 for x in vector) ** 0.5
        if norm > 0:
            vector = [x / norm for x in vector]

        return vector

    def add_chapter(self, chapter_num: int, title: str, content: str,
                    summary: str = "", key_events: List[str] = None):
        """添加章节到存储"""
        keywords = self._extract_keywords(content)
        embedding = self._keywords_to_vector(keywords)

        self.chapters[chapter_num] = ChapterEmbedding(
            chapter_num=chapter_num,
            title=title,
            content_hash=self._compute_hash(content),
            embedding=embedding,
            summary=summary or content[:200],
            key_events=key_events or []
        )
        self.save()

    def compute_similarity(self, content: str, chapter_num: int = None) -> float:
        """
        计算内容与已存储章节的相似度

        Returns:
            最高相似度分数 (0-1)
        """
        if not self.chapters:
            return 0.0

        keywords = self._extract_keywords(content)
        vec = self._keywords_to_vector(keywords)

        max_similarity = 0.0

        for num, ch in self.chapters.items():
            # 跳过自身（如果是更新）
            if chapter_num is not None and num == chapter_num:
                continue

            # 计算余弦相似度
            similarity = self._cosine_similarity(vec, ch.embedding)
            max_similarity = max(max_similarity, similarity)

        return max_similarity

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算余弦相似度"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x ** 2 for x in a) ** 0.5
        norm_b = sum(x ** 2 for x in b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)

    def find_similar_chapters(self, content: str, threshold: float = 0.7) -> List[Dict]:
        """
        查找相似的章节

        Returns:
            相似章节列表，按相似度排序
        """
        keywords = self._extract_keywords(content)
        vec = self._keywords_to_vector(keywords)

        similar = []
        for num, ch in self.chapters.items():
            similarity = self._cosine_similarity(vec, ch.embedding)
            if similarity >= threshold:
                similar.append({
                    'chapter_num': num,
                    'title': ch.title,
                    'similarity': similarity,
                    'summary': ch.summary
                })

        return sorted(similar, key=lambda x: x['similarity'], reverse=True)

    def get_all_summaries(self) -> List[str]:
        """获取所有章节的摘要"""
        return [f"第{ch.chapter_num}章《{ch.title}》: {ch.summary[:100]}..."
                for ch in self.chapters.values()]

    def export_for_repetition_check(self) -> Dict:
        """导出用于重复检测的数据"""
        return {
            num: {
                'title': ch.title,
                'summary': ch.summary,
                'key_events': ch.key_events
            }
            for num, ch in self.chapters.items()
        }
