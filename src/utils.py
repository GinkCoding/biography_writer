"""通用工具函数"""
import re
import hashlib
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import jieba
import tiktoken


def count_chinese_words(text: str) -> int:
    """统计中文字符数（不含标点）"""
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    return len(chinese_chars)


def count_total_words(text: str) -> int:
    """统计总字数（中文字符 + 英文单词）"""
    chinese_count = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    return chinese_count + english_words


def estimate_tokens(text: str, model: str = "gpt-4") -> int:
    """估算token数量"""
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except:
        # 回退方案：粗略估算
        return len(text) // 2


def extract_time_expressions(text: str) -> List[Dict[str, Any]]:
    """从文本中提取时间表达式"""
    time_patterns = [
        # 年月日
        r'(\d{4})年(\d{1,2})月(\d{1,2})日',
        r'(\d{4})-(\d{1,2})-(\d{1,2})',
        # 年月
        r'(\d{4})年(\d{1,2})月',
        r'(\d{4})-(\d{1,2})',
        # 年
        r'(\d{4})年',
        # 相对时间
        r'(\d{4})年代',
        r'(\d{1,2})岁',
        r'(小学|初中|高中|大学)时期',
        r'(童年|少年|青年|中年|老年)',
        r'(春天|夏天|秋天|冬天)',
    ]
    
    results = []
    for pattern in time_patterns:
        for match in re.finditer(pattern, text):
            results.append({
                "text": match.group(0),
                "start": match.start(),
                "end": match.end(),
                "type": "absolute" if match.group(0).isdigit() else "relative"
            })
    
    return results


def extract_entities(text: str) -> List[Dict[str, Any]]:
    """提取命名实体（简单实现，可用NER模型增强）"""
    entities = []
    
    # 人名模式（简单规则）
    # 中文人名：2-4个汉字，常见姓氏开头
    common_surnames = "王李张刘陈杨黄赵周吴徐孙马朱胡郭何罗高林郑梁谢宋唐许韩冯邓曹彭曾肖田董潘袁蔡蒋余于杜"
    name_pattern = f"[{common_surnames}][\u4e00-\u9fff]{{1,3}}"
    
    found_names = set()
    for match in re.finditer(name_pattern, text):
        name = match.group(0)
        if name not in found_names:
            found_names.add(name)
            entities.append({
                "text": name,
                "type": "PERSON",
                "start": match.start(),
                "end": match.end()
            })
    
    # 地名模式
    location_suffixes = "省市县区镇乡村庄路街道"
    location_pattern = f"[\u4e00-\u9fff]{{2,6}}[{location_suffixes}]"
    
    for match in re.finditer(location_pattern, text):
        entities.append({
            "text": match.group(0),
            "type": "LOCATION",
            "start": match.start(),
            "end": match.end()
        })
    
    return entities


def split_text_into_chunks(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100
) -> List[str]:
    """将长文本切分成块"""
    # 使用句子边界切分
    sentences = re.split(r'([。！？.!?\n])', text)
    
    chunks = []
    current_chunk = []
    current_length = 0
    
    for i in range(0, len(sentences), 2):
        sentence = sentences[i]
        if i + 1 < len(sentences):
            sentence += sentences[i + 1]  # 加上标点
        
        sentence_length = len(sentence)
        
        if current_length + sentence_length > chunk_size and current_chunk:
            chunks.append("".join(current_chunk))
            # 保留重叠部分
            overlap_text = "".join(current_chunk)[-chunk_overlap:]
            current_chunk = [overlap_text, sentence]
            current_length = len(overlap_text) + sentence_length
        else:
            current_chunk.append(sentence)
            current_length += sentence_length
    
    if current_chunk:
        chunks.append("".join(current_chunk))
    
    return chunks


def normalize_date(date_str: str) -> Optional[str]:
    """标准化日期格式"""
    if not date_str:
        return None
    
    # 尝试多种格式
    patterns = [
        (r'(\d{4})年(\d{1,2})月(\d{1,2})日', lambda m: f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"),
        (r'(\d{4})-(\d{1,2})-(\d{1,2})', lambda m: f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"),
        (r'(\d{4})年(\d{1,2})月', lambda m: f"{m.group(1)}-{m.group(2).zfill(2)}"),
        (r'(\d{4})-(\d{1,2})', lambda m: f"{m.group(1)}-{m.group(2).zfill(2)}"),
        (r'(\d{4})年', lambda m: m.group(1)),
        (r'(\d{4})', lambda m: m.group(1) if len(m.group(1)) == 4 else None),
    ]
    
    for pattern, formatter in patterns:
        match = re.match(pattern, date_str)
        if match:
            return formatter(match)
    
    return date_str


def generate_id(*args) -> str:
    """基于内容生成唯一ID"""
    content = "|".join(str(arg) for arg in args)
    return hashlib.md5(content.encode()).hexdigest()[:16]


def save_json(data: Any, filepath: Path):
    """保存JSON文件"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def load_json(filepath: Path) -> Any:
    """加载JSON文件"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def sanitize_filename(filename: str) -> str:
    """清理文件名中的非法字符"""
    illegal_chars = '<>:"/\\|?*'
    for char in illegal_chars:
        filename = filename.replace(char, '_')
    return filename.strip()


def calculate_age(birth_date: str, current_date: str) -> Optional[int]:
    """计算年龄"""
    try:
        birth_year = int(re.match(r'(\d{4})', birth_date).group(1))
        current_year = int(re.match(r'(\d{4})', current_date).group(1))
        return current_year - birth_year
    except:
        return None


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


class ProgressTracker:
    """进度跟踪器"""
    
    def __init__(self, total: int, description: str = "Progress"):
        self.total = total
        self.current = 0
        self.description = description
    
    def update(self, n: int = 1):
        self.current += n
        percentage = (self.current / self.total) * 100
        return f"{self.description}: {self.current}/{self.total} ({percentage:.1f}%)"
    
    @property
    def is_complete(self) -> bool:
        return self.current >= self.total