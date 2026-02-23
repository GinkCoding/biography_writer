"""第二层：知识构建与全局记忆层 (Knowledge & Memory)"""
import json
from typing import List, Dict, Optional, Any
from pathlib import Path
from dataclasses import dataclass, field
import networkx as nx
from loguru import logger

from src.llm_client import LLMClient
from src.models import (
    Event, Relationship, CharacterProfile, Timeline, 
    GlobalState, WritingStyle, InterviewMaterial
)
from src.utils import normalize_date, generate_id, calculate_age, save_json, load_json


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
        
        # 构建提取提示
        prompt = f"""请从以下采访文本中提取结构化信息。请以JSON格式返回。

=== 采访文本 ===
{all_text}

=== 提取要求 ===
1. 人物画像 (profile): 传主的基本信息
   - name: 姓名（如果未提供，推测最可能是传主的人名）
   - aliases: 别名/昵称列表
   - birth_date: 出生日期（格式：YYYY-MM-DD 或 YYYY-MM 或 YYYY）
   - birth_place: 出生地
   - occupation: 职业列表
   - personality_traits: 性格特征列表（3-5个关键词）
   - core_values: 核心价值观列表（3-5个关键词）

2. 人物关系 (relationships): 传主与其他人的关系
   - source: 关系主体（通常是传主）
   - target: 关系对象
   - relation_type: 关系类型（如：父亲、母亲、妻子、好友、导师等）
   - description: 关系描述

3. 重要事件 (events): 传主生命中的关键事件
   - date: 发生时间（尽可能精确）
   - date_approximate: 时间是否推测
   - title: 事件标题（10字以内）
   - description: 事件详细描述
   - characters_involved: 涉及人物
   - location: 发生地点
   - importance: 重要程度（1-10）

请返回严格符合以下JSON Schema的数据：
{{
  "profile": {{...}},
  "relationships": [...],
  "events": [...]
}}
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
                    name=p.get("name", subject_hint or "未知"),
                    aliases=p.get("aliases", []),
                    birth_date=normalize_date(p.get("birth_date")),
                    birth_place=p.get("birth_place"),
                    occupation=p.get("occupation", []),
                    personality_traits=p.get("personality_traits", []),
                    core_values=p.get("core_values", []),
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
                    title=e.get("title", ""),
                    description=e.get("description", ""),
                    source_text=all_text[max(0, len(all_text)//10):max(100, len(all_text)//10)+200],
                    characters_involved=e.get("characters_involved", []),
                    location=e.get("location"),
                    importance=e.get("importance", 5),
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
        years = sorted(year_events.keys())
        gaps = []
        for i in range(len(years) - 1):
            y1, y2 = int(years[i]), int(years[i + 1])
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
    """全局状态管理器"""
    
    def __init__(self, book_id: str, cache_dir: Path):
        self.book_id = book_id
        self.cache_dir = Path(cache_dir)
        self.cache_file = self.cache_dir / f"{book_id}_state.json"
        self.state = GlobalState(book_id=book_id)
    
    def init_from_timeline(self, timeline: Timeline):
        """从时间线初始化状态"""
        self.state.subject_profile = timeline.subject
        self.state.current_subject_age = None
        
        # 统计人物出场
        for event in timeline.events:
            for char in event.characters_involved:
                if char in self.state.characters_mentioned:
                    self.state.characters_mentioned[char] += 1
                else:
                    self.state.characters_mentioned[char] = 1
    
    def update_for_chapter(
        self,
        chapter_order: int,
        chapter_time_start: Optional[str],
        chapter_time_end: Optional[str]
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
    
    def add_chapter_summary(self, summary: str):
        """添加章节摘要到记忆"""
        self.state.add_chapter_summary(summary)
    
    def get_context_for_generation(self) -> Dict[str, Any]:
        """获取生成所需的上下文信息"""
        return {
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
    
    def save(self):
        """保存状态到文件"""
        save_json(self.state.model_dump(), self.cache_file)
    
    def load(self):
        """从文件加载状态"""
        if self.cache_file.exists():
            data = load_json(self.cache_file)
            self.state = GlobalState(**data)


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
        return timeline, knowledge_graph, state_manager