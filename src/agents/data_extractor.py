"""Data Agent - 数据链工程师

位置: 在Generation层之后
输入: 生成的章节内容
输出: 提取的实体、状态更新、向量嵌入
职责: 语义化提取并同步到存储层
"""

import re
import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from loguru import logger

from src.models import (
    BookOutline, ChapterOutline, SectionOutline,
    GeneratedSection, GeneratedChapter, EnhancedGlobalState,
    CharacterProfile, InterviewMaterial, ForeshadowingItem,
    ImageryTracker, CharacterEvolution
)
from src.llm_client import LLMClient
from src.layers.data_ingestion import VectorStore
from src.utils import count_chinese_words, truncate_text, generate_id


@dataclass
class EntityAppearance:
    """实体出场记录"""
    entity_id: str
    entity_type: str  # 角色/地点/组织/物品/时间
    name: str
    mentions: List[str] = field(default_factory=list)  # 提及形式（别名）
    confidence: float = 0.0  # 置信度
    context_snippets: List[str] = field(default_factory=list)  # 上下文片段


@dataclass
class EntitySuggestion:
    """新实体建议"""
    suggested_id: str
    name: str
    entity_type: str
    tier: str = "装饰"  # 核心/重要/装饰
    evidence: str = ""  # 证据/依据


@dataclass
class StateChange:
    """状态变化记录"""
    entity_id: str
    field: str  # 变化的字段
    old_value: str
    new_value: str
    reason: str
    confidence: float = 0.0


@dataclass
class RelationshipChange:
    """关系变化记录"""
    from_entity: str
    to_entity: str
    relation_type: str
    description: str
    is_new: bool = True  # 是否新建立的关系


@dataclass
class SceneChunk:
    """场景切片"""
    scene_id: str
    chapter_id: str
    order: int
    location: str
    time_mark: str
    characters_present: List[str]
    summary: str
    content: str
    word_count: int


@dataclass
class ChapterMeta:
    """章节元数据"""
    chapter_number: int
    hook_type: str = ""
    hook_content: str = ""
    hook_strength: str = "weak"
    pattern_opening: str = ""  # 开头模式
    pattern_hook: str = ""     # 钩子模式
    emotion_rhythm: str = ""   # 情绪节奏
    info_density: str = "medium"  # 信息密度
    ending_time: str = ""
    ending_location: str = ""
    ending_emotion: str = ""


@dataclass
class UncertainMatch:
    """不确定匹配项"""
    mention: str
    candidates: List[Dict[str, str]]  # [{type, id, name}, ...]
    confidence: float
    adopted_candidate: Optional[str] = None  # 采用的候选


@dataclass
class ExtractionResult:
    """数据提取结果"""
    chapter_id: str
    chapter_number: int

    # 实体相关
    entities_appeared: List[EntityAppearance] = field(default_factory=list)
    entities_new: List[EntitySuggestion] = field(default_factory=list)

    # 状态和关系
    state_changes: List[StateChange] = field(default_factory=list)
    relationships_new: List[RelationshipChange] = field(default_factory=list)

    # 场景切片
    scenes_chunked: List[SceneChunk] = field(default_factory=list)

    # 章节元数据
    chapter_meta: Optional[ChapterMeta] = None

    # 不确定项和警告
    uncertain: List[UncertainMatch] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    # 统计
    total_word_count: int = 0
    processing_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "chapter_id": self.chapter_id,
            "chapter_number": self.chapter_number,
            "entities_appeared": len(self.entities_appeared),
            "entities_new": len(self.entities_new),
            "state_changes": len(self.state_changes),
            "relationships_new": len(self.relationships_new),
            "scenes_chunked": len(self.scenes_chunked),
            "uncertain": len(self.uncertain),
            "warnings": self.warnings,
            "errors": self.errors,
            "total_word_count": self.total_word_count,
        }


class DataAgent:
    """Data Agent - 数据链工程师

    职责:
    1. 从生成的章节内容中提取实体、状态变化、关系
    2. 进行场景切片
    3. 生成向量嵌入
    4. 更新全局状态
    5. 生成章节摘要和元数据
    """

    # 置信度阈值
    HIGH_CONFIDENCE = 0.8
    MEDIUM_CONFIDENCE = 0.5

    # 模板化套话检测
    TEMPLATE_PHRASES = [
        '尘埃在光柱中飞舞',
        '尘埃在光柱中起舞',
        '苦涩中带着回甘',
        '滴答，滴答',
        '咔嚓，咔嚓',
        '春蚕噬叶',
        '细雨敲窗',
        '时光的流逝',
        '命运的齿轮',
        '暴风雨前的宁静',
        '真相正伺机而动',
        '桌上摊开的文件',
        '端起一只搪瓷杯',
        '端起一只瓷杯',
        '凉茶早已凉透',
        '墙上的挂钟',
        '窗外的老槐树',
        '窗外的梧桐树',
    ]

    def __init__(self, llm: LLMClient, vector_store: VectorStore):
        self.llm = llm
        self.vector_store = vector_store

    async def process_chapter(
        self,
        generated_chapter: GeneratedChapter,
        outline: BookOutline,
        global_state: EnhancedGlobalState,
        review_score: Optional[int] = None
    ) -> ExtractionResult:
        """处理生成的章节内容

        Args:
            generated_chapter: 生成的章节内容
            outline: 全书大纲
            global_state: 全局状态
            review_score: 审校评分（可选）

        Returns:
            ExtractionResult: 提取结果
        """
        start_time = datetime.now()
        chapter_outline = generated_chapter.outline

        logger.info(f"DataAgent: 开始处理章节 - {chapter_outline.title}")

        result = ExtractionResult(
            chapter_id=generated_chapter.id,
            chapter_number=chapter_outline.order,
            total_word_count=generated_chapter.word_count
        )

        # 获取完整内容
        full_content = generated_chapter.full_content

        # Step A: 提取实体
        logger.info(f"DataAgent: 提取实体...")
        entities_result = await self._extract_entities(
            full_content, global_state
        )
        result.entities_appeared = entities_result["appeared"]
        result.entities_new = entities_result["new"]
        result.uncertain = entities_result["uncertain"]

        # Step B: 提取状态变化
        logger.info(f"DataAgent: 提取状态变化...")
        result.state_changes = await self._extract_state_changes(
            full_content, result.entities_appeared, global_state
        )

        # Step C: 提取关系变化
        logger.info(f"DataAgent: 提取关系变化...")
        result.relationships_new = await self._extract_relationships(
            full_content, result.entities_appeared
        )

        # Step D: 场景切片
        logger.info(f"DataAgent: 场景切片...")
        result.scenes_chunked = await self._chunk_scenes(
            generated_chapter, chapter_outline
        )

        # Step E: 生成章节元数据
        logger.info(f"DataAgent: 生成章节元数据...")
        result.chapter_meta = await self._generate_chapter_meta(
            full_content, chapter_outline
        )

        # Step F: 检测模板化内容（质量警告）
        logger.info(f"DataAgent: 检测模板化内容...")
        template_warnings = self._detect_template_phrases(full_content)
        result.warnings.extend(template_warnings)

        # 计算处理时间
        result.processing_time = (datetime.now() - start_time).total_seconds()

        logger.info(f"DataAgent: 章节处理完成 - "
                   f"实体{len(result.entities_appeared)}个, "
                   f"场景{len(result.scenes_chunked)}个, "
                   f"耗时{result.processing_time:.2f}秒")

        return result

    async def update_global_state(
        self,
        result: ExtractionResult,
        global_state: EnhancedGlobalState,
        generated_chapter: GeneratedChapter
    ) -> EnhancedGlobalState:
        """更新全局状态

        Args:
            result: 提取结果
            global_state: 当前全局状态
            generated_chapter: 生成的章节

        Returns:
            更新后的全局状态
        """
        logger.info(f"DataAgent: 更新全局状态...")

        # 1. 更新人物出场次数
        for entity in result.entities_appeared:
            if entity.entity_type == "角色":
                current_count = global_state.characters_mentioned.get(entity.name, 0)
                global_state.characters_mentioned[entity.name] = current_count + len(entity.mentions)
                if entity.name != (global_state.subject_profile.name if global_state.subject_profile else ""):
                    global_state.register_character(entity.name, aliases=entity.mentions[:3])

        # 1.5 注册新识别的人物，尽早建立名称锚点
        for entity in result.entities_new:
            if entity.entity_type == "角色":
                global_state.register_character(entity.name)

        # 2. 更新人物快照
        for entity in result.entities_appeared:
            if entity.entity_type == "角色" and entity.name in global_state.character_evolutions:
                traits = {
                    "mentions_in_chapter": len(entity.mentions),
                    "confidence": entity.confidence,
                }
                global_state.record_character_snapshot(entity.name, traits)

        # 3. 更新传主状态
        subject_changes = [sc for sc in result.state_changes
                          if sc.entity_id == global_state.subject_profile.name
                          if global_state.subject_profile]
        for change in subject_changes:
            if change.field == "age":
                try:
                    global_state.current_subject_age = int(change.new_value)
                except ValueError:
                    pass
            elif change.field == "mood":
                global_state.current_subject_mood = change.new_value

        # 4. 添加章节摘要
        chapter_summary = self._generate_chapter_summary(result, generated_chapter)
        global_state.add_chapter_summary(chapter_summary)

        # 5. 更新当前进度
        global_state.current_chapter_idx = result.chapter_number

        logger.info(f"DataAgent: 全局状态更新完成")
        return global_state

    async def generate_embeddings(
        self,
        result: ExtractionResult,
        generated_chapter: GeneratedChapter,
        project_root: str
    ) -> bool:
        """生成向量嵌入

        Args:
            result: 提取结果
            generated_chapter: 生成的章节
            project_root: 项目根目录

        Returns:
            是否成功
        """
        logger.info(f"DataAgent: 生成向量嵌入...")

        try:
            # 1. 索引章节摘要
            if result.chapter_meta:
                summary = self._build_chapter_summary_text(result, generated_chapter)
                self.vector_store.add_text(
                    text=summary,
                    metadata={
                        "type": "chapter_summary",
                        "chapter_id": result.chapter_id,
                        "chapter_number": result.chapter_number,
                        "source": f"chapter_{result.chapter_number:04d}_summary"
                    }
                )

            # 2. 索引场景切片
            for scene in result.scenes_chunked:
                self.vector_store.add_text(
                    text=scene.summary,
                    metadata={
                        "type": "scene",
                        "chapter_id": result.chapter_id,
                        "scene_id": scene.scene_id,
                        "location": scene.location,
                        "characters": scene.characters_present,
                        "source": f"chapter_{result.chapter_number:04d}_scene_{scene.order}"
                    }
                )

            logger.info(f"DataAgent: 向量嵌入生成完成")
            return True

        except Exception as e:
            logger.error(f"DataAgent: 向量嵌入生成失败 - {e}")
            return False

    async def _extract_entities(
        self,
        content: str,
        global_state: EnhancedGlobalState
    ) -> Dict[str, List]:
        """提取实体

        Returns:
            {"appeared": [], "new": [], "uncertain": []}
        """
        appeared = []
        new = []
        uncertain = []

        # 获取已知实体列表
        known_entities = {}
        if global_state.subject_profile:
            known_entities[global_state.subject_profile.name] = {
                "type": "角色",
                "aliases": global_state.subject_profile.aliases
            }

        for name, mapping in global_state.character_name_mappings.items():
            known_entities[name] = {
                "type": "角色",
                "aliases": mapping.aliases
            }

        # 简单的实体识别（基于已知实体和常见模式）
        # 实际实现中可以使用LLM进行更精确的提取

        # 识别已知实体
        for entity_name, entity_info in known_entities.items():
            mentions = []
            # 检查标准名称
            if entity_name in content:
                mentions.append(entity_name)
            # 检查别名
            for alias in entity_info.get("aliases", []):
                if alias in content and alias not in mentions:
                    mentions.append(alias)

            if mentions:
                # 提取上下文片段
                snippets = []
                for mention in mentions:
                    idx = content.find(mention)
                    if idx >= 0:
                        start = max(0, idx - 30)
                        end = min(len(content), idx + len(mention) + 30)
                        snippets.append(content[start:end])

                entity_app = EntityAppearance(
                    entity_id=entity_name,
                    entity_type=entity_info["type"],
                    name=entity_name,
                    mentions=mentions,
                    confidence=0.9,  # 已知实体置信度高
                    context_snippets=snippets[:3]  # 最多3个片段
                )
                appeared.append(entity_app)

        # 识别潜在的新实体（简单启发式）
        # 实际实现中应该使用NER模型或LLM
        new_entities = self._detect_potential_new_entities(content, known_entities)
        for ne in new_entities:
            new.append(EntitySuggestion(
                suggested_id=generate_id("entity"),
                name=ne["name"],
                entity_type=ne["type"],
                tier="装饰",
                evidence=ne["evidence"]
            ))

        return {
            "appeared": appeared,
            "new": new,
            "uncertain": uncertain
        }

    def _detect_potential_new_entities(
        self,
        content: str,
        known_entities: Dict
    ) -> List[Dict]:
        """检测潜在的新实体（启发式）"""
        potential = []

        # 简单的人名检测模式（中文人名常见模式）
        # 实际实现中应该使用更精确的NER
        name_patterns = [
            r'[\u4e00-\u9fa5]{2,3}(?=先生|女士|老师|医生|教授)',
            r'[\u4e00-\u9fa5]{2,3}(?=说|回忆|告诉|提到)',
        ]

        found_names = set()
        for pattern in name_patterns:
            matches = re.findall(pattern, content)
            found_names.update(matches)

        # 过滤已知实体
        known_names = set(known_entities.keys())
        for name in known_names:
            known_names.update(known_entities[name].get("aliases", []))

        for name in found_names:
            if name not in known_names and len(name) >= 2:
                # 检查上下文
                idx = content.find(name)
                context = content[max(0, idx-20):min(len(content), idx+len(name)+20)]
                potential.append({
                    "name": name,
                    "type": "角色",
                    "evidence": context
                })

        return potential[:5]  # 最多返回5个

    async def _extract_state_changes(
        self,
        content: str,
        entities: List[EntityAppearance],
        global_state: EnhancedGlobalState
    ) -> List[StateChange]:
        """提取状态变化"""
        changes = []

        # 简单的状态变化检测（启发式）
        # 实际实现中应该使用LLM进行语义理解

        # 检测年龄变化
        age_patterns = [
            r'(\d+)[岁周岁]',
            r'(?:那年|当时|这一年).*?(\d+)[岁周岁]',
        ]

        for pattern in age_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                try:
                    new_age = int(match)
                    current_age = global_state.current_subject_age
                    if current_age and new_age != current_age:
                        changes.append(StateChange(
                            entity_id=global_state.subject_profile.name if global_state.subject_profile else "传主",
                            field="age",
                            old_value=str(current_age),
                            new_value=str(new_age),
                            reason=f"章节中提及年龄为{new_age}岁",
                            confidence=0.7
                        ))
                except ValueError:
                    pass

        return changes

    async def _extract_relationships(
        self,
        content: str,
        entities: List[EntityAppearance]
    ) -> List[RelationshipChange]:
        """提取关系变化"""
        relationships = []

        # 简单的关系检测（启发式）
        # 实际实现中应该使用LLM进行语义理解

        # 检测人物共现作为潜在关系
        char_entities = [e for e in entities if e.entity_type == "角色"]
        if len(char_entities) >= 2:
            for i, char1 in enumerate(char_entities):
                for char2 in char_entities[i+1:]:
                    # 检查是否在同一段落中出现
                    if self._check_cooccurrence(content, char1.name, char2.name):
                        relationships.append(RelationshipChange(
                            from_entity=char1.name,
                            to_entity=char2.name,
                            relation_type="同场出现",
                            description=f"在第{char1.entity_id}章中同时出现",
                            is_new=True
                        ))

        return relationships

    def _check_cooccurrence(
        self,
        content: str,
        name1: str,
        name2: str,
        window: int = 200
    ) -> bool:
        """检查两个实体是否在相近位置共现"""
        idx1 = content.find(name1)
        idx2 = content.find(name2)

        if idx1 < 0 or idx2 < 0:
            return False

        return abs(idx1 - idx2) < window

    async def _chunk_scenes(
        self,
        generated_chapter: GeneratedChapter,
        chapter_outline: ChapterOutline
    ) -> List[SceneChunk]:
        """场景切片"""
        scenes = []

        # 基于小节进行切片
        for i, section in enumerate(generated_chapter.sections):
            section_outline = None
            if i < len(chapter_outline.sections):
                section_outline = chapter_outline.sections[i]

            # 尝试识别场景边界（简单按段落分割）
            paragraphs = section.content.split('\n\n')

            scene = SceneChunk(
                scene_id=generate_id("scene"),
                chapter_id=generated_chapter.id,
                order=i + 1,
                location=section_outline.key_events[0] if section_outline and section_outline.key_events else "",
                time_mark=chapter_outline.time_period_start or "",
                characters_present=chapter_outline.characters_present,
                summary=truncate_text(section.content, 100),
                content=section.content,
                word_count=section.word_count
            )
            scenes.append(scene)

        return scenes

    async def _generate_chapter_meta(
        self,
        content: str,
        chapter_outline: ChapterOutline
    ) -> ChapterMeta:
        """生成章节元数据"""
        meta = ChapterMeta(chapter_number=chapter_outline.order)

        # 检测开头模式
        first_para = content[:200]
        if any(word in first_para for word in ['"', '"', '"', '"']):
            meta.pattern_opening = "对话开场"
        elif any(word in first_para for word in ['那是', '当时', '那一年']):
            meta.pattern_opening = "回忆开场"
        else:
            meta.pattern_opening = "叙述开场"

        # 检测结尾情绪
        last_para = content[-200:]
        emotion_indicators = {
            "感慨": ['感慨', '感叹', '时光', '岁月'],
            "希望": ['希望', '期待', '未来', '明天'],
            "平静": ['平静', '安静', '宁静', '淡然'],
            "忧伤": ['忧伤', '悲伤', '遗憾', '难过'],
        }
        for emotion, indicators in emotion_indicators.items():
            if any(word in last_para for word in indicators):
                meta.ending_emotion = emotion
                break

        # 检测钩子（简单启发式）
        hook_indicators = ['后来', '不久', '没想到', '然而']
        if any(word in last_para for word in hook_indicators):
            meta.hook_type = "悬念钩"
            meta.hook_strength = "medium"
            meta.hook_content = "留下后续发展的线索"
        else:
            meta.hook_type = "自然收束"
            meta.hook_strength = "weak"

        # 信息密度估计
        word_count = count_chinese_words(content)
        para_count = len(content.split('\n\n'))
        if para_count > 0:
            density = word_count / para_count
            if density > 150:
                meta.info_density = "high"
            elif density < 80:
                meta.info_density = "low"
            else:
                meta.info_density = "medium"

        return meta

    def _detect_template_phrases(self, content: str) -> List[str]:
        """检测模板化套话"""
        warnings = []

        for phrase in self.TEMPLATE_PHRASES:
            if phrase in content:
                warnings.append(f"检测到模板化表达: '{phrase}'")

        # 检测重复意象
        repetitive_patterns = [
            (r'晨光|晨光熹微|晨光透过', "晨光重复"),
            (r'夕阳|夕阳西下|落日', "夕阳重复"),
            (r'凉茶|茶水|茶杯', "喝茶重复"),
            (r'挂钟|钟表|滴答', "钟表重复"),
            (r'钢笔|笔尖|沙沙', "写字重复"),
            (r'窗外|看着窗外|望向窗外', "窗外重复"),
        ]

        for pattern, desc in repetitive_patterns:
            matches = re.findall(pattern, content)
            if len(matches) > 2:
                warnings.append(f"意象重复: {desc}出现{len(matches)}次")

        return warnings

    def _generate_chapter_summary(
        self,
        result: ExtractionResult,
        generated_chapter: GeneratedChapter
    ) -> str:
        """生成章节摘要文本"""
        parts = [
            f"第{result.chapter_number}章",
            generated_chapter.outline.title,
        ]

        if result.chapter_meta:
            parts.append(f"情绪: {result.chapter_meta.ending_emotion}")

        if result.entities_appeared:
            char_names = [e.name for e in result.entities_appeared if e.entity_type == "角色"]
            if char_names:
                parts.append(f"出场: {', '.join(char_names[:3])}")

        return " | ".join(parts)

    def _build_chapter_summary_text(
        self,
        result: ExtractionResult,
        generated_chapter: GeneratedChapter
    ) -> str:
        """构建用于向量索引的章节摘要文本"""
        lines = [
            f"第{result.chapter_number}章: {generated_chapter.outline.title}",
            f"",
            f"内容概要: {generated_chapter.outline.summary}",
            f"",
            f"出场角色: {', '.join([e.name for e in result.entities_appeared if e.entity_type == '角色'])}",
        ]

        if result.chapter_meta:
            lines.extend([
                f"",
                f"结尾情绪: {result.chapter_meta.ending_emotion}",
                f"钩子类型: {result.chapter_meta.hook_type}",
            ])

        return "\n".join(lines)

    async def generate_chapter_summary_file(
        self,
        result: ExtractionResult,
        generated_chapter: GeneratedChapter,
        output_path: str
    ) -> str:
        """生成章节摘要文件（Markdown格式）

        Returns:
            文件路径
        """
        meta = result.chapter_meta or ChapterMeta(chapter_number=result.chapter_number)

        lines = [
            f"---",
            f"chapter: {result.chapter_number:04d}",
            f"title: {generated_chapter.outline.title}",
            f"word_count: {result.total_word_count}",
        ]

        if meta:
            lines.extend([
                f"ending_emotion: {meta.ending_emotion}",
                f"hook_type: {meta.hook_type}",
                f"hook_strength: {meta.hook_strength}",
            ])

        lines.extend([
            f"---",
            f"",
            f"## 剧情摘要",
            f"",
            truncate_text(generated_chapter.outline.summary, 200),
            f"",
            f"## 出场实体",
            f"",
        ])

        for entity in result.entities_appeared:
            lines.append(f"- **{entity.name}** ({entity.entity_type})")

        if result.state_changes:
            lines.extend([
                f"",
                f"## 状态变化",
                f"",
            ])
            for change in result.state_changes:
                lines.append(f"- {change.entity_id}: {change.field} {change.old_value} → {change.new_value}")

        if result.scenes_chunked:
            lines.extend([
                f"",
                f"## 场景",
                f"",
            ])
            for scene in result.scenes_chunked:
                lines.append(f"- 场景{scene.order}: {scene.location} ({scene.word_count}字)")

        content = "\n".join(lines)

        # 写入文件
        import os
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return output_path
