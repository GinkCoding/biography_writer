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
    """时间线事件 - 增强版，包含丰富的场景细节"""
    id: str
    date: Optional[str] = None  # 格式: YYYY-MM-DD 或 YYYY-MM 或 YYYY
    date_approximate: bool = False
    season: Optional[str] = None  # 季节
    time_of_day: Optional[str] = None  # 时段（早晨/下午/夜晚）

    title: str
    description: str
    scene_description: Optional[str] = None  # 场景描写（环境、氛围）

    source_text: str  # 原始访谈文本
    source_material_id: Optional[str] = None  # 来源素材ID

    # 人物与互动
    characters_involved: List[str] = []
    subject_role: Optional[str] = None  # 传主在该事件中的角色
    character_reactions: Dict[str, str] = Field(default_factory=dict)  # 人物反应 {姓名: 反应描述}

    location: Optional[str] = None
    location_details: Optional[str] = None  # 地点细节

    # 感官细节
    sensory_details: Dict[str, List[str]] = Field(default_factory=dict)  # 感官细节 {视觉/听觉/嗅觉/触觉/味觉: [细节]}

    # 事件维度
    importance: int = Field(default=5, ge=1, le=10)  # 重要程度
    event_type: str = "life_event"  # 事件类型: life_event/turning_point/crisis/achievement/daily

    # 因果关系
    causes: List[str] = Field(default_factory=list)  # 原因/前因
    consequences: List[str] = Field(default_factory=list)  # 后果/影响
    impact_on_subject: Optional[str] = None  # 对传主的具体影响

    # 情感与主题
    emotional_tone: Optional[str] = None  # 情感基调
    themes: List[str] = Field(default_factory=list)  # 相关主题

    chapter_id: Optional[str] = None  # 关联的章节

    def get_rich_description(self) -> str:
        """获取丰富的事件描述"""
        parts = [f"【{self.title}】"]

        when = self.date or "时间不详"
        if self.season:
            when += f" ({self.season})"
        if self.time_of_day:
            when += f" {self.time_of_day}"
        parts.append(f"时间: {when}")

        if self.location:
            parts.append(f"地点: {self.location}")

        if self.characters_involved:
            parts.append(f"人物: {', '.join(self.characters_involved)}")

        parts.append(f"事件: {self.description}")

        if self.scene_description:
            parts.append(f"场景: {self.scene_description}")

        if self.impact_on_subject:
            parts.append(f"影响: {self.impact_on_subject}")

        return "\n".join(parts)


class Relationship(BaseModel):
    """人物关系"""
    source: str  # 关系主体
    target: str  # 关系对象
    relation_type: str  # 如：父亲、朋友、同事
    description: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class CharacterProfile(BaseModel):
    """人物画像 - 扩展版，支持更立体的人物刻画"""
    # 基础信息
    name: str
    aliases: List[str] = []
    birth_date: Optional[str] = None
    birth_place: Optional[str] = None
    current_residence: Optional[str] = None  # 现居地

    # 职业与教育
    occupation: List[str] = []
    education_background: List[str] = []  # 教育背景
    skills: List[str] = []  # 技能特长
    career_highlights: List[str] = []  # 职业高光时刻

    # 性格与心理
    personality_traits: List[str] = []
    personality_evolution: Dict[str, List[str]] = Field(default_factory=dict)  # 性格演变 {时期: [特征]}
    core_values: List[str] = []
    beliefs: List[str] = []  # 信念/信条
    habits: List[str] = []  # 习惯（日常习惯、工作习惯等）
    quirks: List[str] = []  # 小怪癖/独特之处

    # 外貌与行为
    physical_description: Optional[str] = None  # 外貌描述
    habitual_actions: List[str] = []  # 习惯性动作/姿态
    dressing_style: Optional[str] = None  # 穿衣风格

    # 语言与表达
    speaking_style: Optional[str] = None  # 说话风格（语速、用词特点等）
    catchphrases: List[str] = []  # 口头禅/常用语
    language_quirks: List[str] = []  # 语言特点（方言、语法习惯等）

    # 情感与人际
    emotional_patterns: Dict[str, str] = Field(default_factory=dict)  # 情感模式 {情境: 反应方式}
    relationship_patterns: Optional[str] = None  # 人际关系模式
    family_dynamics: Dict[str, str] = Field(default_factory=dict)  # 家庭动态 {成员: 关系描述}

    # 成长与转折
    growth_turning_points: List[Dict] = Field(default_factory=list)  # 成长转折点 [{age, event, impact}]
    life_philosophy: Optional[str] = None  # 人生哲学/感悟
    regrets: List[str] = []  # 遗憾/未竟之事
    proudest_moments: List[str] = []  # 最自豪的时刻

    # 时代与环境
    social_background: Optional[str] = None  # 社会背景（阶层、环境）
    era_influence: Optional[str] = None  # 时代对人物的影响

    # 关系网络
    relationships: List[Relationship] = []
    key_people: Dict[str, str] = Field(default_factory=dict)  # 关键人物 {姓名: 影响描述}

    def to_bio_summary(self) -> str:
        """生成人物小传摘要"""
        parts = [
            f"【{self.name}】",
            f"生于{self.birth_place or '某地'}，{self.birth_date or '生年不详'}",
        ]

        if self.occupation:
            parts.append(f"职业：{'、'.join(self.occupation)}")

        if self.personality_traits:
            parts.append(f"性格：{'、'.join(self.personality_traits)}")

        if self.physical_description:
            parts.append(f"外貌：{self.physical_description}")

        if self.speaking_style:
            parts.append(f"言谈：{self.speaking_style}")

        if self.life_philosophy:
            parts.append(f"人生哲学：{self.life_philosophy}")

        return "\n".join(parts)
    
    
class Timeline(BaseModel):
    """全局时间线"""
    subject: CharacterProfile
    events: List[Event] = []
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None
    
    def sort_events(self):
        """按时间排序事件"""
        self.events.sort(key=lambda e: e.date or "")


class ParagraphOutline(BaseModel):
    """段落级大纲 - 支持更精细的内容规划"""
    id: str
    order: int  # 段落顺序
    paragraph_type: str = "narrative"  # 段落类型: narrative(叙述)/dialogue(对话)/description(描写)/reflection(思考)
    content_purpose: str  # 本段的写作目的
    target_words: int = 150  # 目标字数
    key_details: List[str] = []  # 必须包含的具体细节
    sensory_focus: List[str] = []  # 重点描写的感官类型
    emotional_progression: str = ""  # 情感递进目标
    transition_from_prev: str = ""  # 与前段的衔接方式
    material_refs: List[str] = []  # 引用的素材


class SectionOutline(BaseModel):
    """小节大纲"""
    id: str
    title: str
    target_words: int
    key_events: List[str] = []  # 关联的事件ID
    content_summary: str  # 内容概要
    emotional_tone: str  # 情感基调
    material_refs: List[str] = []  # 引用的素材块ID
    paragraphs: List[ParagraphOutline] = []  # 段落级大纲（可选，用于精细控制）
    pacing: str = "moderate"  # 节奏: slow(舒缓)/moderate(适中)/fast(紧凑)/mixed(起伏)


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


class CharacterNameMapping(BaseModel):
    """人物称谓映射 - 确保称谓一致性"""
    canonical_name: str  # 标准名称（全名）
    aliases: List[str] = []  # 别名列表
    preferred_form: str  # 首选称谓形式
    first_appearance_chapter: int = 0  # 首次出现章节
    description: str = ""  # 人物简介（用于首次出现时介绍）

    def get_display_name(self, chapter_idx: int) -> str:
        """获取在指定章节的显示名称"""
        # 首次出现时可能需要全名+介绍
        if chapter_idx <= self.first_appearance_chapter:
            return self.canonical_name
        return self.preferred_form


class CharacterEvolution(BaseModel):
    """人物进化追踪 - 记录人物在书中的变化"""
    character_name: str
    chapter_snapshots: Dict[int, Dict] = Field(default_factory=dict)  # 每章的人物快照

    def add_snapshot(self, chapter_idx: int, traits: Dict):
        """添加章节快照"""
        self.chapter_snapshots[chapter_idx] = {
            "traits": traits,  # 性格特征表现
            "key_actions": [],  # 关键行为
            "relationships": {},  # 与其他人的关系状态
            "recorded_at": datetime.now().isoformat()
        }

    def get_latest_snapshot(self) -> Optional[Dict]:
        """获取最新快照"""
        if not self.chapter_snapshots:
            return None
        latest_chapter = max(self.chapter_snapshots.keys())
        return self.chapter_snapshots[latest_chapter]

    def check_consistency(self, chapter_idx: int, new_traits: Dict) -> List[str]:
        """检查人物一致性，返回冲突列表"""
        conflicts = []
        # 检查之前章节是否有矛盾的特征描述
        for prev_chapter, snapshot in self.chapter_snapshots.items():
            if prev_chapter >= chapter_idx:
                continue
            prev_traits = snapshot.get("traits", {})
            for trait, value in new_traits.items():
                if trait in prev_traits and prev_traits[trait] != value:
                    conflicts.append(f"{trait}: 第{prev_chapter}章为'{prev_traits[trait]}', 现为'{value}'")
        return conflicts


class ForeshadowingItem(BaseModel):
    """伏笔项 - 用于前后照应"""
    id: str
    content: str  # 伏笔内容
    chapter_introduced: int  # 引入章节
    section_introduced: str = ""  # 引入小节
    expected_resolution_chapter: Optional[int] = None  # 预计回收章节
    is_resolved: bool = False  # 是否已回收
    resolution_chapter: Optional[int] = None  # 实际回收章节
    resolution_content: Optional[str] = None  # 回收方式描述


class ImageryTracker(BaseModel):
    """意象追踪 - 确保核心意象的前后呼应"""
    imagery_id: str
    name: str  # 意象名称（如"老榕树"）
    first_appearance_chapter: int
    first_context: str = ""  # 首次出现的语境
    appearances: List[Dict] = Field(default_factory=list)  # 每次出现记录
    symbolic_meaning: str = ""  # 象征意义

    def record_appearance(self, chapter_idx: int, context: str, usage: str):
        """记录意象出现"""
        self.appearances.append({
            "chapter": chapter_idx,
            "context": context,
            "usage": usage,  # 用法：呼应/对比/深化等
            "recorded_at": datetime.now().isoformat()
        })


class EnhancedGlobalState(BaseModel):
    """增强版全局状态 - 支持更好的文学性和一致性"""
    book_id: str
    current_chapter_idx: int = 0
    current_section_idx: int = 0
    subject_profile: Optional[CharacterProfile] = None

    # 人物管理增强
    character_name_mappings: Dict[str, CharacterNameMapping] = Field(default_factory=dict)
    character_evolutions: Dict[str, CharacterEvolution] = Field(default_factory=dict)

    # 伏笔和意象追踪
    foreshadowings: List[ForeshadowingItem] = Field(default_factory=list)
    imagery_trackers: Dict[str, ImageryTracker] = Field(default_factory=dict)

    # 基础状态
    characters_mentioned: Dict[str, int] = Field(default_factory=dict)
    current_subject_age: Optional[int] = None
    current_subject_mood: Optional[str] = None
    generated_chapter_summaries: List[str] = Field(default_factory=list)

    # 风格一致性
    style_keywords_used: List[str] = Field(default_factory=list)  # 已使用的风格关键词
    tone_consistency: Dict[int, str] = Field(default_factory=dict)  # 每章的基调记录

    def register_character(self, name: str, aliases: List[str] = None, description: str = ""):
        """注册新人物"""
        if name not in self.character_name_mappings:
            self.character_name_mappings[name] = CharacterNameMapping(
                canonical_name=name,
                aliases=aliases or [],
                preferred_form=name,
                first_appearance_chapter=self.current_chapter_idx,
                description=description
            )
            self.character_evolutions[name] = CharacterEvolution(character_name=name)

    def get_character_display_name(self, name: str) -> str:
        """获取人物在当前章节的显示名称"""
        mapping = self.character_name_mappings.get(name)
        if mapping:
            return mapping.get_display_name(self.current_chapter_idx)
        return name

    def record_character_snapshot(self, name: str, traits: Dict):
        """记录人物章节快照"""
        if name in self.character_evolutions:
            self.character_evolutions[name].add_snapshot(self.current_chapter_idx, traits)

    def add_foreshadowing(self, content: str, expected_chapter: Optional[int] = None) -> str:
        """添加伏笔"""
        import uuid
        fs_id = str(uuid.uuid4())[:8]
        fs = ForeshadowingItem(
            id=fs_id,
            content=content,
            chapter_introduced=self.current_chapter_idx,
            expected_resolution_chapter=expected_chapter
        )
        self.foreshadowings.append(fs)
        return fs_id

    def get_unresolved_foreshadowings(self) -> List[ForeshadowingItem]:
        """获取未回收的伏笔"""
        return [fs for fs in self.foreshadowings if not fs.is_resolved]

    def resolve_foreshadowing(self, fs_id: str, resolution: str):
        """回收伏笔"""
        for fs in self.foreshadowings:
            if fs.id == fs_id:
                fs.is_resolved = True
                fs.resolution_chapter = self.current_chapter_idx
                fs.resolution_content = resolution
                break

    def register_imagery(self, name: str, context: str, symbolic_meaning: str = ""):
        """注册核心意象"""
        if name not in self.imagery_trackers:
            self.imagery_trackers[name] = ImageryTracker(
                imagery_id=name,
                name=name,
                first_appearance_chapter=self.current_chapter_idx,
                first_context=context,
                symbolic_meaning=symbolic_meaning
            )

    def record_imagery_usage(self, name: str, context: str, usage: str):
        """记录意象使用"""
        if name in self.imagery_trackers:
            self.imagery_trackers[name].record_appearance(
                self.current_chapter_idx, context, usage
            )

    def get_active_imageries(self) -> List[ImageryTracker]:
        """获取需要继续使用的核心意象（最近3章内出现过）"""
        active = []
        for img in self.imagery_trackers.values():
            if img.appearances:
                latest = max(a["chapter"] for a in img.appearances)
                if self.current_chapter_idx - latest <= 3:
                    active.append(img)
        return active

    def add_chapter_summary(self, summary: str):
        """添加章节摘要"""
        self.generated_chapter_summaries.append(summary)
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