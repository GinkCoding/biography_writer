"""第三层：规划与编排层 (Planning & Orchestration)"""
import yaml
from typing import List, Dict, Optional
from pathlib import Path
from loguru import logger

from src.llm_client import LLMClient
from src.models import (
    WritingStyle, BookOutline, ChapterOutline, SectionOutline,
    Timeline, CharacterProfile
)
from src.config import settings
from src.utils import generate_id, count_chinese_words


class StyleController:
    """风格控制中心"""
    
    def __init__(self):
        self.styles_config = self._load_styles()
    
    def _load_styles(self) -> Dict:
        """加载风格配置"""
        style_file = Path(__file__).parent.parent.parent / "config" / "styles.yaml"
        with open(style_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    
    def get_style_config(self, style: WritingStyle) -> Dict:
        """获取特定风格的配置"""
        return self.styles_config.get("styles", {}).get(style.value, {})
    
    def list_styles(self) -> List[Dict]:
        """列出所有可用风格"""
        styles = []
        for key, config in self.styles_config.get("styles", {}).items():
            styles.append({
                "id": key,
                "name": config.get("name", key),
                "description": config.get("description", ""),
            })
        return styles
    
    def build_style_prompt(self, style: WritingStyle) -> str:
        """构建风格化的系统提示词"""
        config = self.get_style_config(style)
        return config.get("system_prompt", "")


class OutlineGenerator:
    """大纲生成器"""
    
    # 传记经典结构模板
    BIOGRAPHY_STRUCTURE = [
        {"phase": "起源", "chapters": 3, "focus": "家世背景、童年、早期教育"},
        {"phase": "成长", "chapters": 4, "focus": "求学、青春期、性格形成、初恋"},
        {"phase": "起步", "chapters": 4, "focus": "初入社会、早期工作、第一次挫折"},
        {"phase": "奋斗", "chapters": 6, "focus": "事业拼搏、关键决策、重要合作"},
        {"phase": "转折", "chapters": 4, "focus": "人生危机、重大改变、重新出发"},
        {"phase": "成就", "chapters": 3, "focus": "巅峰时期、代表作品、社会贡献"},
        {"phase": "沉淀", "chapters": 1, "focus": "晚年生活、人生感悟、留给后人的话"},
    ]
    
    def __init__(self, llm: LLMClient):
        self.llm = llm
    
    async def generate_outline(
        self,
        timeline: Timeline,
        style: WritingStyle,
        target_words: int = 100000,
        total_chapters: int = 25,
        enable_iteration: bool = True
    ) -> BookOutline:
        """
        生成完整的书籍大纲（支持迭代优化）

        Args:
            timeline: 全局时间线
            style: 写作风格
            target_words: 目标字数
            total_chapters: 总章节数
            enable_iteration: 是否启用迭代优化
        """
        logger.info(f"开始生成大纲，目标字数: {target_words}, 章节数: {total_chapters}")

        subject = timeline.subject
        events = timeline.events

        # 1. 分析素材丰富度
        material_analysis = self._analyze_material_richness(events, subject)
        logger.info(f"素材分析: 高密度章节 {len(material_analysis['rich_periods'])}, "
                   f"低密度章节 {len(material_analysis['sparse_periods'])}")

        # 2. 基于素材分析调整章节分配
        chapter_distribution = self._distribute_events_to_chapters_enhanced(
            events, total_chapters, material_analysis
        )

        # 3. 为每个章节生成详细大纲
        chapters = []
        for i, chapter_events in enumerate(chapter_distribution, 1):
            chapter = await self._generate_chapter_outline(
                chapter_num=i,
                total_chapters=total_chapters,
                events=chapter_events,
                subject=subject,
                target_words=target_words // total_chapters,
                material_analysis=material_analysis if i in material_analysis['sparse_periods'] else None
            )
            chapters.append(chapter)

        # 4. 构建初步大纲
        outline = BookOutline(
            title=f"{subject.name}传",
            subtitle=self._generate_subtitle(subject),
            subject_name=subject.name,
            style=style,
            total_chapters=total_chapters,
            target_total_words=target_words,
            chapters=chapters,
            prologue="",
            epilogue=""
        )

        # 5. 迭代优化（如果启用）
        if enable_iteration:
            logger.info("开始大纲迭代优化...")
            outline = await self._iterate_outline_optimization(outline, timeline, style)

        # 6. 生成前言和后记（基于优化后的大纲）
        outline.prologue = await self._generate_prologue(subject, events, style, outline)
        outline.epilogue = await self._generate_epilogue(subject, events, style, outline)

        logger.info(f"大纲生成完成: {outline.title}, 共 {len(chapters)} 章")
        return outline

    def _analyze_material_richness(self, events: List[Event], subject: CharacterProfile) -> Dict:
        """分析素材丰富度，识别高密度和低密度时期"""
        analysis = {
            'rich_periods': [],  # 素材丰富的章节索引
            'sparse_periods': [],  # 素材稀疏的章节索引
            'key_turning_points': [],  # 关键转折点位置
            'event_density_by_period': {},  # 各时期事件密度
            'character_arc_gaps': [],  # 人物弧光缺失点
        }

        if not events:
            return analysis

        # 按时间排序事件
        sorted_events = sorted(events, key=lambda e: e.date or "")

        # 计算事件重要性分布
        high_importance_events = [e for e in sorted_events if e.importance >= 8]
        analysis['key_turning_points'] = [i for i, e in enumerate(sorted_events) if e.importance >= 8]

        # 识别素材稀疏期（连续3个低重要性事件）
        for i in range(len(sorted_events) - 2):
            if all(sorted_events[j].importance <= 4 for j in range(i, i + 3)):
                analysis['sparse_periods'].append(i)

        # 识别素材丰富期
        for i, e in enumerate(sorted_events):
            if e.importance >= 6 or len(e.sensory_details) > 2 or len(e.character_reactions) > 1:
                analysis['rich_periods'].append(i)

        return analysis

    def _distribute_events_to_chapters_enhanced(
        self,
        events: List[Event],
        total_chapters: int,
        material_analysis: Dict
    ) -> List[List]:
        """增强版事件分配，考虑素材丰富度"""
        if not events:
            return [[] for _ in range(total_chapters)]

        # 按时间排序
        sorted_events = sorted(events, key=lambda e: e.date or "")

        # 基础分配
        events_per_chapter = len(sorted_events) / total_chapters

        distribution = []
        for i in range(total_chapters):
            start_idx = int(i * events_per_chapter)
            end_idx = int((i + 1) * events_per_chapter)

            chapter_events = sorted_events[start_idx:end_idx]

            # 如果这是关键转折点章节，确保包含转折点事件
            for tp_idx in material_analysis.get('key_turning_points', []):
                if start_idx <= tp_idx < end_idx:
                    # 关键转折点章节，保持原样
                    break

            # 如果素材稀疏，尝试从相邻章节补充背景信息
            if i in material_analysis.get('sparse_periods', []) and len(chapter_events) < 2:
                # 添加一些时代背景事件
                if start_idx > 0:
                    chapter_events.insert(0, sorted_events[start_idx - 1])

            if not chapter_events and sorted_events:
                chapter_events = [sorted_events[i % len(sorted_events)]]

            distribution.append(chapter_events)

        return distribution

    async def _iterate_outline_optimization(
        self,
        outline: BookOutline,
        timeline: Timeline,
        style: WritingStyle,
        max_iterations: int = 2
    ) -> BookOutline:
        """迭代优化大纲"""

        for iteration in range(max_iterations):
            logger.info(f"大纲优化迭代 {iteration + 1}/{max_iterations}")

            # 检查大纲质量
            issues = self._check_outline_quality(outline, timeline)

            if not issues:
                logger.info("大纲质量检查通过")
                break

            logger.info(f"发现 {len(issues)} 个问题，进行优化...")

            # 根据问题类型进行优化
            for issue in issues:
                if issue['type'] == 'time_gap':
                    await self._optimize_time_gap(outline, issue, timeline)
                elif issue['type'] == 'character_arc_break':
                    await self._optimize_character_arc(outline, issue, timeline)
                elif issue['type'] == 'sparse_content':
                    await self._enrich_sparse_chapter(outline, issue, timeline)

        return outline

    def _check_outline_quality(self, outline: BookOutline, timeline: Timeline) -> List[Dict]:
        """检查大纲质量问题"""
        issues = []

        # 1. 检查时间跳跃
        for i in range(len(outline.chapters) - 1):
            current_end = outline.chapters[i].time_period_end
            next_start = outline.chapters[i + 1].time_period_start

            if current_end and next_start:
                # 简单年份检查
                current_year = self._extract_year(current_end)
                next_year = self._extract_year(next_start)

                if current_year and next_year and next_year - current_year > 5:
                    issues.append({
                        'type': 'time_gap',
                        'chapter': i + 1,
                        'description': f'时间跳跃 {next_year - current_year} 年',
                        'suggestion': '添加过渡说明或中间时期概述'
                    })

        # 2. 检查内容稀疏章节
        for i, chapter in enumerate(outline.chapters):
            if len(chapter.sections) < 2 and not chapter.summary.strip():
                issues.append({
                    'type': 'sparse_content',
                    'chapter': i + 1,
                    'description': '章节内容稀疏',
                    'suggestion': '丰富章节内容或合并到相邻章节'
                })

        return issues

    def _extract_year(self, date_str: str) -> Optional[int]:
        """从日期字符串提取年份"""
        if not date_str:
            return None
        match = re.search(r'(\d{4})', date_str)
        return int(match.group(1)) if match else None

    async def _optimize_time_gap(self, outline: BookOutline, issue: Dict, timeline: Timeline):
        """优化时间跳跃问题"""
        chapter_idx = issue['chapter'] - 1
        if 0 <= chapter_idx < len(outline.chapters):
            chapter = outline.chapters[chapter_idx]
            # 添加过渡说明
            chapter.summary += f"\n【过渡】{issue['suggestion']}"
            logger.info(f"已优化第{issue['chapter']}章的时间跳跃问题")

    async def _optimize_character_arc(self, outline: BookOutline, issue: Dict, timeline: Timeline):
        """优化人物弧光断裂问题"""
        # 实现人物弧光连贯性优化
        pass

    async def _enrich_sparse_chapter(self, outline: BookOutline, issue: Dict, timeline: Timeline):
        """丰富内容稀疏的章节"""
        chapter_idx = issue['chapter'] - 1
        if 0 <= chapter_idx < len(outline.chapters):
            chapter = outline.chapters[chapter_idx]
            # 添加时代背景小节
            if len(chapter.sections) < 2:
                from src.models import SectionOutline
                chapter.sections.append(SectionOutline(
                    id=generate_id("section", chapter_idx, len(chapter.sections)),
                    title="时代背景与过渡",
                    target_words=1000,
                    content_summary=f"补充{chapter.time_period_start or '这一时期'}的社会背景",
                    emotional_tone="平实"
                ))
            logger.info(f"已丰富第{issue['chapter']}章的内容")
    
    def _distribute_events_to_chapters(
        self,
        events: List,
        total_chapters: int
    ) -> List[List]:
        """将事件分配到各章节"""
        if not events:
            return [[] for _ in range(total_chapters)]
        
        # 按时间排序
        sorted_events = sorted(events, key=lambda e: e.date or "")
        
        # 计算每个章节的事件数
        events_per_chapter = len(sorted_events) / total_chapters
        
        distribution = []
        for i in range(total_chapters):
            start_idx = int(i * events_per_chapter)
            end_idx = int((i + 1) * events_per_chapter)
            
            # 确保每个章节至少有一些事件
            chapter_events = sorted_events[start_idx:end_idx]
            if not chapter_events and sorted_events:
                # 如果某章没有事件，分配一个重要事件
                chapter_events = [sorted_events[i % len(sorted_events)]]
            
            distribution.append(chapter_events)
        
        return distribution
    
    async def _generate_chapter_outline(
        self,
        chapter_num: int,
        total_chapters: int,
        events: List,
        subject: CharacterProfile,
        target_words: int,
        material_analysis: Optional[Dict] = None
    ) -> ChapterOutline:
        """生成单章大纲（增强版，使用立体人物画像）"""

        # 提取事件信息（包含丰富的场景细节）
        events_text = "\n\n".join([
            f"【事件{i+1}】\n"
            f"时间: {e.date or '未知'} {e.season or ''} {e.time_of_day or ''}\n"
            f"地点: {e.location or '未知'} {e.location_details or ''}\n"
            f"标题: {e.title}\n"
            f"描述: {e.description}\n"
            f"场景: {e.scene_description or '无'}\n"
            f"感官细节: {', '.join([f'{k}: {v}' for k, v in e.sensory_details.items()]) if e.sensory_details else '无'}\n"
            f"人物反应: {e.character_reactions if e.character_reactions else '无'}\n"
            f"影响: {e.impact_on_subject or '无'}"
            for i, e in enumerate(events[:6])
        ])

        # 确定章节时间范围
        dates = [e.date for e in events if e.date]
        time_start = min(dates) if dates else None
        time_end = max(dates) if dates else None

        # 推断时代背景
        era_hint = self._get_era_hint(time_start)

        # 构建人物画像信息
        subject_profile_text = f"""
【基础信息】
姓名: {subject.name}，别名: {', '.join(subject.aliases) if subject.aliases else '无'}
出生: {subject.birth_place or '不详'} {subject.birth_date or '不详'}
现居: {subject.current_residence or '不详'}
职业: {', '.join(subject.occupation) if subject.occupation else '不详'}

【性格特征】
核心特质: {', '.join(subject.personality_traits) if subject.personality_traits else '不详'}
{'性格演变: ' + str(subject.personality_evolution) if subject.personality_evolution else ''}
价值观: {', '.join(subject.core_values) if subject.core_values else '不详'}
信念: {', '.join(subject.beliefs) if subject.beliefs else '不详'}
习惯: {', '.join(subject.habits[:3]) if subject.habits else '不详'}
小怪癖: {', '.join(subject.quirks[:3]) if subject.quirks else '不详'}

【外貌与行为】
外貌: {subject.physical_description or '不详'}
习惯性动作: {', '.join(subject.habitual_actions[:3]) if subject.habitual_actions else '不详'}
穿衣风格: {subject.dressing_style or '不详'}

【语言表达】
说话风格: {subject.speaking_style or '不详'}
口头禅: {', '.join(subject.catchphrases[:3]) if subject.catchphrases else '不详'}
语言特点: {', '.join(subject.language_quirks[:2]) if subject.language_quirks else '不详'}

【情感与人际】
情感模式: {str(subject.emotional_patterns) if subject.emotional_patterns else '不详'}
人际模式: {subject.relationship_patterns or '不详'}

【成长轨迹】
转折点: {str(subject.growth_turning_points[:2]) if subject.growth_turning_points else '不详'}
人生哲学: {subject.life_philosophy or '不详'}
"""

        # 素材稀疏警告
        sparse_warning = ""
        if material_analysis:
            sparse_warning = """
【注意：本章素材相对稀疏】
由于采访素材在该时期较为有限，请：
1. 充分利用已有的事件细节进行深度挖掘
2. 合理补充时代背景信息
3. 通过传主的性格特征和行为模式进行合理推演
4. 不要编造不存在的人物或事件，但可以丰富已有人物的具体表现
"""

        prompt = f"""请为传记的第{chapter_num}章生成详细大纲。

=== 传主画像 ===
{subject_profile_text}

=== 章节信息 ===
章节位置: 第{chapter_num}章 / 共{total_chapters}章
时间范围: {time_start or '待定'} 至 {time_end or '待定'}
时代背景: {era_hint}
目标字数: {target_words}字

=== 本章涉及的详细事件 ===
{events_text}
{sparse_warning}"

请生成以下内容（JSON格式）:
{{
  "title": "章节标题（8-12字，有吸引力且反映具体内容）",
  "summary": "本章内容概要（100-150字，必须包含具体时间、地点和核心事件）",
  "characters_present": ["本章出现的所有人物，标注与传主关系"],
  "historical_context": "时代背景描述（100字左右，说明当时的社会环境）",
  "sections": [
    {{
      "title": "小节标题（具体反映本节内容）",
      "target_words": {target_words // 4},
      "content_summary": "本节要写什么（80-100字，必须包含具体事实细节，禁止空洞描述）",
      "emotional_tone": "情感基调（如：沉重、激昂、温馨、悬疑）",
      "pacing": "本节节奏（slow-舒缓/moderate-适中/fast-紧凑/mixed-起伏）",
      "key_events": ["关联的具体事件名称"],
      "time_location": "具体时间和地点，如：1982年春，佛山陈家村",
      "paragraphs": [
        {{
          "order": 1,
          "paragraph_type": "段落类型: narrative(叙述)/dialogue(对话)/description(描写)/reflection(思考)",
          "content_purpose": "本段的写作目的（如：引入场景/推进情节/刻画心理/展示对话）",
          "target_words": 150,
          "key_details": ["必须包含的具体细节1", "细节2"],
          "sensory_focus": ["visual", "auditory"],
          "emotional_progression": "本段要达成的情感递进目标",
          "transition_from_prev": "与前段的衔接方式"
        }}
      ]
    }}
  ]
}}

【硬性要求 - 必须遵守】
1. 时间要求：
   - 必须提取确切时间（精确到年月，如不可考则标注"约XX年"）
   - 每小节必须标注"time_location"字段

2. 地点要求：
   - 必须提取具体地点（省/市/县/具体场所）
   - 不能出现"待定"、"未知"等模糊表述

3. 人物要求：
   - 列出所有出场人物的全名及与传主关系
   - 首次出现的人物需标注"（首次出现）"

4. 内容概要要求：
   - 80-100字，必须包含至少1个具体事实细节
   - 禁止空洞形容词堆砌（如"这是一个重要的时期"）
   - 必须说明：谁在什么时间什么地点做了什么

5. 时代背景要求：
   - 简述本章时间段的社会大环境
   - 提及当时的重大历史事件或社会现象
   - 说明时代背景对传主的影响

6. 素材引用要求：
   - 每个小节必须关联至少1个采访事件
   - 禁止脱离素材凭空设计情节

7. 段落级规划要求（每小节4-5段）：
   - 每段明确类型：叙述/对话/描写/思考
   - 每段标注情感递进目标
   - 确保段落间过渡自然，逻辑连贯
   - 合理分配感官描写（视觉/听觉/嗅觉/触觉/味觉）
   - 段落顺序符合叙事逻辑，避免跳跃
"""
        
        messages = [
            {"role": "system", "content": "你是一位资深的传记文学编辑，擅长从采访素材中提取具体事实设计章节结构。请只返回JSON格式。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await self.llm.complete(messages, temperature=0.5)
            data = self._parse_json_response(response)
            
            # 构建小节大纲
            sections = []
            for i, sec_data in enumerate(data.get("sections", [])):
                # 解析段落级大纲
                paragraphs = []
                for j, para_data in enumerate(sec_data.get("paragraphs", [])):
                    from src.models import ParagraphOutline
                    paragraphs.append(ParagraphOutline(
                        id=generate_id("para", chapter_num, i, j),
                        order=para_data.get("order", j + 1),
                        paragraph_type=para_data.get("paragraph_type", "narrative"),
                        content_purpose=para_data.get("content_purpose", ""),
                        target_words=para_data.get("target_words", 150),
                        key_details=para_data.get("key_details", []),
                        sensory_focus=para_data.get("sensory_focus", []),
                        emotional_progression=para_data.get("emotional_progression", ""),
                        transition_from_prev=para_data.get("transition_from_prev", ""),
                    ))

                sections.append(SectionOutline(
                    id=generate_id("section", chapter_num, i),
                    title=sec_data.get("title", f"第{i+1}节"),
                    target_words=sec_data.get("target_words", target_words // 4),
                    key_events=sec_data.get("key_events", []),
                    content_summary=sec_data.get("content_summary", ""),
                    emotional_tone=sec_data.get("emotional_tone", "平实"),
                    pacing=sec_data.get("pacing", "moderate"),
                    paragraphs=paragraphs,
                ))
            
            return ChapterOutline(
                id=generate_id("chapter", chapter_num),
                title=data.get("title", f"第{chapter_num}章"),
                order=chapter_num,
                summary=data.get("summary", ""),
                sections=sections,
                time_period_start=time_start,
                time_period_end=time_end,
                characters_present=data.get("characters_present", []),
            )
            
        except Exception as e:
            logger.error(f"生成第{chapter_num}章大纲失败: {e}")
            # 返回默认大纲
            return self._default_chapter_outline(chapter_num, target_words)
    
    def _get_era_hint(self, time_start: Optional[str]) -> str:
        """根据时间推断时代背景"""
        if not time_start:
            return "时间待定"
        
        year = time_start[:4] if len(time_start) >= 4 else ""
        
        era_map = {
            "1949": "新中国成立初期，土地改革",
            "1950": "建国初期，三大改造",
            "1960": "三年困难时期，物质极度匮乏",
            "1966": "文革时期，社会动荡",
            "1976": "文革结束，拨乱反正",
            "1978": "改革开放初期，思想解放",
            "1980": "改革开放初期，特区设立",
            "1984": "城市改革启动，沿海开放",
            "1992": "南巡讲话后，市场经济确立",
            "1997": "香港回归，国企改革攻坚",
            "2001": "中国加入WTO，申奥成功",
            "2008": "北京奥运会，金融危机",
            "2010": "移动互联网时代",
        }
        
        for decade, desc in era_map.items():
            if year.startswith(decade[:3]):
                return desc
        
        return f"{year}年代"
    
    def _default_chapter_outline(self, chapter_num: int, target_words: int) -> ChapterOutline:
        """生成默认章节大纲 - 带段落级规划"""
        sections = []
        paragraph_types = ["narrative", "description", "dialogue", "reflection"]
        for i in range(4):
            # 为每小节创建4个段落
            paragraphs = []
            for j in range(4):
                from src.models import ParagraphOutline
                paragraphs.append(ParagraphOutline(
                    id=generate_id("para", chapter_num, i, j),
                    order=j + 1,
                    paragraph_type=paragraph_types[j % len(paragraph_types)],
                    content_purpose="推进叙事或刻画细节",
                    target_words=(target_words // 4) // 4,
                    key_details=[],
                    sensory_focus=[],
                ))

            sections.append(SectionOutline(
                id=generate_id("section", chapter_num, i),
                title=f"第{i+1}节",
                target_words=target_words // 4,
                content_summary="基于采访素材展开具体叙述",
                emotional_tone="平实",
                pacing="moderate",
                paragraphs=paragraphs,
            ))

        return ChapterOutline(
            id=generate_id("chapter", chapter_num),
            title=f"第{chapter_num}章",
            order=chapter_num,
            summary="本章基于原始采访素材，还原传主的真实经历",
            sections=sections
        )
    
    async def _generate_prologue(
        self,
        subject: CharacterProfile,
        events: List,
        style: WritingStyle,
        outline: BookOutline
    ) -> str:
        """生成前言（增强版，使用完整人物画像）"""
        # 提取关键信息用于前言
        key_events = [e.title for e in events[:5] if e.title]
        turning_points = [e.title for e in events if e.importance >= 8][:3]

        # 构建丰富的人物信息
        profile_summary = f"""
【核心特质】
性格: {', '.join(subject.personality_traits[:3]) if subject.personality_traits else '多元'}
价值观: {', '.join(subject.core_values[:3]) if subject.core_values else '坚韧'}
人生哲学: {subject.life_philosophy[:50] if subject.life_philosophy else '未详'}

【人生轨迹】
职业: {' → '.join(subject.occupation[:4]) if subject.occupation else '丰富多彩'}
转折点: {', '.join(turning_points)}
最自豪: {subject.proudest_moments[0] if subject.proudest_moments else '奋斗的一生'}
"""

        prompt = f"""请为《{subject.name}传》撰写一段前言（300-500字）。

=== 传主画像 ===
{profile_summary}

=== 书籍信息 ===
书名: {outline.title}
副标题: {outline.subtitle or '未定'}
章节结构: 共{outline.total_chapters}章，从{outline.chapters[0].time_period_start if outline.chapters else '起点'}到{outline.chapters[-1].time_period_end if outline.chapters else '终点'}
写作风格: {style.value}

=== 生平关键事件 ===
{chr(10).join(key_events)}

=== 前言要求 ===
1. 开篇点题：用传主的一句代表性话语或一个典型场景引入
2. 人物速写：通过具体细节勾勒传主形象（避免"伟大""杰出"等空泛词）
3. 采访缘起：交代采访时间、地点、契机（增强真实感）
4. 书籍价值：说明这本传记的独特之处
5. 读者引导：引发阅读兴趣，点明阅读重点

注意：使用具体细节，避免空泛评价。用传主的言行举止展现其性格，而非直接形容词描述。
"""

        messages = [
            {"role": "system", "content": "你是一位资深出版人，擅长撰写传记前言。你注重真实感和具体细节。"},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self.llm.complete(messages, temperature=0.6)
            return response.strip()
        except Exception as e:
            logger.error(f"生成前言失败: {e}")
            return f"本书基于对{subject.name}的深入采访写成，力求还原其真实的人生轨迹。"

    async def _generate_epilogue(
        self,
        subject: CharacterProfile,
        events: List,
        style: WritingStyle,
        outline: BookOutline
    ) -> str:
        """生成后记 - 增强版,包含完整人物弧光总结"""
        # 提取人生各阶段的事件
        early_events = [e for e in events if e.event_type == "life_event"][:3]
        turning_events = [e for e in events if e.importance >= 8][:3]
        achievements = [e for e in events if e.event_type == "achievement"][:3]

        life_summary = f"""
【人生阶段回顾】
早期: {early_events[0].title if early_events else '成长岁月'} - {subject.personality_evolution.get('青年期', ['性格形成'])[0] if subject.personality_evolution else '性格形成'}
转折: {turning_events[0].title if turning_events else '关键抉择'} - 影响深远
成就: {achievements[0].title if achievements else '事业巅峰'} - {subject.career_highlights[0] if subject.career_highlights else '专业成就'}

【人物总结】
成长轨迹: {len(subject.growth_turning_points)}个关键转折点
人际特点: {subject.relationship_patterns[:30] if subject.relationship_patterns else '重情重义'}
时代印记: {subject.era_influence[:30] if subject.era_influence else '时代见证者'}
人生智慧: {subject.life_philosophy[:50] if subject.life_philosophy else '踏实做人'}

【遗憾与自豪】
遗憾: {subject.regrets[0] if subject.regrets else '无'}
最自豪: {subject.proudest_moments[0] if subject.proudest_moments else '无愧于心'}
"""

        prompt = f"""请为《{subject.name}传》撰写一段后记（300-500字）。

=== 传主人生总结 ===
{life_summary}

=== 书籍信息 ===
书名: {outline.title}
章节数: {outline.total_chapters}章
总字数: 约{outline.target_total_words}字
写作风格: {style.value}

=== 后记要求 ===
1. 人物弧光总结：回顾传主从{outline.chapters[0].title if outline.chapters else '起点'}到{outline.chapters[-1].title if outline.chapters else '终点'}的转变
2. 具体细节收尾：用一个传主的真实言行或习惯动作作结
3. 人生智慧提炼：总结传主留给读者的人生启示（基于具体事例）
4. 作者感悟：作为采访者的真实感受
5. 留白思考：提出一个开放性问题供读者思考

注意：避免"他的一生是伟大的"这类空泛评价，用传主自己的言行作为最后的注脚。"""

        messages = [
            {"role": "system", "content": "你是一位资深传记作家，擅长基于事实总结人生，善于用具体细节而非空泛评价。"},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self.llm.complete(messages, temperature=0.6)
            return response.strip()
        except Exception as e:
            logger.error(f"生成后记失败: {e}")
            return f"{subject.name}的一生，是一部基于真实经历的生动记录。"
    
    def _generate_subtitle(self, subject: CharacterProfile) -> str:
        """生成副标题"""
        hints = []
        if subject.occupation:
            hints.append(subject.occupation[0])
        if subject.personality_traits:
            hints.append(subject.personality_traits[0])
        
        if hints:
            return f"一个{'的'.join(hints)}的真实人生"
        return "一部基于采访的真实记录"
    
    def _parse_json_response(self, response: str) -> Dict:
        """解析JSON响应"""
        import json
        import re
        
        # 尝试直接解析
        try:
            return json.loads(response)
        except:
            pass
        
        # 提取JSON块
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass
        
        return {}


class PlanningOrchestrationLayer:
    """规划与编排层主类"""
    
    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.style_controller = StyleController()
        self.outline_generator = OutlineGenerator(llm)
    
    async def create_book_plan(
        self,
        timeline: Timeline,
        style: WritingStyle,
        target_words: Optional[int] = None,
        total_chapters: Optional[int] = None
    ) -> BookOutline:
        """
        创建完整的书籍规划
        
        Returns:
            BookOutline: 书籍大纲
        """
        # 使用配置默认值
        target = target_words or settings.generation.target_length
        chapters = total_chapters or settings.generation.total_chapters
        
        # 生成大纲
        outline = await self.outline_generator.generate_outline(
            timeline=timeline,
            style=style,
            target_words=target,
            total_chapters=chapters
        )
        
        logger.info(f"书籍规划完成: {outline.title}, 预计{outline.target_total_words}字")
        return outline
    
    def get_available_styles(self) -> List[Dict]:
        """获取所有可用风格"""
        return self.style_controller.list_styles()
