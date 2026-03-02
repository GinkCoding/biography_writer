"""第二层：知识构建与全局记忆层 (Knowledge & Memory)"""
import json
from typing import List, Dict, Optional, Any
from pathlib import Path
from dataclasses import dataclass, field
import networkx as nx
from loguru import logger
from datetime import datetime

from src.llm_client import LLMClient
from src.models import (
    Event, Relationship, CharacterProfile, Timeline,
    GlobalState, WritingStyle, InterviewMaterial
)
from src.utils import normalize_date, generate_id, calculate_age, save_json, load_json
from src.config import settings

# 导入新的三层存储架构
from src.storage.state_manager import StateManager, CharacterSnapshot, WritingProgress
from src.storage.index_manager import IndexManager, EntityMeta, RelationshipMeta, TimelineEventMeta


@dataclass
class ExtractedFacts:
    """从文本提取的事实"""
    events: List[Event] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)
    profile: Optional[CharacterProfile] = None


class EntityRelationExtractor:
    """实体与关系抽取器"""
    
    def __init__(self, llm: LLMClient):
        self.llm = llm
    
    async def extract_from_materials(
        self,
        materials: List[InterviewMaterial],
        subject_hint: Optional[str] = None
    ) -> ExtractedFacts:
        """从素材中提取实体和关系"""
        
        # 合并所有素材文本
        all_text = "\n\n".join([m.content for m in materials])
        
        # 限制长度
        if len(all_text) > 15000:
            all_text = all_text[:15000] + "..."
        
        # 构建提取提示 - 增强版
        prompt = f"""请从以下采访文本中提取结构化信息。请以JSON格式返回。

=== 采访文本 ===
{all_text}

=== 提取要求 ===

1. 人物画像 (profile): 传主的全方位画像
   【基础信息】
   - name: 姓名
   - aliases: 别名/昵称列表
   - birth_date: 出生日期（格式：YYYY-MM-DD 或 YYYY-MM 或 YYYY）
   - birth_place: 出生地
   - current_residence: 现居地（如有提及）

   【职业与教育】
   - occupation: 职业列表（包含时间线，如["1980-1990: 工人", "1990-2000: 厂长"]）
   - education_background: 教育背景（学校、专业、时间）
   - skills: 技能特长
   - career_highlights: 职业高光时刻（3-5个）

   【性格与心理】
   - personality_traits: 性格特征列表（5-8个关键词，要具体如"急躁但事后后悔"而非"情绪化"）
   - personality_evolution: 性格演变（按人生阶段划分，如{{"青年期": ["冲动", "理想主义"], "中年期": ["稳重", "务实"]}}）
   - core_values: 核心价值观列表（3-5个）
   - beliefs: 信念/人生信条（如有）
   - habits: 日常习惯、工作习惯（具体可感，如"每天五点起床浇花"）
   - quirks: 小怪癖/独特之处（让人物生动的细节）

   【外貌与行为】
   - physical_description: 外貌描述（身高、体型、面部特征、 aging痕迹等）
   - habitual_actions: 习惯性动作/姿态（如"思考时摸下巴"、"紧张时搓手"）
   - dressing_style: 穿衣风格（如"永远穿蓝色工装"、"注重仪表"）

   【语言与表达】
   - speaking_style: 说话风格（语速、音量、用词特点、逻辑性等）
   - catchphrases: 口头禅/常用语（3-5个）
   - language_quirks: 语言特点（方言、特定语法习惯、特殊用词）

   【情感与人际】
   - emotional_patterns: 情感模式（不同情境下的反应，如{{"面对挫折": "先愤怒后沉默", "面对赞扬": "摆手谦虚"}}）
   - relationship_patterns: 人际关系模式（如"对上级恭敬对下级严厉"、"朋友少但交情深"）
   - family_dynamics: 家庭动态（与家人的关系特点，如{{"父亲": "严厉但暗中支持", "妻子": "事业上的后盾"}}）

   【成长与转折】
   - growth_turning_points: 成长转折点（包含年龄、事件、影响，如[{{"age": "25", "event": "第一次创业失败", "impact": "从理想主义转向务实"}}]）
   - life_philosophy: 人生哲学/感悟（用第一人称总结）
   - regrets: 遗憾/未竟之事
   - proudest_moments: 最自豪的时刻（3-5个）

   【时代与环境】
   - social_background: 社会背景（阶层、家庭环境、成长环境）
   - era_influence: 时代对人物的影响（如"文革使其失去求学机会"）

   【关系网络】
   - key_people: 关键人物及其影响（如{{"师傅老王": "教会手艺和做人", "对手李明": "激发斗志"}}）

2. 人物关系 (relationships): 传主与其他人的关系
   - source: 关系主体（通常是传主）
   - target: 关系对象
   - relation_type: 关系类型
   - description: 关系描述（具体事例支撑）
   - evolution: 关系演变（如"早年疏远，晚年和解"）

3. 重要事件 (events): 传主生命中的关键事件
   【时间地点】
   - date: 发生时间（尽可能精确）
   - date_approximate: 时间是否推测
   - season: 季节（如有提及）
   - time_of_day: 时段（早晨/下午/夜晚）
   - location: 发生地点
   - location_details: 地点细节（如"厂门口的榕树下"、"家里那间漏雨的厨房"）

   【事件内容】
   - title: 事件标题（简洁有力，10字以内）
   - description: 事件详细描述（谁做了什么，结果如何）
   - event_type: 事件类型（life_event/turning_point/crisis/achievement/daily）
   - importance: 重要程度（1-10）

   【场景细节】
   - scene_description: 场景描写（环境、氛围、天气等）
   - sensory_details: 感官细节（视觉/听觉/嗅觉/触觉/味觉的具体描述）

   【人物与互动】
   - characters_involved: 涉及人物
   - subject_role: 传主在该事件中的角色（主导者/被动接受者/旁观者等）
   - character_reactions: 各人物的反应（如{{"陈国伟": "强装镇定", "母亲": "默默流泪"}}）

   【因果与影响】
   - causes: 事件原因/前因
   - consequences: 事件后果
   - impact_on_subject: 对传主的具体影响（性格、人生轨迹等）
   - emotional_tone: 情感基调
   - themes: 相关主题（如["坚韧", "牺牲", "转折"]）

请返回严格符合以下JSON Schema的数据：
{{
  "profile": {{...}},
  "relationships": [...],
  "events": [...]
}}

【重要提示】
1. 所有描述必须基于文本中的具体信息，不要编造
2. 对于不确定的信息，使用"据回忆"标注或留空
3. 性格特征要具体，避免空泛形容词（如"坚强"应具体为"再大的困难也不在外人面前流泪"）
4. 事件描述要包含可感知的细节，不要只有概括
"""
        
        messages = [
            {"role": "system", "content": "你是一个专业的信息抽取助手，擅长从非结构化文本中提取结构化的人物信息。请只返回JSON格式数据，不要有任何其他文字。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await self.llm.complete(messages, temperature=0.2)
            
            # 提取JSON
            json_str = self._extract_json(response)
            data = json.loads(json_str)
            
            # 构建ExtractedFacts
            profile = None
            if data.get("profile"):
                p = data["profile"]
                profile = CharacterProfile(
                    # 基础信息
                    name=p.get("name", subject_hint or "未知"),
                    aliases=p.get("aliases", []),
                    birth_date=normalize_date(p.get("birth_date")),
                    birth_place=p.get("birth_place"),
                    current_residence=p.get("current_residence"),

                    # 职业与教育
                    occupation=p.get("occupation", []),
                    education_background=p.get("education_background", []),
                    skills=p.get("skills", []),
                    career_highlights=p.get("career_highlights", []),

                    # 性格与心理
                    personality_traits=p.get("personality_traits", []),
                    personality_evolution=p.get("personality_evolution", {}),
                    core_values=p.get("core_values", []),
                    beliefs=p.get("beliefs", []),
                    habits=p.get("habits", []),
                    quirks=p.get("quirks", []),

                    # 外貌与行为
                    physical_description=p.get("physical_description"),
                    habitual_actions=p.get("habitual_actions", []),
                    dressing_style=p.get("dressing_style"),

                    # 语言与表达
                    speaking_style=p.get("speaking_style"),
                    catchphrases=p.get("catchphrases", []),
                    language_quirks=p.get("language_quirks", []),

                    # 情感与人际
                    emotional_patterns=p.get("emotional_patterns", {}),
                    relationship_patterns=p.get("relationship_patterns"),
                    family_dynamics=p.get("family_dynamics", {}),

                    # 成长与转折
                    growth_turning_points=p.get("growth_turning_points", []),
                    life_philosophy=p.get("life_philosophy"),
                    regrets=p.get("regrets", []),
                    proudest_moments=p.get("proudest_moments", []),

                    # 时代与环境
                    social_background=p.get("social_background"),
                    era_influence=p.get("era_influence"),

                    # 关系网络
                    key_people=p.get("key_people", {}),
                )

            relationships = []
            for r in data.get("relationships", []):
                relationships.append(Relationship(
                    source=r.get("source", profile.name if profile else ""),
                    target=r.get("target", ""),
                    relation_type=r.get("relation_type", ""),
                    description=r.get("description"),
                ))

            events = []
            for i, e in enumerate(data.get("events", [])):
                events.append(Event(
                    id=generate_id("event", i, e.get("title", "")),
                    date=normalize_date(e.get("date")),
                    date_approximate=e.get("date_approximate", False),
                    season=e.get("season"),
                    time_of_day=e.get("time_of_day"),
                    title=e.get("title", ""),
                    description=e.get("description", ""),
                    scene_description=e.get("scene_description"),
                    source_text=all_text[max(0, len(all_text)//10):max(100, len(all_text)//10)+200],
                    characters_involved=e.get("characters_involved", []),
                    subject_role=e.get("subject_role"),
                    character_reactions=e.get("character_reactions", {}),
                    location=e.get("location"),
                    location_details=e.get("location_details"),
                    sensory_details=_normalize_sensory_details(e.get("sensory_details", {})),
                    importance=e.get("importance", 5),
                    event_type=e.get("event_type", "life_event"),
                    causes=e.get("causes", []),
                    consequences=e.get("consequences", []),
                    impact_on_subject=e.get("impact_on_subject"),
                    emotional_tone=e.get("emotional_tone"),
                    themes=e.get("themes", []),
                ))
            
            return ExtractedFacts(
                events=events,
                relationships=relationships,
                profile=profile
            )
            
        except Exception as e:
            logger.error(f"信息抽取失败: {e}")
            # 返回空结果
            return ExtractedFacts(
                profile=CharacterProfile(name=subject_hint or "传主")
            )
    
    def _extract_json(self, text: str) -> str:
        """从文本中提取JSON"""
        # 尝试找到JSON块
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return text[start:end+1]
        return text


class TimelineBuilder:
    """时间线构建器"""
    
    def __init__(self, llm: LLMClient):
        self.llm = llm
    
    async def build_timeline(
        self,
        facts: ExtractedFacts,
        materials: List[InterviewMaterial]
    ) -> Timeline:
        """构建全局时间线"""
        
        # 合并已有事件和从素材中提取的时间信息
        all_events = facts.events.copy()
        
        # 从素材中补充更多时间信息
        for material in materials:
            # 材料已经包含时间引用，整合到时间线
            for time_ref in material.time_references:
                # 检查是否已存在类似时间
                exists = any(e.date == normalize_date(time_ref) for e in all_events)
                if not exists and time_ref:
                    # 创建占位事件
                    event = Event(
                        id=generate_id("auto_event", time_ref, material.id),
                        date=normalize_date(time_ref),
                        title=f"时期: {time_ref}",
                        description=f"来自素材: {material.content[:100]}...",
                        source_text=material.content,
                        importance=3,
                    )
                    all_events.append(event)
        
        # 排序事件
        all_events.sort(key=lambda e: e.date or "9999")
        
        # 构建时间线
        timeline = Timeline(
            subject=facts.profile or CharacterProfile(name="未知"),
            events=all_events,
        )
        
        if all_events:
            timeline.time_range_start = all_events[0].date
            timeline.time_range_end = all_events[-1].date
        
        logger.info(f"时间线构建完成，共 {len(all_events)} 个事件")
        return timeline
    
    def fill_time_gaps(self, timeline: Timeline) -> Timeline:
        """填补时间空白 - 识别时间线中的大段空白期"""
        if len(timeline.events) < 2:
            return timeline
        
        # 按时间分组事件
        year_events = {}
        for event in timeline.events:
            if event.date:
                year = event.date[:4]  # 提取年份
                if year not in year_events:
                    year_events[year] = []
                year_events[year].append(event)
        
        # 找出空白期（超过3年没有事件）
        import re
        def extract_year(y):
            """从字符串中提取年份数字"""
            if isinstance(y, int):
                return y
            # 尝试匹配4位年份
            match = re.search(r'\d{4}', str(y))
            if match:
                return int(match.group())
            return None

        years = sorted([y for y in year_events.keys() if extract_year(y) is not None],
                       key=lambda x: extract_year(x))
        gaps = []
        for i in range(len(years) - 1):
            y1_val, y2_val = extract_year(years[i]), extract_year(years[i + 1])
            if y1_val is None or y2_val is None:
                continue
            y1, y2 = int(y1_val), int(y2_val)
            if y2 - y1 > 3:
                gaps.append((y1, y2))
        
        if gaps:
            logger.warning(f"发现 {len(gaps)} 个时间空白期: {gaps}")
            # 这些空白期需要在大纲阶段特殊处理
            timeline.metadata = {"time_gaps": gaps}
        
        return timeline


class KnowledgeGraph:
    """轻量级人物关系图谱"""
    
    def __init__(self):
        self.graph = nx.Graph()
    
    def build_from_facts(self, facts: ExtractedFacts):
        """从事实构建图谱"""
        # 添加传主节点
        if facts.profile:
            self.graph.add_node(
                facts.profile.name,
                type="subject",
                **facts.profile.model_dump()
            )
        
        # 添加关系节点和边
        for rel in facts.relationships:
            # 添加关系对象节点
            if rel.target not in self.graph:
                self.graph.add_node(rel.target, type="related")
            
            # 添加边
            self.graph.add_edge(
                rel.source,
                rel.target,
                relation_type=rel.relation_type,
                description=rel.description
            )
    
    def get_related_people(self, name: str, depth: int = 1) -> List[str]:
        """获取相关人物"""
        if name not in self.graph:
            return []
        
        related = set()
        for neighbor in nx.neighbors(self.graph, name):
            related.add(neighbor)
            if depth > 1:
                for second in nx.neighbors(self.graph, neighbor):
                    if second != name:
                        related.add(second)
        
        return list(related)
    
    def get_relationship(self, source: str, target: str) -> Optional[str]:
        """获取两人关系"""
        if self.graph.has_edge(source, target):
            edge_data = self.graph[source][target]
            return edge_data.get("relation_type", "未知")
        return None
    
    def to_dict(self) -> Dict:
        """导出为字典"""
        return {
            "nodes": [
                {"id": n, **self.graph.nodes[n]}
                for n in self.graph.nodes()
            ],
            "edges": [
                {
                    "source": u,
                    "target": v,
                    **data
                }
                for u, v, data in self.graph.edges(data=True)
            ]
        }


class GlobalStateManager:
    """全局状态管理器 - 支持增强版状态和三层存储架构

    此类现在整合了三层存储架构：
    - state.json: 通过 StateManager 管理精简状态
    - index.db: 通过 IndexManager 管理实体、关系、时间线
    """

    def __init__(
        self,
        book_id: str,
        cache_dir: Optional[Path] = None,
        use_enhanced: bool = True,
        use_new_storage: bool = True
    ):
        self.book_id = book_id
        self.cache_dir = Path(cache_dir) if cache_dir else Path(settings.paths.cache_dir)
        self.cache_file = self.cache_dir / f"{book_id}_state.json"
        self.use_enhanced = use_enhanced
        self.use_new_storage = use_new_storage

        # 新的存储架构
        if use_new_storage:
            self._state_manager = StateManager(book_id, self.cache_dir)
            self._index_manager = IndexManager(book_id, self.cache_dir)
        else:
            self._state_manager = None
            self._index_manager = None

        # 根据配置选择状态类型
        if use_enhanced:
            from src.models import EnhancedGlobalState
            self.state = EnhancedGlobalState(book_id=book_id)
        else:
            self.state = GlobalState(book_id=book_id)

    def init_from_timeline(self, timeline: Timeline):
        """从时间线初始化状态"""
        self.state.subject_profile = timeline.subject
        if hasattr(self.state, 'current_subject_age'):
            self.state.current_subject_age = None

        # 统计人物出场
        for event in timeline.events:
            for char in event.characters_involved:
                # 基础统计
                if char in self.state.characters_mentioned:
                    self.state.characters_mentioned[char] += 1
                else:
                    self.state.characters_mentioned[char] = 1

                # 增强版：注册人物
                if self.use_enhanced and hasattr(self.state, 'register_character'):
                    self.state.register_character(name=char)

        # 同步到新的存储架构
        if self.use_new_storage and self._index_manager:
            self._sync_timeline_to_index(timeline)

    def _sync_timeline_to_index(self, timeline: Timeline):
        """将时间线数据同步到 IndexManager"""
        # 添加传主实体
        if timeline.subject:
            subject_entity = EntityMeta(
                id=f"person_{timeline.subject.name}",
                type="person",
                name=timeline.subject.name,
                aliases=timeline.subject.aliases or [],
                description=timeline.subject.to_bio_summary(),
                attributes={
                    "birth_date": timeline.subject.birth_date,
                    "birth_place": timeline.subject.birth_place,
                    "occupation": timeline.subject.occupation,
                    "personality_traits": timeline.subject.personality_traits,
                },
                importance="major"
            )
            self._index_manager.add_entity(subject_entity)

        # 添加时间线事件
        for event in timeline.events:
            event_meta = TimelineEventMeta(
                id=event.id,
                date=event.date,
                date_approximate=event.date_approximate,
                title=event.title,
                description=event.description,
                location=event.location or "",
                characters_involved=event.characters_involved,
                importance=event.importance,
                event_type=event.event_type,
                chapter_id=event.chapter_id
            )
            self._index_manager.add_timeline_event(event_meta)

        logger.info(f"已同步 {len(timeline.events)} 个事件到索引数据库")

    def update_for_chapter(
        self,
        chapter_order: int,
        chapter_time_start: Optional[str] = None,
        chapter_time_end: Optional[str] = None
    ):
        """更新到新的章节状态"""
        self.state.current_chapter_idx = chapter_order
        self.state.current_section_idx = 0

        # 计算当前年龄
        if chapter_time_start and self.state.subject_profile:
            birth = self.state.subject_profile.birth_date
            if birth:
                age = calculate_age(birth, chapter_time_start)
                self.state.current_subject_age = age

        # 同步到新存储
        if self.use_new_storage and self._state_manager:
            self._state_manager.update_progress(chapter_order, 0)

    def add_chapter_summary(self, summary: str):
        """添加章节摘要到记忆"""
        self.state.add_chapter_summary(summary)

        # 同步到新存储
        if self.use_new_storage and self._state_manager:
            self._state_manager.update_recent_summaries(summary)

    def get_context_for_generation(self) -> Dict[str, Any]:
        """获取生成所需的上下文信息"""
        context = {
            "subject_name": self.state.subject_profile.name if self.state.subject_profile else "",
            "subject_age": self.state.current_subject_age,
            "subject_mood": self.state.current_subject_mood,
            "chapter_progress": f"第{self.state.current_chapter_idx}章",
            "previous_summaries": self.state.generated_chapter_summaries[-3:],  # 最近3章
            "frequent_characters": sorted(
                self.state.characters_mentioned.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]  # 出场最多的5人
        }

        # 增强版：添加人物称谓映射和意象追踪
        if self.use_enhanced:
            if hasattr(self.state, 'character_name_mappings'):
                context["character_names"] = {
                    name: mapping.get_display_name(self.state.current_chapter_idx)
                    for name, mapping in self.state.character_name_mappings.items()
                }

            if hasattr(self.state, 'get_active_imageries'):
                active_imageries = self.state.get_active_imageries()
                if active_imageries:
                    context["active_imageries"] = [
                        {"name": img.name, "symbolic_meaning": img.symbolic_meaning}
                        for img in active_imageries
                    ]

            if hasattr(self.state, 'get_unresolved_foreshadowings'):
                unresolved = self.state.get_unresolved_foreshadowings()
                if unresolved:
                    context["pending_foreshadowings"] = [
                        {"id": fs.id, "content": fs.content}
                        for fs in unresolved[:3]  # 最多3个
                    ]

        return context

    def save(self):
        """保存状态到文件"""
        # 保存到旧格式（向后兼容）
        save_json(self.state.model_dump(), self.cache_file)

        # 同步到新存储架构
        if self.use_new_storage and self._state_manager:
            self._sync_to_new_state_manager()

    def _sync_to_new_state_manager(self):
        """同步状态到新的 StateManager"""
        if not self._state_manager:
            return

        # 确保状态已初始化
        if self._state_manager.state is None:
            self._state_manager.init_state(
                book_title=getattr(self.state, 'book_title', self.book_id),
                subject_name=self.state.subject_profile.name if self.state.subject_profile else "",
                writing_style=getattr(self.state, 'writing_style', 'literary'),
                total_chapters=getattr(self.state, 'total_chapters', 25)
            )

        # 更新进度
        self._state_manager.update_progress(
            self.state.current_chapter_idx,
            self.state.current_section_idx
        )

        # 同步人物快照
        if self.state.subject_profile:
            snapshot = CharacterSnapshot(
                name=self.state.subject_profile.name,
                age=self.state.current_subject_age,
                key_traits=self.state.subject_profile.personality_traits[:5] if self.state.subject_profile.personality_traits else [],
                current_status="active"
            )
            self._state_manager.add_character_snapshot(snapshot)

    def load(self):
        """从文件加载状态"""
        # 优先尝试从新的存储架构加载
        if self.use_new_storage and self._state_manager:
            new_state = self._state_manager.load()
            if new_state:
                logger.info(f"从新的存储架构加载状态: {self.book_id}")
                # 同步回旧的状态对象
                self._sync_from_new_state_manager(new_state)
                return

        # 回退到旧格式
        if self.cache_file.exists():
            data = load_json(self.cache_file)
            if self.use_enhanced:
                from src.models import EnhancedGlobalState
                self.state = EnhancedGlobalState(**data)
            else:
                self.state = GlobalState(**data)

    def _sync_from_new_state_manager(self, new_state):
        """从新的 StateManager 同步状态"""
        self.state.current_chapter_idx = new_state.progress.current_chapter
        self.state.current_section_idx = new_state.progress.current_section
        # 其他字段根据需要进行同步



def _normalize_sensory_details(data):
    """将 sensory_details 转换为 Dict[str, List[str]] 格式"""
    if not data:
        return {}
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return {}
        # 允许模型返回纯文本描述，统一放入“visual”槽位
        return {"visual": [text]}
    if isinstance(data, list):
        normalized = [str(item).strip() for item in data if str(item).strip()]
        return {"visual": normalized} if normalized else {}
    if not isinstance(data, dict):
        return {}
    result = {}
    for key, value in data.items():
        if isinstance(value, list):
            result[key] = [str(item).strip() for item in value if str(item).strip()]
        elif isinstance(value, str):
            # 字符串转列表
            result[key] = [value] if value.strip() else []
        else:
            result[key] = []
    return result

class KnowledgeMemoryLayer:
    """知识构建与全局记忆层主类"""
    
    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.entity_extractor = EntityRelationExtractor(llm)
        self.timeline_builder = TimelineBuilder(llm)
    
    async def build_knowledge_base(
        self,
        materials: List[InterviewMaterial],
        book_id: str,
        subject_hint: Optional[str] = None
    ) -> tuple[Timeline, KnowledgeGraph, GlobalStateManager]:
        """
        构建完整的知识基础
        
        Returns:
            (时间线, 关系图谱, 状态管理器)
        """
        logger.info("开始构建知识基础...")
        
        # 1. 实体与关系抽取
        logger.info("抽取实体与关系...")
        facts = await self.entity_extractor.extract_from_materials(
            materials, subject_hint
        )
        
        # 2. 构建关系图谱
        logger.info("构建人物关系图谱...")
        knowledge_graph = KnowledgeGraph()
        knowledge_graph.build_from_facts(facts)
        
        # 3. 构建时间线
        logger.info("构建时间线...")
        timeline = await self.timeline_builder.build_timeline(facts, materials)
        timeline = self.timeline_builder.fill_time_gaps(timeline)
        
        # 4. 初始化全局状态
        state_manager = GlobalStateManager(
            book_id=book_id,
            cache_dir=Path(settings.paths.cache_dir)
        )
        state_manager.init_from_timeline(timeline)
        state_manager.save()
        
        logger.info("知识基础构建完成")

        # 5. 生成人物小传文档
        logger.info("生成人物小传...")
        character_bio = await self.generate_character_biography(facts, timeline)
        bio_path = Path(settings.paths.cache_dir) / f"{book_id}_character_bio.md"
        bio_path.write_text(character_bio, encoding="utf-8")
        logger.info(f"人物小传已保存: {bio_path}")

        return timeline, knowledge_graph, state_manager

    async def generate_character_biography(
        self,
        facts: ExtractedFacts,
        timeline: Timeline
    ) -> str:
        """
        生成人物小传文档 - 为后续写作提供完整的人物参考

        Returns:
            格式化的人物小传文本
        """
        profile = facts.profile
        if not profile:
            return "# 人物小传\n\n（未能提取人物信息）"

        # 构建小传各部分
        parts = []

        # 标题
        parts.append(f"# {profile.name} 人物小传")
        parts.append(f"\n> 基于采访素材整理 | 生成时间: {datetime.now().strftime('%Y-%m-%d')}\n")

        # 一、人物速写（200字内）
        parts.append("## 一、人物速写\n")
        quick_summary = await self._generate_quick_summary(profile, facts.events)
        parts.append(quick_summary)

        # 二、基础档案
        parts.append("\n## 二、基础档案\n")
        parts.append(f"- **姓名**: {profile.name}")
        if profile.aliases:
            parts.append(f"- **别名**: {', '.join(profile.aliases)}")
        parts.append(f"- **出生**: {profile.birth_date or '不详'} {profile.birth_place or ''}")
        if profile.current_residence:
            parts.append(f"- **现居**: {profile.current_residence}")
        if profile.occupation:
            parts.append(f"- **职业轨迹**: {' → '.join(profile.occupation)}")
        if profile.education_background:
            parts.append(f"- **教育背景**: {'; '.join(profile.education_background)}")

        # 三、性格画像
        parts.append("\n## 三、性格画像\n")

        if profile.physical_description:
            parts.append(f"### 外貌特征\n{profile.physical_description}\n")

        if profile.habitual_actions:
            parts.append(f"### 习惯性动作\n" + '\n'.join([f"- {a}" for a in profile.habitual_actions]) + "\n")

        if profile.dressing_style:
            parts.append(f"### 穿衣风格\n{profile.dressing_style}\n")

        if profile.personality_traits:
            parts.append(f"### 核心性格\n" + '\n'.join([f"- {t}" for t in profile.personality_traits]) + "\n")

        if profile.personality_evolution:
            parts.append("### 性格演变\n")
            for period, traits in profile.personality_evolution.items():
                parts.append(f"- **{period}**: {', '.join(traits)}")
            parts.append("")

        if profile.habits:
            parts.append(f"### 日常习惯\n" + '\n'.join([f"- {h}" for h in profile.habits[:5]]) + "\n")

        if profile.quirks:
            parts.append(f"### 小怪癖\n" + '\n'.join([f"- {q}" for q in profile.quirks]) + "\n")

        # 四、语言风格
        if profile.speaking_style or profile.catchphrases or profile.language_quirks:
            parts.append("\n## 四、语言风格\n")
            if profile.speaking_style:
                parts.append(f"**说话特点**: {profile.speaking_style}\n")
            if profile.catchphrases:
                parts.append(f"**口头禅**: {', '.join(profile.catchphrases)}\n")
            if profile.language_quirks:
                parts.append(f"**语言特点**: {', '.join(profile.language_quirks)}\n")

        # 五、情感与人际模式
        if profile.emotional_patterns or profile.relationship_patterns or profile.family_dynamics:
            parts.append("\n## 五、情感与人际模式\n")
            if profile.emotional_patterns:
                parts.append("### 情感反应模式\n")
                for situation, reaction in profile.emotional_patterns.items():
                    parts.append(f"- **{situation}**: {reaction}")
                parts.append("")

            if profile.relationship_patterns:
                parts.append(f"### 人际模式\n{profile.relationship_patterns}\n")

            if profile.family_dynamics:
                parts.append("### 家庭关系\n")
                for member, relation in profile.family_dynamics.items():
                    parts.append(f"- **{member}**: {relation}")
                parts.append("")

        # 六、关键人物
        if profile.key_people:
            parts.append("\n## 六、关键人物\n")
            for name, influence in profile.key_people.items():
                parts.append(f"- **{name}**: {influence}")
            parts.append("")

        # 七、成长轨迹与转折点
        if profile.growth_turning_points or profile.proudest_moments or profile.regrets:
            parts.append("\n## 七、成长轨迹\n")

            if profile.growth_turning_points:
                parts.append("### 关键转折点\n")
                for tp in profile.growth_turning_points[:5]:
                    # 处理字典或 Event 对象
                    if hasattr(tp, 'get'):
                        age = tp.get('age', '未知年龄')
                        event = tp.get('event', '未知事件')
                        impact = tp.get('impact', '影响未详')
                    else:
                        age = getattr(tp, 'age', '未知年龄')
                        event = getattr(tp, 'event', '未知事件')
                        impact = getattr(tp, 'impact', '影响未详')
                    parts.append(f"- **{age}岁**: {event}")
                    parts.append(f"  - 影响: {impact}\n")

            if profile.proudest_moments:
                parts.append("### 最自豪的时刻\n")
                for i, moment in enumerate(profile.proudest_moments[:3], 1):
                    parts.append(f"{i}. {moment}")
                parts.append("")

            if profile.regrets:
                parts.append("### 遗憾\n")
                for i, regret in enumerate(profile.regrets[:3], 1):
                    parts.append(f"{i}. {regret}")
                parts.append("")

        # 八、核心价值观
        if profile.core_values or profile.beliefs or profile.life_philosophy:
            parts.append("\n## 八、核心价值观\n")
            if profile.core_values:
                parts.append(f"**核心价值观**: {', '.join(profile.core_values)}\n")
            if profile.beliefs:
                parts.append(f"**信念**: {', '.join(profile.beliefs)}\n")
            if profile.life_philosophy:
                parts.append(f"**人生哲学**: {profile.life_philosophy}\n")

        # 九、时代印记
        if profile.social_background or profile.era_influence:
            parts.append("\n## 九、时代印记\n")
            if profile.social_background:
                parts.append(f"**社会背景**: {profile.social_background}\n")
            if profile.era_influence:
                parts.append(f"**时代影响**: {profile.era_influence}\n")

        # 十、信息补全与合理推断
        parts.append("\n## 十、信息补全与合理推断\n")
        parts.append("> ⚠️ **重要提示**：本节内容基于人物背景信息（出生年份、地域、家庭背景等）进行合理推断，用于补足采访信息的空白。这些推断符合时代背景和社会规律，但具体到个人可能有差异，需要进一步核实。\n")

        try:
            from src.inference_engine import analyze_information_completeness
            inference_result = analyze_information_completeness(facts, timeline)

            # 信息完整性评估
            completeness = inference_result.get('completeness_score', 0)
            parts.append(f"\n### 信息完整性评估\n")
            parts.append(f"- **完整性评分**: {completeness:.0%}")
            parts.append(f"- **信息缺口数**: {inference_result.get('analysis_summary', {}).get('total_gaps', 0)} 个")
            parts.append(f"- **关键缺口**: {inference_result.get('analysis_summary', {}).get('critical_gaps', 0)} 个\n")

            # 推断的人生轨迹
            segments = inference_result.get('inferred_segments', [])
            if segments:
                parts.append("\n### 推断的人生轨迹\n")
                for seg in segments:
                    parts.append(f"\n**{seg.get('period', '未知时期')}** ({seg.get('life_stage', '')})")
                    parts.append(f"- **典型经历**: {', '.join(seg.get('typical_events', []))}")
                    if seg.get('social_context'):
                        parts.append(f"- **时代背景**: {seg['social_context']}")
                    parts.append(f"- **置信度**: {seg.get('confidence', 0):.0%}")
                    if seg.get('basis'):
                        parts.append(f"- **推断依据**: {', '.join(seg['basis'])}")
                    parts.append(f"- **类型**: 🔍 合理推断\n")

            # 人物画像增强
            profile_enrichment = inference_result.get('profile_enrichment', {})
            enrichments = profile_enrichment.get('inferred_enrichments', {})
            if enrichments:
                parts.append("\n### 画像特征推断\n")
                if enrichments.get('life_stage'):
                    parts.append(f"- **当前人生阶段**: {enrichments['life_stage']}")
                if enrichments.get('generation'):
                    parts.append(f"- **代际归属**: {enrichments['generation']}")
                if enrichments.get('era_features'):
                    parts.append(f"- **时代特征**: {', '.join(enrichments['era_features'])}")
                if enrichments.get('typical_concerns'):
                    parts.append(f"- **典型关注**: {', '.join(enrichments['typical_concerns'])}")
                if enrichments.get('region_type'):
                    parts.append(f"- **地域类型**: {enrichments['region_type']}")

            # 信息缺口提示
            gaps = inference_result.get('gaps', [])
            if gaps:
                parts.append("\n### 建议补充的信息\n")
                parts.append("以下时间段信息不足，建议通过补充采访或资料核实：\n")
                for gap in gaps[:5]:  # 只显示前5个
                    parts.append(f"- **{gap.get('description', '')}** ({gap.get('severity', 'medium')})")

            # 使用警告
            if inference_result.get('warnings'):
                parts.append("\n### ⚠️ 使用注意事项\n")
                for warning in inference_result.get('warnings', []):
                    parts.append(f"- {warning}")

        except Exception as e:
            logger.warning(f"信息推理失败: {e}")
            parts.append("\n（信息推理模块暂时不可用）\n")

        # 十一、事件档案
        if facts.events:
            parts.append("\n## 十、关键事件档案\n")
            # 按重要性排序
            sorted_events = sorted(facts.events, key=lambda e: e.importance, reverse=True)
            for i, e in enumerate(sorted_events[:10], 1):
                parts.append(f"### 事件{i}: {e.title}")
                parts.append(f"- **时间**: {e.date or '未知'} {e.season or ''}")
                parts.append(f"- **地点**: {e.location or '未知'}")
                parts.append(f"- **类型**: {e.event_type}")
                parts.append(f"- **重要度**: {'★' * e.importance}")
                parts.append(f"- **描述**: {e.description}")
                if e.scene_description:
                    parts.append(f"- **场景**: {e.scene_description}")
                if e.impact_on_subject:
                    parts.append(f"- **影响**: {e.impact_on_subject}")
                if e.sensory_details:
                    parts.append(f"- **感官细节**: {str(e.sensory_details)}")
                parts.append("")

        # 十一、写作要点提示
        parts.append("\n## 十一、写作要点提示\n")
        writing_tips = await self._generate_writing_tips(profile, facts.events)
        parts.append(writing_tips)

        return '\n'.join(parts)

    async def _generate_quick_summary(self, profile: CharacterProfile, events: List[Event]) -> str:
        """生成200字内的人物速写"""
        prompt = f"""请为{profile.name}写一段200字内的人物速写。

信息:
- 出生: {profile.birth_place or '某地'} {profile.birth_date or '不详'}
- 职业: {'、'.join(profile.occupation[:2]) if profile.occupation else '待考'}
- 性格: {', '.join(profile.personality_traits[:3]) if profile.personality_traits else '多元'}
- 外貌: {profile.physical_description or '未详'}
- 口头禅: {profile.catchphrases[0] if profile.catchphrases else '无'}

要求:
1. 用一句话概括核心特质
2. 用具体细节（习惯、动作、语言）而非空泛形容词
3. 点出最吸引人的特质
4. 200字以内
"""
        try:
            response = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.6
            )
            return response.strip()
        except Exception as e:
            logger.error(f"生成人物速写失败: {e}")
            return f"{profile.name}，{profile.birth_place or '某地'}人，{profile.occupation[0] if profile.occupation else '其'}一生{len(events)}个关键事件。"

    async def _generate_writing_tips(self, profile: CharacterProfile, events: List[Event]) -> str:
        """生成写作要点提示"""
        tips = []

        # 基于人物特征生成提示
        if profile.personality_evolution:
            tips.append("- 注意刻画人物性格的演变过程，避免前后矛盾")

        if profile.habitual_actions or profile.quirks:
            tips.append(f"- 善用习惯性动作（如{'、'.join(profile.habitual_actions[:2])}）来标示人物状态")

        if profile.catchphrases:
            tips.append(f"- 在关键情节中适时使用口头禅（{'、'.join(profile.catchphrases[:2])}）强化人物辨识度")

        if profile.sensory_details_exist:
            tips.append("- 充分利用素材中的感官细节，营造场景氛围")

        if profile.emotional_patterns:
            tips.append("- 情感冲突场景遵循人物的反应模式，保持内在一致性")

        if not tips:
            tips.append("- 注重具体细节，避免空泛评价")
            tips.append("- 用传主的言行举止展现性格，而非直接形容词描述")

        return '\n'.join(tips)
