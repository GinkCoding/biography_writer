"""数据模型定义"""
from datetime import datetime
from typing import List, Dict, Optional, Any
from enum import Enum
from pydantic import BaseModel, Field


class WritingStyle(str, Enum):
    """写作风格枚举"""
    DOCUMENTARY = "documentary"
    LITERARY = "literary"
    INVESTIGATIVE = "investigative"
    MEMOIR = "memoir"
    INSPIRATIONAL = "inspirational"


class Event(BaseModel):
    """时间线事件"""
    id: str
    date: Optional[str] = None  # 格式: YYYY-MM-DD 或 YYYY-MM 或 YYYY
    date_approximate: bool = False
    title: str
    description: str
    source_text: str  # 原始访谈文本
    characters_involved: List[str] = []
    location: Optional[str] = None
    importance: int = Field(default=5, ge=1, le=10)  # 重要程度
    chapter_id: Optional[str] = None  # 关联的章节


class Relationship(BaseModel):
    """人物关系"""
    source: str  # 关系主体
    target: str  # 关系对象
    relation_type: str  # 如：父亲、朋友、同事
    description: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class CharacterProfile(BaseModel):
    """人物画像"""
    name: str
    aliases: List[str] = []
    birth_date: Optional[str] = None
    birth_place: Optional[str] = None
    occupation: List[str] = []
    personality_traits: List[str] = []
    core_values: List[str] = []
    relationships: List[Relationship] = []
    
    
class Timeline(BaseModel):
    """全局时间线"""
    subject: CharacterProfile
    events: List[Event] = []
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None
    
    def sort_events(self):
        """按时间排序事件"""
        self.events.sort(key=lambda e: e.date or "")


class SectionOutline(BaseModel):
    """小节大纲"""
    id: str
    title: str
    target_words: int
    key_events: List[str] = []  # 关联的事件ID
    content_summary: str  # 内容概要
    emotional_tone: str  # 情感基调
    material_refs: List[str] = []  # 引用的素材块ID


class ChapterOutline(BaseModel):
    """章节大纲"""
    id: str
    title: str
    order: int
    summary: str
    sections: List[SectionOutline] = []
    time_period_start: Optional[str] = None
    time_period_end: Optional[str] = None
    characters_present: List[str] = []
    
    @property
    def target_words(self) -> int:
        return sum(s.target_words for s in self.sections)


class BookOutline(BaseModel):
    """书籍大纲"""
    title: str
    subtitle: Optional[str] = None
    subject_name: str
    style: WritingStyle
    total_chapters: int
    target_total_words: int
    chapters: List[ChapterOutline] = []
    prologue: Optional[str] = None  # 前言/序
    epilogue: Optional[str] = None  # 后记
    
    @property
    def actual_total_words(self) -> int:
        return sum(c.target_words for c in self.chapters)


class GeneratedSection(BaseModel):
    """已生成的章节内容"""
    id: str
    chapter_id: str
    title: str
    content: str
    word_count: int
    generation_time: datetime
    facts_verified: bool = False
    issues: List[str] = []


class GeneratedChapter(BaseModel):
    """已生成的完整章节"""
    id: str
    outline: ChapterOutline
    sections: List[GeneratedSection] = []
    transition_paragraph: Optional[str] = None  # 与下章的过渡段落
    
    @property
    def full_content(self) -> str:
        parts = [f"# {self.outline.title}\n\n"]
        for section in self.sections:
            parts.append(f"## {section.title}\n\n")
            parts.append(section.content)
            parts.append("\n\n")
        if self.transition_paragraph:
            parts.append(self.transition_paragraph)
        return "".join(parts)
    
    @property
    def word_count(self) -> int:
        return sum(s.word_count for s in self.sections)


class BiographyBook(BaseModel):
    """完整的传记书籍"""
    id: str
    outline: BookOutline
    chapters: List[GeneratedChapter] = []
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    @property
    def full_text(self) -> str:
        """生成完整文本"""
        parts = []
        
        # 标题
        parts.append(f"# {self.outline.title}\n\n")
        if self.outline.subtitle:
            parts.append(f"**{self.outline.subtitle}**\n\n")
        parts.append(f"*{self.outline.subject_name}传*\n\n")
        parts.append("---\n\n")
        
        # 前言
        if self.outline.prologue:
            parts.append(f"## 序\n\n{self.outline.prologue}\n\n---\n\n")
        
        # 正文
        for chapter in self.chapters:
            parts.append(chapter.full_content)
            parts.append("\n\n")
        
        # 后记
        if self.outline.epilogue:
            parts.append(f"---\n\n## 后记\n\n{self.outline.epilogue}\n")
        
        return "".join(parts)
    
    @property
    def total_word_count(self) -> int:
        return sum(c.word_count for c in self.chapters)


class GlobalState(BaseModel):
    """全局状态管理"""
    book_id: str
    current_chapter_idx: int = 0
    current_section_idx: int = 0
    subject_profile: Optional[CharacterProfile] = None
    characters_mentioned: Dict[str, int] = Field(default_factory=dict)  # 人物出场次数
    current_subject_age: Optional[int] = None
    current_subject_mood: Optional[str] = None
    generated_chapter_summaries: List[str] = []  # 已生成章节的摘要
    
    def update_progress(self, chapter_idx: int, section_idx: int = 0):
        self.current_chapter_idx = chapter_idx
        self.current_section_idx = section_idx
    
    def add_chapter_summary(self, summary: str):
        self.generated_chapter_summaries.append(summary)
        # 保持最近10章的摘要
        if len(self.generated_chapter_summaries) > 10:
            self.generated_chapter_summaries = self.generated_chapter_summaries[-10:]


class InterviewMaterial(BaseModel):
    """采访素材块"""
    id: str
    source_file: str
    content: str
    chunk_index: int
    embedding: Optional[List[float]] = None
    topics: List[str] = []
    time_references: List[str] = []  # 提取的时间提及
    entities: List[str] = []  # 包含的实体


class FactCheckResult(BaseModel):
    """事实核查结果"""
    section_id: str
    is_consistent: bool
    violations: List[Dict[str, str]] = []  # 违规项列表
    suggestions: List[str] = []
    confidence: float = Field(ge=0, le=1)