"""通用工具函数"""
import re
import hashlib
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Set
from pathlib import Path
import jieba
import tiktoken


_FULLWIDTH_TRANSLATION_TABLE = str.maketrans(
    "０１２３４５６７８９－／．：，（）　",
    "0123456789-/.:,() ",
)

_COMMON_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华"
    "金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方"
    "俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝安常乐于时傅皮"
    "卞齐康伍余元顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏"
    "成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童"
    "颜郭梅盛林刁钟徐邱骆高夏蔡田胡凌霍虞万支柯管卢莫经房裘缪"
    "干解应宗丁宣贲邓郁单杭洪包诸左石崔吉龚程邢滑裴陆荣翁荀羊"
    "於惠甄魏加鲁窦黎乔白简连薄向巩沙瞿阎江童司马欧阳上官夏侯"
)

_PERSON_STOPWORDS: Set[str] = {
    "这个", "那个", "这里", "那里", "他们", "我们", "你们", "自己", "大家",
    "后来", "当时", "如果", "因为", "所以", "于是", "还有", "就是", "然后",
}

_RELATIVE_TIME_TERMS = [
    "当年", "那年", "次年", "翌年", "同年", "次月", "次日",
    "后来", "随后", "再后来", "不久后", "之后", "之前", "当时",
    "童年", "少年", "青年", "中年", "老年",
    "小学时期", "初中时期", "高中时期", "大学时期",
    "春天", "夏天", "秋天", "冬天",
]


def _ensure_text(value: Any) -> str:
    """将输入安全转换为字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_extraction_text(text: str) -> str:
    """规范化提取文本，降低口语稿和全角符号对规则匹配的影响。"""
    normalized = _ensure_text(text).translate(_FULLWIDTH_TRANSLATION_TABLE)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _ordered_unique(items: List[str], max_items: int = 50) -> List[str]:
    """按原顺序去重。"""
    seen: Set[str] = set()
    result: List[str] = []
    for item in items:
        text = _ensure_text(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= max_items:
            break
    return result


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
    """从文本中提取时间表达式（容错增强版）。"""
    normalized_text = _normalize_extraction_text(text)
    if not normalized_text:
        return []

    patterns = [
        ("absolute", "date", r"(?P<year>(?:19|20)\d{2})[年\-/.](?P<month>\d{1,2})[月\-/.](?P<day>\d{1,2})[日号]?"),
        ("absolute", "month", r"(?P<year>(?:19|20)\d{2})[年\-/.](?P<month>\d{1,2})月?"),
        ("absolute", "year", r"(?<!\d)(?P<year>(?:19|20)\d{2})年(?!\d)"),
        ("absolute", "decade", r"(?<!\d)(?P<year>(?:19|20)\d{2})年代"),
        ("relative", "age", r"(?P<age>\d{1,3})岁(?:那年|时|的时候|阶段)?"),
    ]

    seen: Set[Tuple[int, int, str]] = set()
    results: List[Dict[str, Any]] = []

    for expression_type, category, pattern in patterns:
        try:
            matches = list(re.finditer(pattern, normalized_text))
        except re.error:
            continue
        for match in matches:
            span_key = (match.start(), match.end(), match.group(0))
            if span_key in seen:
                continue
            seen.add(span_key)

            normalized = match.group(0)
            confidence = 0.8
            if category == "date":
                year = match.group("year")
                month = int(match.group("month"))
                day = int(match.group("day"))
                if 1 <= month <= 12 and 1 <= day <= 31:
                    normalized = f"{year}-{month:02d}-{day:02d}"
                    confidence = 0.95
            elif category == "month":
                year = match.group("year")
                month = int(match.group("month"))
                if 1 <= month <= 12:
                    normalized = f"{year}-{month:02d}"
                    confidence = 0.9
            elif category in {"year", "decade"}:
                normalized = match.group("year")
                confidence = 0.88

            results.append(
                {
                    "text": match.group(0),
                    "start": match.start(),
                    "end": match.end(),
                    "type": expression_type,
                    "category": category,
                    "normalized": normalized,
                    "confidence": confidence,
                }
            )

    relative_pattern = "|".join(re.escape(term) for term in _RELATIVE_TIME_TERMS)
    if relative_pattern:
        for match in re.finditer(relative_pattern, normalized_text):
            span_key = (match.start(), match.end(), match.group(0))
            if span_key in seen:
                continue
            seen.add(span_key)
            results.append(
                {
                    "text": match.group(0),
                    "start": match.start(),
                    "end": match.end(),
                    "type": "relative",
                    "category": "relative",
                    "normalized": match.group(0),
                    "confidence": 0.7,
                }
            )

    results.sort(key=lambda x: (x.get("start", 0), x.get("end", 0)))
    return results


def extract_entities(text: str) -> List[Dict[str, Any]]:
    """提取命名实体（容错增强版，失败降级）。"""
    normalized_text = _normalize_extraction_text(text)
    if not normalized_text:
        return []

    entities: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str, int]] = set()

    def add_entity(raw_text: str, entity_type: str, start: int, end: int, confidence: float) -> None:
        clean_text = _ensure_text(raw_text).strip("，。；：、,.!?！？()（）[]【】")
        if not clean_text:
            return
        key = (clean_text, entity_type, start)
        if key in seen:
            return
        seen.add(key)
        entities.append(
            {
                "text": clean_text,
                "type": entity_type,
                "start": start,
                "end": end,
                "confidence": round(confidence, 3),
            }
        )

    # 角色+姓名（优先规则）
    role_name_pattern = (
        r"(父亲|母亲|老师|同学|厂长|主任|书记|经理|老板|师傅|邻居|叔叔|阿姨|哥哥|姐姐|弟弟|妹妹)"
        r"[：:\s]{0,2}"
        r"(?P<name>["
        + _COMMON_SURNAMES
        + r"][\u4e00-\u9fff]{1,2})"
    )
    for match in re.finditer(role_name_pattern, normalized_text):
        add_entity(match.group("name"), "PERSON", match.start("name"), match.end("name"), 0.93)

    person_pattern = r"(?<![\u4e00-\u9fffA-Za-z])([" + _COMMON_SURNAMES + r"][\u4e00-\u9fff]{1,2})(?![\u4e00-\u9fffA-Za-z])"
    for match in re.finditer(person_pattern, normalized_text):
        candidate = match.group(1)
        if candidate in _PERSON_STOPWORDS:
            continue
        if len(candidate) < 2 or len(candidate) > 4:
            continue
        add_entity(candidate, "PERSON", match.start(1), match.end(1), 0.82)

    location_pattern = (
        r"(?P<loc>[\u4e00-\u9fff]{2,14}"
        r"(?:省|市|自治区|自治州|区|县|镇|乡|村|街道|胡同|路|大道|园区|开发区))"
    )
    for match in re.finditer(location_pattern, normalized_text):
        add_entity(match.group("loc"), "LOCATION", match.start("loc"), match.end("loc"), 0.88)

    organization_pattern = (
        r"(?P<org>[A-Za-z0-9\u4e00-\u9fff]{2,30}"
        r"(?:公司|集团|工厂|厂|学校|大学|学院|银行|医院|研究院|研究所|政府|委员会|公安局|出版社|部队|电视台|报社|协会))"
    )
    for match in re.finditer(organization_pattern, normalized_text):
        add_entity(match.group("org"), "ORG", match.start("org"), match.end("org"), 0.86)

    entities.sort(key=lambda x: (x.get("start", 0), x.get("end", 0)))
    return entities


def extract_key_information(text: Any, max_events: int = 12) -> Dict[str, Any]:
    """从采访素材中提取关键信息（失败不抛错，始终返回结构化结果）。"""
    normalized_text = _normalize_extraction_text(_ensure_text(text))
    result: Dict[str, Any] = {
        "time_expressions": [],
        "entities": [],
        "people": [],
        "locations": [],
        "organizations": [],
        "roles": [],
        "event_candidates": [],
        "warnings": [],
    }

    if not normalized_text:
        result["warnings"].append("输入文本为空")
        return result

    try:
        result["time_expressions"] = extract_time_expressions(normalized_text)
    except Exception as exc:
        result["warnings"].append(f"时间提取失败: {exc}")

    try:
        entities = extract_entities(normalized_text)
        result["entities"] = entities
        result["people"] = _ordered_unique([e["text"] for e in entities if e.get("type") == "PERSON"])
        result["locations"] = _ordered_unique([e["text"] for e in entities if e.get("type") == "LOCATION"])
        result["organizations"] = _ordered_unique([e["text"] for e in entities if e.get("type") == "ORG"])
    except Exception as exc:
        result["warnings"].append(f"实体提取失败: {exc}")

    role_pattern = (
        r"(父亲|母亲|老师|同学|厂长|主任|书记|经理|老板|师傅|邻居|妻子|丈夫|儿子|女儿)"
        r"(?:是|叫|名叫|：|:)?"
        r"(["
        + _COMMON_SURNAMES
        + r"]?[\u4e00-\u9fff]{0,2})"
    )
    roles: List[str] = []
    for match in re.finditer(role_pattern, normalized_text):
        role = _ensure_text(match.group(1)).strip()
        name = _ensure_text(match.group(2)).strip()
        if role and name:
            roles.append(f"{role}:{name}")
        elif role:
            roles.append(role)
    result["roles"] = _ordered_unique(roles, max_items=30)

    sentence_splitter = r"[。！？!?；;\n]+"
    event_verbs = [
        "出生", "上学", "毕业", "工作", "创业", "结婚", "离开", "返回",
        "考上", "调任", "创业", "失败", "转行", "成立", "加入", "搬家",
        "生病", "康复", "去世", "采访", "回忆", "决定",
    ]
    time_texts = {item.get("text", "") for item in result["time_expressions"]}
    for raw_sentence in re.split(sentence_splitter, normalized_text):
        sentence = raw_sentence.strip()
        if len(sentence) < 8:
            continue
        has_time_signal = any(time_text and time_text in sentence for time_text in time_texts)
        has_event_verb = any(verb in sentence for verb in event_verbs)
        if not has_time_signal and not has_event_verb:
            continue
        confidence = 0.55
        if has_time_signal:
            confidence += 0.25
        if has_event_verb:
            confidence += 0.2
        result["event_candidates"].append(
            {
                "text": sentence[:200],
                "confidence": round(min(confidence, 0.99), 3),
            }
        )
        if len(result["event_candidates"]) >= max_events:
            break

    return result


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
