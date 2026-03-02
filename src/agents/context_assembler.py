"""Context Agent - 创作任务书工程师

位置: 在Generation层之前
输入: 大纲、相关素材、前文内容、人物状态
输出: 结构化的创作任务书
职责: 精确组装生成所需的上下文
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from loguru import logger

from src.models import (
    BookOutline, ChapterOutline, SectionOutline,
    EnhancedGlobalState, CharacterProfile, InterviewMaterial,
    WritingStyle, ForeshadowingItem, ImageryTracker
)
from src.llm_client import LLMClient
from src.layers.data_ingestion import VectorStore
from src.utils import truncate_text


@dataclass
class ChapterTask:
    """本章核心任务"""
    conflict_summary: str = ""           # 冲突一句话
    must_complete: List[str] = field(default_factory=list)  # 必须完成
    must_avoid: List[str] = field(default_factory=list)     # 绝对不能
    antagonist_level: Optional[str] = None  # 反派层级（如适用）


@dataclass
class PreviousHook:
    """承接上文信息"""
    hook_type: str = "无"                # 钩子类型
    hook_content: str = ""               # 钩子内容
    hook_strength: str = "weak"          # 钩子强度
    reader_expectation: str = ""         # 读者期待
    opening_requirement: str = ""        # 开头必须


@dataclass
class CharacterState:
    """出场角色状态"""
    name: str
    current_status: str                  # 当前状态
    motivation: str                      # 动机
    emotional_base: str                  # 情绪底色
    speaking_style: str                  # 说话风格
    red_lines: List[str] = field(default_factory=list)  # 红线（不能写的内容）
    appearance_count: int = 0            # 出场次数


@dataclass
class SceneConstraint:
    """场景与约束"""
    location: str = ""                   # 地点
    time_period: str = ""                # 时间段
    available_abilities: List[str] = field(default_factory=list)   # 可用能力
    forbidden_abilities: List[str] = field(default_factory=list)   # 禁用能力
    era_keywords: List[str] = field(default_factory=list)          # 时代关键词


@dataclass
class StyleGuide:
    """风格指导"""
    chapter_type: str = ""               # 本章类型
    reference_samples: List[str] = field(default_factory=list)     # 参考样本
    recent_patterns: List[str] = field(default_factory=list)       # 最近模式
    chapter_suggestions: List[str] = field(default_factory=list)   # 本章建议
    sensory_focus: List[str] = field(default_factory=list)         # 感官重点


@dataclass
class ContinuityInfo:
    """连续性与伏笔"""
    time_continuity: str = ""            # 时间连贯
    location_continuity: str = ""        # 位置连贯
    emotion_continuity: str = ""         # 情绪连贯
    must_resolve_foreshadowing: List[ForeshadowingItem] = field(default_factory=list)   # 必须处理
    optional_foreshadowing: List[ForeshadowingItem] = field(default_factory=list)       # 可选伏笔
    active_imageries: List[ImageryTracker] = field(default_factory=list)                # 活跃意象


@dataclass
class QualityStrategy:
    """质量策略"""
    hook_type_suggestion: str = ""       # 章末钩子类型建议
    hook_strength_target: str = ""       # 钩子强度目标
    micro_fulfillment: List[str] = field(default_factory=list)     # 微兑现建议
    differentiation_hints: List[str] = field(default_factory=list)  # 差异化提示
    debt_status: Optional[Dict] = None   # 债务状态（如适用）


@dataclass
class ContextContract:
    """创作任务书 - 7板块结构

    参考webnovel-writer的7板块设计，适配传记写作场景：
    1. 本章核心任务
    2. 承接上文
    3. 出场角色状态
    4. 场景与约束
    5. 风格指导
    6. 连续性与伏笔
    7. 质量策略

    额外字段（由ContextAgent动态填充）：
    - materials: 检索到的素材文本
    - coverage_info: 素材覆盖率信息
    """
    chapter_task: ChapterTask = field(default_factory=ChapterTask)
    previous_hook: PreviousHook = field(default_factory=PreviousHook)
    characters: List[CharacterState] = field(default_factory=list)
    constraints: SceneConstraint = field(default_factory=SceneConstraint)
    style_guide: StyleGuide = field(default_factory=StyleGuide)
    continuity: ContinuityInfo = field(default_factory=ContinuityInfo)
    quality_strategy: QualityStrategy = field(default_factory=QualityStrategy)

    # 元数据
    chapter_id: str = ""
    chapter_title: str = ""
    section_title: str = ""
    generated_at: datetime = field(default_factory=datetime.now)
    version: str = "1.0"

    # 动态填充字段（不由__init__直接设置）
    materials: str = ""
    coverage_info: Dict = field(default_factory=dict)

    def __post_init__(self):
        """初始化后的处理"""
        # 确保materials和coverage_info有默认值
        if not hasattr(self, 'materials'):
            self.materials = ""
        if not hasattr(self, 'coverage_info'):
            self.coverage_info = {}

    def to_prompt_context(self) -> Dict[str, str]:
        """转换为生成层可用的提示词上下文"""
        return {
            "global": self._build_global_section(),
            "section": self._build_section_section(),
            "materials": self._build_materials_section(),
            "continuity": self._build_continuity_section(),
            "era": self._build_era_section(),
            "sensory": self._build_sensory_section(),
            "quality": self._build_quality_section(),
        }

    def _build_global_section(self) -> str:
        """构建全局设定部分"""
        parts = ["=== 全局设定 ==="]
        parts.append(f"本章任务: {self.chapter_task.conflict_summary}")
        if self.chapter_task.must_complete:
            parts.append(f"必须完成: {'; '.join(self.chapter_task.must_complete)}")
        if self.chapter_task.must_avoid:
            parts.append(f"绝对不能: {'; '.join(self.chapter_task.must_avoid)}")
        return "\n".join(parts)

    def _build_section_section(self) -> str:
        """构建小节部分"""
        parts = [f"=== 当前小节: {self.section_title} ==="]
        parts.append(f"章节: {self.chapter_title}")
        return "\n".join(parts)

    def _build_materials_section(self) -> str:
        """构建素材部分（由Agent填充）"""
        if self.materials:
            return f"=== 相关素材 ===\n{self.materials}"
        return "=== 相关素材 ===\n（素材内容由ContextAgent检索后填充）"

    def _build_continuity_section(self) -> str:
        """构建连续性部分"""
        parts = ["=== 上下文衔接 ==="]
        if self.previous_hook.hook_content:
            parts.append(f"上章钩子: {self.previous_hook.hook_content}")
        if self.previous_hook.reader_expectation:
            parts.append(f"读者期待: {self.previous_hook.reader_expectation}")
        if self.previous_hook.opening_requirement:
            parts.append(f"开头要求: {self.previous_hook.opening_requirement}")
        return "\n".join(parts) if len(parts) > 1 else "=== 上下文衔接 ===\n（首章无前文）"

    def _build_era_section(self) -> str:
        """构建时代背景部分"""
        parts = ["=== 时代背景 ==="]
        if self.constraints.time_period:
            parts.append(f"时间段: {self.constraints.time_period}")
        if self.constraints.era_keywords:
            parts.append(f"时代关键词: {', '.join(self.constraints.era_keywords)}")
        return "\n".join(parts)

    def _build_sensory_section(self) -> str:
        """构建感官指导部分"""
        parts = ["=== 感官描写指引 ==="]
        if self.style_guide.sensory_focus:
            parts.append(f"重点感官: {', '.join(self.style_guide.sensory_focus)}")
        return "\n".join(parts)

    def _build_quality_section(self) -> str:
        """构建质量策略部分"""
        parts = ["=== 质量策略 ==="]
        if self.quality_strategy.hook_type_suggestion:
            parts.append(f"钩子建议: {self.quality_strategy.hook_type_suggestion}")
        if self.quality_strategy.micro_fulfillment:
            parts.append(f"微兑现: {'; '.join(self.quality_strategy.micro_fulfillment)}")
        return "\n".join(parts)

    def to_markdown(self) -> str:
        """生成Markdown格式的创作任务书（用于人工查看）"""
        lines = [
            f"# 创作任务书: {self.chapter_title}",
            f"",
            f"> 生成时间: {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"> 版本: {self.version}",
            f"",
            f"## 1. 本章核心任务",
            f"",
            f"**冲突一句话**: {self.chapter_task.conflict_summary}",
            f"",
            f"**必须完成**:",
        ]
        for item in self.chapter_task.must_complete:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("**绝对不能**:")
        for item in self.chapter_task.must_avoid:
            lines.append(f"- {item}")
        if self.chapter_task.antagonist_level:
            lines.append(f"")
            lines.append(f"**反派层级**: {self.chapter_task.antagonist_level}")

        lines.extend([
            f"",
            f"## 2. 承接上文",
            f"",
            f"**上章钩子**: {self.previous_hook.hook_type} ({self.previous_hook.hook_strength})",
            f"",
            f"{self.previous_hook.hook_content}",
            f"",
            f"**读者期待**: {self.previous_hook.reader_expectation}",
            f"",
            f"**开头必须**: {self.previous_hook.opening_requirement}",
            f"",
            f"## 3. 出场角色状态",
            f"",
        ])
        for char in self.characters:
            lines.extend([
                f"### {char.name}",
                f"- 状态: {char.current_status}",
                f"- 动机: {char.motivation}",
                f"- 情绪底色: {char.emotional_base}",
                f"- 说话风格: {char.speaking_style}",
            ])
            if char.red_lines:
                lines.append(f"- 红线: {', '.join(char.red_lines)}")
            lines.append("")

        lines.extend([
            f"## 4. 场景与约束",
            f"",
            f"**地点**: {self.constraints.location}",
            f"",
            f"**时间段**: {self.constraints.time_period}",
            f"",
        ])
        if self.constraints.available_abilities:
            lines.append(f"**可用要素**: {', '.join(self.constraints.available_abilities)}")
        if self.constraints.forbidden_abilities:
            lines.append(f"**禁用要素**: {', '.join(self.constraints.forbidden_abilities)}")
        lines.extend([
            f"",
            f"## 5. 风格指导",
            f"",
            f"**本章类型**: {self.style_guide.chapter_type}",
            f"",
        ])
        if self.style_guide.reference_samples:
            lines.append(f"**参考样本**: {', '.join(self.style_guide.reference_samples)}")
        if self.style_guide.recent_patterns:
            lines.append(f"**最近模式**: {', '.join(self.style_guide.recent_patterns)}")
        if self.style_guide.chapter_suggestions:
            lines.append(f"**本章建议**:")
            for suggestion in self.style_guide.chapter_suggestions:
                lines.append(f"- {suggestion}")

        lines.extend([
            f"",
            f"## 6. 连续性与伏笔",
            f"",
            f"**时间连贯**: {self.continuity.time_continuity}",
            f"",
            f"**位置连贯**: {self.continuity.location_continuity}",
            f"",
            f"**情绪连贯**: {self.continuity.emotion_continuity}",
            f"",
        ])
        if self.continuity.must_resolve_foreshadowing:
            lines.append(f"**必须处理的伏笔**:")
            for fs in self.continuity.must_resolve_foreshadowing:
                lines.append(f"- {fs.content} (第{fs.chapter_introduced}章引入)")
            lines.append("")
        if self.continuity.active_imageries:
            lines.append(f"**活跃意象**:")
            for img in self.continuity.active_imageries:
                lines.append(f"- {img.name}: {img.symbolic_meaning}")
            lines.append("")

        lines.extend([
            f"## 7. 质量策略",
            f"",
            f"**章末钩子建议**: {self.quality_strategy.hook_type_suggestion} ({self.quality_strategy.hook_strength_target})",
            f"",
        ])
        if self.quality_strategy.micro_fulfillment:
            lines.append(f"**微兑现建议**:")
            for item in self.quality_strategy.micro_fulfillment:
                lines.append(f"- {item}")
        if self.quality_strategy.differentiation_hints:
            lines.append(f"**差异化提示**:")
            for hint in self.quality_strategy.differentiation_hints:
                lines.append(f"- {hint}")

        return "\n".join(lines)


class ContextAgent:
    """Context Agent - 创作任务书工程师

    职责:
    1. 读取大纲、状态、前文摘要
    2. 检索相关素材
    3. 分析角色状态和连续性
    4. 组装结构化的创作任务书(ContextContract)
    """

    # 感官描述关键词库
    SENSORY_KEYWORDS = {
        "visual": ["看见", "看到", "望", "瞧", "颜色", "光线", "阳光", "影子", "模样", "穿着", "表情", "眼神"],
        "auditory": ["听见", "听到", "声音", "喊道", "说", "笑声", "哭声", "音乐", "歌声", "噪音", "寂静"],
        "olfactory": ["闻到", "气味", "香味", "臭味", "气息", "味道", "烟味", "花香", "饭菜香"],
        "tactile": ["感到", "摸", "触摸", "温度", "冷", "热", "疼痛", "粗糙", "光滑", "柔软", "坚硬"],
        "gustatory": ["尝到", "味道", "甜", "苦", "辣", "酸", "咸", "好吃", "难吃"],
    }

    # 时代背景关键词映射
    ERA_HINTS = {
        "1949": ("新中国成立", ["土地改革", "抗美援朝", "社会主义改造"]),
        "1950": ("建国初期", ["百废待兴", "三大改造", "集体化运动"]),
        "1960": ("困难时期", ["三年自然灾害", "物质极度匮乏", "票证制度"]),
        "1966": ("文革时期", ["社会动荡", "上山下乡", "个人命运起伏"]),
        "1976": ("转折之年", ["文革结束", "拨乱反正", "恢复高考"]),
        "1978": ("改革开放", ["十一届三中全会", "家庭联产承包", "思想解放"]),
        "1980": ("改革初期", ["特区设立", "价格双轨制", "万元户涌现"]),
        "1984": ("城市改革", ["沿海开放城市", "国企改革", "商品经济"]),
        "1992": ("南巡讲话", ["市场经济确立", "下海热潮", "开发浦东"]),
        "1997": ("香港回归", ["国企改革攻坚", "亚洲金融危机", "互联网起步"]),
        "2001": ("入世元年", ["WTO", "申奥成功", "房地产起步"]),
        "2008": ("金融危机", ["奥运会", "四万亿", "房价飙升"]),
        "2010": ("移动互联网", ["微博兴起", "创业热潮", "O2O"]),
    }

    def __init__(self, llm: LLMClient, vector_store: VectorStore):
        self.llm = llm
        self.vector_store = vector_store

    async def assemble_contract(
        self,
        section: SectionOutline,
        chapter: ChapterOutline,
        outline: BookOutline,
        global_state: EnhancedGlobalState,
        previous_section_summary: Optional[str] = None,
        previous_chapter_meta: Optional[Dict] = None
    ) -> ContextContract:
        """组装完整的创作任务书

        Args:
            section: 当前小节大纲
            chapter: 当前章节大纲
            outline: 全书大纲
            global_state: 全局状态
            previous_section_summary: 上一节摘要
            previous_chapter_meta: 上一章的元数据（钩子、结束状态等）

        Returns:
            ContextContract: 结构化的创作任务书
        """
        logger.info(f"ContextAgent: 开始组装创作任务书 - {chapter.title}/{section.title}")

        contract = ContextContract(
            chapter_id=chapter.id,
            chapter_title=chapter.title,
            section_title=section.title
        )

        # 1. 组装本章核心任务
        contract.chapter_task = self._build_chapter_task(section, chapter, outline)

        # 2. 组装承接上文
        contract.previous_hook = self._build_previous_hook(
            previous_chapter_meta, previous_section_summary, global_state
        )

        # 3. 组装出场角色状态
        contract.characters = self._build_character_states(
            chapter, global_state
        )

        # 4. 组装场景与约束
        contract.constraints = self._build_scene_constraints(
            chapter, section, outline
        )

        # 5. 组装风格指导
        contract.style_guide = self._build_style_guide(
            outline.style, section, global_state
        )

        # 6. 组装连续性与伏笔
        contract.continuity = self._build_continuity_info(
            global_state, previous_section_summary
        )

        # 7. 组装质量策略
        contract.quality_strategy = self._build_quality_strategy(
            section, chapter, global_state
        )

        logger.info(f"ContextAgent: 创作任务书组装完成 - {chapter.title}")
        return contract

    def _build_chapter_task(
        self,
        section: SectionOutline,
        chapter: ChapterOutline,
        outline: BookOutline
    ) -> ChapterTask:
        """构建本章核心任务"""
        # 从section和chapter中提取核心任务信息
        conflict_summary = section.content_summary[:100] if section.content_summary else "继续叙述传主经历"

        must_complete = []
        if section.key_events:
            must_complete.append(f"叙述关键事件: {', '.join(section.key_events[:3])}")
        must_complete.append(f"达成情感基调: {section.emotional_tone}")
        must_complete.append(f"完成目标字数: {section.target_words}字")

        must_avoid = [
            "虚构未在素材中出现的具体人名、地名",
            "编造具体的数字和数据",
            "使用'待补充'、'此处需要展开'等占位符",
            "套路化意象（尘埃光柱、凉茶苦甘等）",
        ]

        return ChapterTask(
            conflict_summary=conflict_summary,
            must_complete=must_complete,
            must_avoid=must_avoid
        )

    def _build_previous_hook(
        self,
        previous_chapter_meta: Optional[Dict],
        previous_section_summary: Optional[str],
        global_state: EnhancedGlobalState
    ) -> PreviousHook:
        """构建承接上文信息"""
        hook = PreviousHook()

        # 从上一章元数据中提取钩子信息
        if previous_chapter_meta:
            hook_data = previous_chapter_meta.get("hook", {})
            hook.hook_type = hook_data.get("type", "无")
            hook.hook_content = hook_data.get("content", "")
            hook.hook_strength = hook_data.get("strength", "weak")

            ending_data = previous_chapter_meta.get("ending", {})
            hook.emotional_base = ending_data.get("emotion", "")

        # 基于前文摘要推断读者期待
        if previous_section_summary:
            hook.reader_expectation = f"了解{previous_section_summary[:50]}...的后续发展"
            hook.opening_requirement = f"自然承接: {truncate_text(previous_section_summary, 100)}"
        else:
            # 首章情况
            hook.hook_type = "首章"
            hook.hook_content = "传记开篇，需要建立传主形象和时代背景"
            hook.reader_expectation = "了解传主是谁，生活在什么时代"
            hook.opening_requirement = "开篇点题，介绍传主和时代背景"

        return hook

    def _build_character_states(
        self,
        chapter: ChapterOutline,
        global_state: EnhancedGlobalState
    ) -> List[CharacterState]:
        """构建出场角色状态"""
        characters = []

        # 传主始终是核心角色
        subject = global_state.subject_profile
        if subject:
            subject_state = CharacterState(
                name=subject.name,
                current_status=self._infer_subject_status(global_state),
                motivation=self._infer_subject_motivation(subject, global_state),
                emotional_base=global_state.current_subject_mood or "平静",
                speaking_style=subject.speaking_style or "未设定",
                red_lines=["不能虚构未提及的具体事件", "不能编造对话内容"],
                appearance_count=global_state.characters_mentioned.get(subject.name, 0)
            )
            characters.append(subject_state)

        # 本章出场的其他角色
        for char_name in chapter.characters_present:
            if char_name == subject.name if subject else True:
                continue

            # 查找角色信息
            char_mapping = global_state.character_name_mappings.get(char_name)
            if char_mapping:
                char_state = CharacterState(
                    name=char_name,
                    current_status="本章出场",
                    motivation="配合叙事需要",
                    emotional_base="根据场景设定",
                    speaking_style="根据素材描述",
                    appearance_count=global_state.characters_mentioned.get(char_name, 0)
                )
                characters.append(char_state)

        return characters

    def _infer_subject_status(self, global_state: EnhancedGlobalState) -> str:
        """推断传主当前状态"""
        age = global_state.current_subject_age
        if age:
            return f"{age}岁"
        return "年龄待确定"

    def _infer_subject_motivation(
        self,
        subject: CharacterProfile,
        global_state: EnhancedGlobalState
    ) -> str:
        """推断传主当前动机"""
        # 基于当前章节和人物画像推断
        summaries = global_state.generated_chapter_summaries
        if summaries:
            return f"基于前文发展，继续{subject.name}的人生叙述"
        return f"开启{subject.name}的传记叙述"

    def _build_scene_constraints(
        self,
        chapter: ChapterOutline,
        section: SectionOutline,
        outline: BookOutline
    ) -> SceneConstraint:
        """构建场景与约束"""
        constraint = SceneConstraint()

        # 时间段
        if chapter.time_period_start and chapter.time_period_end:
            constraint.time_period = f"{chapter.time_period_start} 至 {chapter.time_period_end}"
        elif chapter.time_period_start:
            constraint.time_period = chapter.time_period_start

        # 时代关键词
        year = chapter.time_period_start[:4] if chapter.time_period_start and len(chapter.time_period_start) >= 4 else ""
        if year:
            for decade, (era_name, keywords) in self.ERA_HINTS.items():
                if year.startswith(decade[:3]):
                    constraint.era_keywords = keywords
                    break

        # 可用要素（基于素材）
        constraint.available_abilities = [
            "具体的时间、地点信息",
            "采访素材中的对话和细节",
            "时代背景特征",
            "人物行为描写",
        ]

        # 禁用要素
        constraint.forbidden_abilities = [
            "虚构的具体人名",
            "编造的数字数据",
            "未经验证的历史事件",
        ]

        return constraint

    def _build_style_guide(
        self,
        style: WritingStyle,
        section: SectionOutline,
        global_state: EnhancedGlobalState
    ) -> StyleGuide:
        """构建风格指导"""
        guide = StyleGuide()

        # 本章类型
        pacing_map = {
            "slow": "舒缓叙述型",
            "moderate": "平衡叙述型",
            "fast": "紧凑推进型",
            "mixed": "起伏变化型"
        }
        guide.chapter_type = pacing_map.get(section.pacing, "平衡叙述型")

        # 感官重点
        style_sensory_map = {
            WritingStyle.DOCUMENTARY: ["视觉", "听觉"],
            WritingStyle.LITERARY: ["视觉", "触觉", "嗅觉"],
            WritingStyle.INVESTIGATIVE: ["视觉", "听觉"],
            WritingStyle.MEMOIR: ["触觉", "嗅觉", "味觉"],
            WritingStyle.INSPIRATIONAL: ["视觉", "听觉"],
        }
        guide.sensory_focus = style_sensory_map.get(style, ["视觉"])

        # 本章建议
        guide.chapter_suggestions = [
            f"保持{style.value}风格的一致性",
            "每300字包含至少1个具体时间、地点或细节",
            "通过具体行为展现人物心理，避免空洞标签",
        ]

        return guide

    def _build_continuity_info(
        self,
        global_state: EnhancedGlobalState,
        previous_section_summary: Optional[str]
    ) -> ContinuityInfo:
        """构建连续性与伏笔信息"""
        continuity = ContinuityInfo()

        # 时间连贯
        age = global_state.current_subject_age
        if age:
            continuity.time_continuity = f"传主当前{age}岁"
        else:
            continuity.time_continuity = "时间线根据素材推断"

        # 情绪连贯
        mood = global_state.current_subject_mood
        if mood:
            continuity.emotion_continuity = f"延续{mood}的情绪基调"
        else:
            continuity.emotion_continuity = "根据场景自然过渡"

        # 获取未回收的伏笔
        unresolved = global_state.get_unresolved_foreshadowings()
        current_chapter = global_state.current_chapter_idx

        # 分类伏笔
        for fs in unresolved:
            if fs.expected_resolution_chapter and fs.expected_resolution_chapter <= current_chapter:
                continuity.must_resolve_foreshadowing.append(fs)
            else:
                continuity.optional_foreshadowing.append(fs)

        # 限制可选伏笔数量
        continuity.optional_foreshadowing = continuity.optional_foreshadowing[:5]

        # 活跃意象
        continuity.active_imageries = global_state.get_active_imageries()

        return continuity

    def _build_quality_strategy(
        self,
        section: SectionOutline,
        chapter: ChapterOutline,
        global_state: EnhancedGlobalState
    ) -> QualityStrategy:
        """构建质量策略"""
        strategy = QualityStrategy()

        # 钩子建议
        is_last_section = section == chapter.sections[-1] if chapter.sections else True
        if is_last_section and chapter.order < 99:  # 假设有较多章节
            strategy.hook_type_suggestion = "承上启下"
            strategy.hook_strength_target = "medium"
        else:
            strategy.hook_type_suggestion = "自然收束"
            strategy.hook_strength_target = "weak"

        # 微兑现建议
        strategy.micro_fulfillment = [
            "回应前文提及的细节",
            "展现人物的小变化",
            "埋设下一章的线索",
        ]

        # 差异化提示
        strategy.differentiation_hints = [
            "避免与最近章节使用相同的开头方式",
            "尝试不同的感官描写角度",
        ]

        return strategy

    async def retrieve_materials(
        self,
        section: SectionOutline,
        chapter: ChapterOutline,
        n_results: int = 10
    ) -> Tuple[str, Dict]:
        """检索相关素材

        Returns:
            (materials_text, coverage_info)
        """
        # 构建多个检索查询
        queries = [
            f"{chapter.title} {section.title} {section.content_summary}",
            f"{chapter.time_period_start or ''} {chapter.time_period_end or ''} {section.key_events[0] if section.key_events else ''}",
            section.content_summary,
        ]

        all_results = []
        for query in queries:
            if query.strip():
                results = await self._search_materials_async(query, n_results=n_results)
                all_results.extend(results)

        # 按相似度排序并去重
        all_results.sort(key=lambda x: x[1], reverse=True)

        seen_ids = set()
        unique_materials = []
        for m, score in all_results:
            if m.id not in seen_ids:
                seen_ids.add(m.id)
                unique_materials.append((m, score))

        # 限制数量
        unique_materials = unique_materials[:n_results]

        # 计算覆盖率
        high_confidence = len([s for m, s in unique_materials if s > 0.7])
        medium_confidence = len([s for m, s in unique_materials if 0.5 <= s <= 0.7])
        coverage_info = {
            "total_materials": len(unique_materials),
            "high_confidence": high_confidence,
            "medium_confidence": medium_confidence,
            "coverage_ratio": min(len(unique_materials) / 5, 1.0),
        }

        if coverage_info["coverage_ratio"] < 0.4:
            coverage_info["status"] = "偏低"
        elif coverage_info["coverage_ratio"] < 0.7:
            coverage_info["status"] = "一般"
        else:
            coverage_info["status"] = "充足"

        # 构建素材文本
        material_texts = []
        for i, (m, score) in enumerate(unique_materials, 1):
            content = truncate_text(m.content, 400)
            material_texts.append(
                f"[素材{i}] 来源: {m.source_file} (相关度: {score:.2f})\n"
                f"内容: {content}\n"
            )

        materials_text = "\n".join(material_texts) if material_texts else "（未检索到相关素材）"

        return materials_text, coverage_info

    async def _search_materials_async(
        self,
        query: str,
        n_results: int = 10,
    ) -> List[Tuple[InterviewMaterial, float]]:
        """异步安全检索，避免在事件循环里调用同步 `search`。"""
        if not query.strip():
            return []

        try:
            hybrid_results = await self.vector_store.hybrid_search(
                query=query,
                n_results=n_results,
                enable_rerank=False,
            )
            if hybrid_results:
                converted: List[Tuple[InterviewMaterial, float]] = []
                for item in hybrid_results:
                    score = float(item.rrf_score or item.vector_score or item.bm25_score or item.rerank_score or 0.0)
                    converted.append((item.material, score))
                return converted
        except Exception as exc:
            logger.warning(f"ContextAgent混合检索失败，回退向量检索: {exc}")

        try:
            vector_hits = self.vector_store.vector_search(query, top_k=n_results)
            if not vector_hits:
                return []
            material_ids = [material_id for material_id, _ in vector_hits]
            materials_map = self.vector_store._get_materials_by_ids(material_ids)
            return [
                (materials_map[material_id], score)
                for material_id, score in vector_hits
                if material_id in materials_map
            ]
        except Exception as exc:
            logger.warning(f"ContextAgent向量检索回退失败: {exc}")
            return []

    def analyze_sensory_details(self, materials_text: str) -> Dict[str, List[str]]:
        """分析素材中的感官描述细节"""
        sensory_found = {k: [] for k in self.SENSORY_KEYWORDS.keys()}

        for material_line in materials_text.split('\n'):
            if material_line.startswith('内容:'):
                content = material_line[3:].strip()
                for sense_type, keywords in self.SENSORY_KEYWORDS.items():
                    for keyword in keywords:
                        if keyword in content and keyword not in sensory_found[sense_type]:
                            idx = content.find(keyword)
                            start = max(0, idx - 15)
                            end = min(len(content), idx + 20)
                            context = content[start:end]
                            sensory_found[sense_type].append(context)
                            break

        return sensory_found
