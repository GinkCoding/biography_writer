"""渐进式上下文加载模块 (Progressive Context Loading L0-L3)

基于webnovel-writer项目的ContextManager设计，为传记写作场景实现四级渐进式上下文加载策略：
- L0: 最小化加载（系统默认状态）
- L1: 最小必需集合（仅加载当前小节相关素材）- 默认
- L2: 条件扩展集合（需要连贯性检查时才加载前文）
- L3: 可选/完整集合（全文审校时加载所有内容）
"""

import asyncio
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from loguru import logger

from src.llm_client import LLMClient
from src.models import (
    BookOutline, ChapterOutline, SectionOutline,
    WritingStyle, InterviewMaterial, CharacterProfile,
    GeneratedSection, GeneratedChapter
)
from src.layers.data_ingestion import VectorStore
from src.utils import count_chinese_words, truncate_text, estimate_tokens


class ContextLevel(Enum):
    """上下文加载级别"""
    L0_MINIMAL = "minimal"           # 最小化，仅系统提示
    L1_ESSENTIAL = "essential"       # 最小必需，默认级别
    L2_EXTENDED = "extended"         # 条件扩展，用于连贯性检查
    L3_COMPLETE = "complete"         # 完整集合，用于全文审校


@dataclass
class TokenBudget:
    """Token预算分配"""
    total: int = 8000
    system_prompt: int = 1000
    context: int = 4000
    generation: int = 3000

    def __post_init__(self):
        # 确保预算总和不超过total
        used = self.system_prompt + self.context + self.generation
        if used > self.total:
            # 优先保证generation，其次是context
            excess = used - self.total
            if excess <= self.context - 2000:
                self.context -= excess
            else:
                excess -= (self.context - 2000)
                self.context = 2000
                self.system_prompt = max(500, self.system_prompt - excess)


@dataclass
class ContextPriority:
    """上下文优先级配置"""
    recency_weight: float = 0.4       # 近期优先权重
    frequency_weight: float = 0.3     # 频次加权权重
    risk_weight: float = 0.3          # 风险信号权重
    max_recent_sections: int = 3      # 最大近期小节数
    max_frequent_entities: int = 10   # 最大高频实体数


@dataclass
class LoadedContext:
    """已加载的上下文数据"""
    # 基础上下文
    global_context: str = ""          # 全局设定
    section_context: str = ""         # 当前小节大纲
    materials_context: str = ""       # 相关素材
    continuity_context: str = ""      # 前文衔接
    era_context: str = ""             # 时代背景
    sensory_context: str = ""         # 感官引导

    # 扩展上下文 (L2+)
    chapter_sections: List[str] = field(default_factory=list)  # 本章其他小节
    character_timeline: Dict[str, List[str]] = field(default_factory=dict)  # 人物时间线
    previous_chapter_summaries: List[str] = field(default_factory=list)  # 前章摘要

    # 完整上下文 (L3)
    all_chapters_content: List[str] = field(default_factory=list)  # 所有章节内容
    full_character_profiles: Dict[str, str] = field(default_factory=dict)  # 完整人物档案
    conflict_warnings: List[str] = field(default_factory=list)  # 冲突警告

    # 元数据
    coverage_info: Dict[str, Any] = field(default_factory=dict)
    loaded_level: ContextLevel = ContextLevel.L1_ESSENTIAL
    token_usage: Dict[str, int] = field(default_factory=dict)


class ProgressiveContextAssembler:
    """渐进式上下文组装器

    实现L0-L3四级渐进式上下文加载策略，支持Token预算管理和上下文优先级排序。
    """

    # 感官描述关键词库
    SENSORY_KEYWORDS = {
        "visual": ["看见", "看到", "望", "瞧", "颜色", "光线", "阳光", "影子", "模样", "穿着", "表情", "眼神"],
        "auditory": ["听见", "听到", "声音", "喊道", "说", "笑声", "哭声", "音乐", "歌声", "噪音", "寂静"],
        "olfactory": ["闻到", "气味", "香味", "臭味", "气息", "味道", "烟味", "花香", "饭菜香"],
        "tactile": ["感到", "摸", "触摸", "温度", "冷", "热", "疼痛", "粗糙", "光滑", "柔软", "坚硬"],
        "gustatory": ["尝到", "味道", "甜", "苦", "辣", "酸", "咸", "好吃", "难吃"],
    }

    def __init__(
        self,
        llm: LLMClient,
        vector_store: VectorStore,
        budget: Optional[TokenBudget] = None,
        priority: Optional[ContextPriority] = None
    ):
        self.llm = llm
        self.vector_store = vector_store
        self.budget = budget or TokenBudget()
        self.priority = priority or ContextPriority()

        # 缓存
        self._chapter_cache: Dict[str, List[GeneratedSection]] = {}
        self._entity_frequency: Dict[str, int] = {}
        self._risk_signals: List[Dict] = []

    async def assemble_context(
        self,
        section: SectionOutline,
        chapter: ChapterOutline,
        outline: BookOutline,
        global_state: Dict[str, Any],
        level: ContextLevel = ContextLevel.L1_ESSENTIAL,
        previous_section_summary: Optional[str] = None,
        generated_sections: Optional[List[GeneratedSection]] = None
    ) -> LoadedContext:
        """根据指定级别组装上下文

        Args:
            section: 当前小节大纲
            chapter: 当前章节大纲
            outline: 书籍大纲
            global_state: 全局状态
            level: 上下文加载级别
            previous_section_summary: 上一节摘要
            generated_sections: 已生成的章节内容（用于L2+）

        Returns:
            LoadedContext: 加载的上下文数据
        """
        logger.info(f"开始组装上下文 [级别: {level.value}] - {chapter.title}/{section.title}")

        context = LoadedContext(loaded_level=level)

        # L0-L3 都包含的基础上下文
        context.global_context = self._build_global_context(outline, global_state)
        context.section_context = self._build_section_context(section, chapter)

        # L1+ 加载素材
        if level.value >= ContextLevel.L1_ESSENTIAL.value:
            context.materials_context, context.coverage_info = await self._retrieve_materials_enhanced(
                section, chapter, budget=self.budget.context // 3
            )
            context.era_context = self._build_era_context_enhanced(chapter)
            context.sensory_context = self._build_sensory_guidance(
                self._analyze_sensory_details(context.materials_context),
                outline.style
            )

        # L1+ 加载连续性上下文
        context.continuity_context = self._build_continuity_context(
            previous_section_summary, global_state, level
        )

        # L2+ 加载扩展上下文
        if level.value >= ContextLevel.L2_EXTENDED.value:
            context.chapter_sections = await self._load_chapter_sections(
                chapter, section, generated_sections, budget=self.budget.context // 4
            )
            context.character_timeline = await self._load_character_timeline(
                section, chapter, outline, budget=self.budget.context // 4
            )
            context.previous_chapter_summaries = self._load_previous_chapter_summaries(
                chapter, global_state, max_count=3
            )

        # L3 加载完整上下文
        if level.value >= ContextLevel.L3_COMPLETE.value:
            context.all_chapters_content = await self._load_all_chapters_content(
                outline, budget=self.budget.context // 2
            )
            context.full_character_profiles = await self._load_full_character_profiles(
                outline, budget=self.budget.context // 4
            )
            context.conflict_warnings = self._detect_conflict_warnings(context)

        # 计算token使用情况
        context.token_usage = self._calculate_token_usage(context)

        logger.info(f"上下文组装完成 - Token使用: {context.token_usage}")
        return context

    def _build_global_context(self, outline: BookOutline, global_state: Dict[str, Any]) -> str:
        """构建全局上下文"""
        subject = global_state.get("subject_name", "传主")
        age = global_state.get("subject_age", "未知")

        theme_desc = ""
        if outline.chapters and outline.chapters[0].summary:
            theme_desc = outline.chapters[0].summary

        return f"""=== 全局设定 ===
传记标题: {outline.title}
传主姓名: {subject}
当前年龄: {age}岁
写作风格: {outline.style.value}
整体进度: {global_state.get('chapter_progress', '')}
传记主题: {theme_desc or '基于真实采访素材撰写的个人传记'}
"""

    def _build_section_context(self, section: SectionOutline, chapter: ChapterOutline) -> str:
        """构建小节上下文"""
        events_str = ', '.join(section.key_events) if section.key_events else '基于采访素材展开'

        return f"""=== 当前小节大纲 ===
章节: {chapter.title} (第{chapter.order}章)
时间范围: {chapter.time_period_start or '待定'} 至 {chapter.time_period_end or '待定'}
小节: {section.title}
目标字数: {section.target_words}字
内容概要: {section.content_summary}
情感基调: {section.emotional_tone}
关联事件: {events_str}
"""

    async def _retrieve_materials_enhanced(
        self,
        section: SectionOutline,
        chapter: ChapterOutline,
        budget: int
    ) -> Tuple[str, Dict[str, Any]]:
        """增强版素材检索 - 多路召回策略"""
        queries = [
            f"{chapter.title} {section.title} {section.content_summary}",
            f"{chapter.time_period_start} {chapter.time_period_end} {section.key_events[0] if section.key_events else ''}",
            section.content_summary,
        ]

        all_results = []
        for query in queries:
            if query.strip():
                results = self.vector_store.search(query, n_results=8)
                all_results.extend(results)

        # 按相似度排序并去重
        all_results.sort(key=lambda x: x[1], reverse=True)

        seen_ids: Set[str] = set()
        unique_materials: List[Tuple[InterviewMaterial, float]] = []
        for m, score in all_results:
            if m.id not in seen_ids:
                seen_ids.add(m.id)
                unique_materials.append((m, score))

        # 根据预算限制数量
        max_materials = min(10, budget // 400)
        unique_materials = unique_materials[:max_materials]

        # 计算素材覆盖率
        high_confidence = len([s for m, s in unique_materials if s > 0.7])
        medium_confidence = len([s for m, s in unique_materials if 0.5 <= s <= 0.7])
        coverage_info = {
            "total_materials": len(unique_materials),
            "high_confidence": high_confidence,
            "medium_confidence": medium_confidence,
            "coverage_ratio": min(len(unique_materials) / 5, 1.0),
        }

        if not unique_materials:
            coverage_info["status"] = "严重不足"
            return """=== 相关素材 ===
【⚠️ 严重警告】当前小节缺乏直接对应的采访素材。请基于已有章节上下文和时代背景进行合理推演，但必须：
1. 不虚构具体的人名、地名、机构名
2. 不编造具体的数字和数据
3. 如需补充细节，使用"据回忆"、"大约是"等模糊表述
4. 禁止使用"待补充"、"此处需要展开"等占位符
""", coverage_info

        if coverage_info["coverage_ratio"] < 0.4:
            coverage_info["status"] = "偏低"
        elif coverage_info["coverage_ratio"] < 0.7:
            coverage_info["status"] = "一般"
        else:
            coverage_info["status"] = "充足"

        material_texts = []
        for i, (m, score) in enumerate(unique_materials, 1):
            content = truncate_text(m.content, 400)
            material_texts.append(
                f"[素材{i}] 来源: {m.source_file} (相关度: {score:.2f})\n"
                f"内容: {content}\n"
            )

        coverage_hint = f"""
【素材覆盖率】{coverage_info['status']}（共{len(unique_materials)}条素材，高相关度{high_confidence}条）
"""

        materials_text = "=== 相关素材（必须引用其中的具体细节）===\n" + "\n".join(material_texts) + coverage_hint

        return materials_text, coverage_info

    def _build_continuity_context(
        self,
        previous_summary: Optional[str],
        global_state: Dict[str, Any],
        level: ContextLevel
    ) -> str:
        """构建上下文衔接信息"""
        parts = ["=== 上下文衔接 ==="]

        # 上一节摘要
        if previous_summary:
            parts.append(f"上一节结尾:\n{truncate_text(previous_summary, 200)}")

        # L1+ 加载更多摘要
        if level.value >= ContextLevel.L1_ESSENTIAL.value:
            summaries = global_state.get("previous_summaries", [])
            if summaries:
                parts.append(f"前几章脉络:\n" + " → ".join(summaries[-3:]))

            frequent_chars = global_state.get("frequent_characters", [])
            if frequent_chars:
                char_list = ", ".join([f"{name}({count}次)" for name, count in frequent_chars[:5]])
                parts.append(f"活跃人物: {char_list}")

        # L2+ 加载风险信号
        if level.value >= ContextLevel.L2_EXTENDED.value:
            risk_signals = global_state.get("continuity_risks", [])
            if risk_signals:
                parts.append("\n【连贯性风险】")
                for risk in risk_signals[:3]:
                    parts.append(f"  - {risk}")

        return "\n".join(parts)

    def _build_era_context_enhanced(self, chapter: ChapterOutline) -> str:
        """构建时代背景上下文"""
        if not chapter.time_period_start:
            return """=== 时代背景 ===
【提示】本章未明确指定时间段，请根据上下文推断或保持模糊处理。
避免编造具体的历史事件年份。
"""

        year = chapter.time_period_start[:4] if len(chapter.time_period_start) >= 4 else ""

        era_hints = {
            "1949": ("新中国成立", "土地改革，抗美援朝，社会主义改造"),
            "1950": ("建国初期", "百废待兴，三大改造，集体化运动"),
            "1960": ("困难时期", "三年自然灾害，物质极度匮乏，票证制度"),
            "1966": ("文革时期", "社会动荡，上山下乡，个人命运起伏"),
            "1976": ("转折之年", "文革结束，拨乱反正，恢复高考"),
            "1978": ("改革开放", "十一届三中全会，家庭联产承包，思想解放"),
            "1980": ("改革初期", "特区设立，价格双轨制，万元户涌现"),
            "1984": ("城市改革", "沿海开放城市，国企改革，商品经济"),
            "1992": ("南巡讲话", "市场经济确立，下海热潮，开发浦东"),
            "1997": ("香港回归", "国企改革攻坚，亚洲金融危机，互联网起步"),
            "2001": ("入世元年", "WTO，申奥成功，房地产起步"),
            "2008": ("金融危机", "奥运会，四万亿，房价飙升"),
            "2010": ("移动互联网", "微博兴起，创业热潮，O2O"),
        }

        era_desc = ""
        era_keywords = ""
        for decade, (era_name, keywords) in era_hints.items():
            if year.startswith(decade[:3]):
                era_desc = era_name
                era_keywords = keywords
                break

        if not era_desc:
            era_desc = f"{year}年代"
            era_keywords = "请参考历史资料"

        return f"""=== 时代背景（写作时必须融入）===
时间: {year}年代
时代特征: {era_desc}
关键元素: {era_keywords}

【写作要求】
1. 必须结合当时的社会大环境描述传主的经历
2. 可提及当时的物价水平、工资标准、流行文化等具体细节
3. 将个人命运与时代变迁相结合
4. 禁止使用"中国社会发展的重要时期"等空泛表述
"""

    def _analyze_sensory_details(self, materials_text: str) -> Dict[str, List[str]]:
        """分析素材中的感官描述细节"""
        sensory_found: Dict[str, List[str]] = {k: [] for k in self.SENSORY_KEYWORDS.keys()}

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

    def _build_sensory_guidance(
        self,
        sensory_details: Dict[str, List[str]],
        style: WritingStyle
    ) -> str:
        """构建感官描写引导"""
        parts = ["=== 感官描写指引 ==="]

        # 从素材中提取的感官细节
        found_any = False
        type_names = {
            "visual": "视觉", "auditory": "听觉", "olfactory": "嗅觉",
            "tactile": "触觉", "gustatory": "味觉"
        }

        for sense_type, contexts in sensory_details.items():
            if contexts:
                found_any = True
                type_name = type_names.get(sense_type, sense_type)
                parts.append(f"【{type_name}细节素材】")
                for ctx in contexts[:3]:
                    parts.append(f"  - ...{ctx}...")

        if not found_any:
            parts.append("【提示】当前素材中感官描述较少，建议结合时代背景补充具体感官细节。")

        parts.append("\n【写作要求】")
        parts.append("1. 每300字至少包含1-2处感官细节描写")
        parts.append("2. 优先使用素材中已有的感官线索")
        parts.append("3. 结合时代背景补充合理的感官信息")
        parts.append("4. 避免套路化感官描写，追求具体独特")

        return "\n".join(parts)

    async def _load_chapter_sections(
        self,
        chapter: ChapterOutline,
        current_section: SectionOutline,
        generated_sections: Optional[List[GeneratedSection]],
        budget: int
    ) -> List[str]:
        """加载本章其他小节内容（用于连贯性检查）"""
        if not generated_sections:
            return []

        sections_text = []
        total_tokens = 0

        for section in generated_sections:
            section_text = f"【{section.title}】\n{truncate_text(section.content, 300)}\n"
            section_tokens = estimate_tokens(section_text)

            if total_tokens + section_tokens > budget:
                break

            sections_text.append(section_text)
            total_tokens += section_tokens

        return sections_text

    async def _load_character_timeline(
        self,
        section: SectionOutline,
        chapter: ChapterOutline,
        outline: BookOutline,
        budget: int
    ) -> Dict[str, List[str]]:
        """加载人物时间线（用于连贯性检查）"""
        # 从章节人物列表中提取
        characters = chapter.characters_present or []
        timeline: Dict[str, List[str]] = {}

        for char in characters[:5]:  # 限制人物数量
            # 搜索该人物的相关素材
            results = self.vector_store.search(char, n_results=5)
            events = []
            total_tokens = 0

            for m, score in results:
                if score > 0.5:
                    event_text = truncate_text(m.content, 200)
                    event_tokens = estimate_tokens(event_text)

                    if total_tokens + event_tokens > budget // len(characters):
                        break

                    events.append(event_text)
                    total_tokens += event_tokens

            if events:
                timeline[char] = events

        return timeline

    def _load_previous_chapter_summaries(
        self,
        chapter: ChapterOutline,
        global_state: Dict[str, Any],
        max_count: int = 3
    ) -> List[str]:
        """加载前章摘要"""
        summaries = global_state.get("previous_summaries", [])
        return summaries[-max_count:] if summaries else []

    async def _load_all_chapters_content(
        self,
        outline: BookOutline,
        budget: int
    ) -> List[str]:
        """加载所有章节内容（L3级别）"""
        # 这里应该从持久化存储中加载
        # 简化实现：返回章节大纲信息
        chapters_text = []
        total_tokens = 0

        for ch in outline.chapters:
            ch_text = f"第{ch.order}章《{ch.title}》: {truncate_text(ch.summary, 200)}\n"
            ch_tokens = estimate_tokens(ch_text)

            if total_tokens + ch_tokens > budget:
                break

            chapters_text.append(ch_text)
            total_tokens += ch_tokens

        return chapters_text

    async def _load_full_character_profiles(
        self,
        outline: BookOutline,
        budget: int
    ) -> Dict[str, str]:
        """加载完整人物档案（L3级别）"""
        # 简化实现：从大纲中提取人物信息
        profiles: Dict[str, str] = {}
        # 实际实现应该从数据库或文件中加载完整的人物档案
        return profiles

    def _detect_conflict_warnings(self, context: LoadedContext) -> List[str]:
        """检测可能的冲突警告"""
        warnings = []

        # 检查时间线冲突
        # 检查人物关系冲突
        # 检查事件描述冲突

        return warnings

    def _calculate_token_usage(self, context: LoadedContext) -> Dict[str, int]:
        """计算各部分的token使用量"""
        usage = {
            "global": estimate_tokens(context.global_context),
            "section": estimate_tokens(context.section_context),
            "materials": estimate_tokens(context.materials_context),
            "continuity": estimate_tokens(context.continuity_context),
            "era": estimate_tokens(context.era_context),
            "sensory": estimate_tokens(context.sensory_context),
        }

        if context.chapter_sections:
            usage["chapter_sections"] = sum(estimate_tokens(s) for s in context.chapter_sections)

        if context.character_timeline:
            usage["character_timeline"] = sum(
                sum(estimate_tokens(e) for e in events)
                for events in context.character_timeline.values()
            )

        if context.previous_chapter_summaries:
            usage["previous_chapters"] = sum(
                estimate_tokens(s) for s in context.previous_chapter_summaries
            )

        if context.all_chapters_content:
            usage["all_chapters"] = sum(estimate_tokens(s) for s in context.all_chapters_content)

        usage["total"] = sum(usage.values())
        return usage

    def to_prompt_context(self, loaded_context: LoadedContext) -> Dict[str, str]:
        """将LoadedContext转换为生成器需要的prompt格式"""
        result = {
            "global": loaded_context.global_context,
            "section": loaded_context.section_context,
            "materials": loaded_context.materials_context,
            "continuity": loaded_context.continuity_context,
            "era": loaded_context.era_context,
            "sensory": loaded_context.sensory_context,
            "coverage_info": str(loaded_context.coverage_info),
        }

        # L2+ 添加扩展上下文
        if loaded_context.loaded_level.value >= ContextLevel.L2_EXTENDED.value:
            if loaded_context.chapter_sections:
                result["chapter_sections"] = "=== 本章其他小节 ===\n" + "\n".join(loaded_context.chapter_sections)

            if loaded_context.character_timeline:
                timeline_text = "=== 人物时间线 ===\n"
                for char, events in loaded_context.character_timeline.items():
                    timeline_text += f"\n【{char}】\n" + "\n".join(events)
                result["character_timeline"] = timeline_text

            if loaded_context.previous_chapter_summaries:
                result["previous_chapters"] = "=== 前章摘要 ===\n" + "\n".join(loaded_context.previous_chapter_summaries)

        # L3 添加完整上下文
        if loaded_context.loaded_level.value >= ContextLevel.L3_COMPLETE.value:
            if loaded_context.all_chapters_content:
                result["all_chapters"] = "=== 全书章节概览 ===\n" + "\n".join(loaded_context.all_chapters_content)

            if loaded_context.conflict_warnings:
                result["conflict_warnings"] = "=== 冲突警告 ===\n" + "\n".join(loaded_context.conflict_warnings)

        return result


class ContextLevelSelector:
    """上下文级别选择器

    根据当前任务类型自动选择合适的上下文加载级别。
    """

    @staticmethod
    def select_level(task_type: str, **kwargs) -> ContextLevel:
        """根据任务类型选择上下文级别

        Args:
            task_type: 任务类型
                - "section_generation": 小节生成
                - "chapter_review": 章节审校
                - "book_review": 全书审校
                - "continuity_check": 连贯性检查
                - "fact_verification": 事实核查
            **kwargs: 额外参数

        Returns:
            ContextLevel: 推荐的上下文级别
        """
        level_map = {
            "section_generation": ContextLevel.L1_ESSENTIAL,
            "chapter_review": ContextLevel.L2_EXTENDED,
            "book_review": ContextLevel.L3_COMPLETE,
            "continuity_check": ContextLevel.L2_EXTENDED,
            "fact_verification": ContextLevel.L2_EXTENDED,
            "style_adaptation": ContextLevel.L1_ESSENTIAL,
            "quick_draft": ContextLevel.L0_MINIMAL,
        }

        level = level_map.get(task_type, ContextLevel.L1_ESSENTIAL)

        # 根据额外条件调整
        if task_type == "section_generation":
            # 如果是第一章第一节，可能需要更多上下文
            chapter_idx = kwargs.get("chapter_idx", 0)
            section_idx = kwargs.get("section_idx", 0)
            if chapter_idx == 0 and section_idx == 0:
                return ContextLevel.L2_EXTENDED  # 开篇需要更多背景

        return level

    @staticmethod
    def get_level_description(level: ContextLevel) -> str:
        """获取级别的描述说明"""
        descriptions = {
            ContextLevel.L0_MINIMAL: "最小化加载 - 仅系统提示和基础大纲",
            ContextLevel.L1_ESSENTIAL: "最小必需 - 相关素材+上一节结尾（默认）",
            ContextLevel.L2_EXTENDED: "条件扩展 - 全章+相关人物时间线",
            ContextLevel.L3_COMPLETE: "完整集合 - 所有内容（全文审校）",
        }
        return descriptions.get(level, "未知级别")
