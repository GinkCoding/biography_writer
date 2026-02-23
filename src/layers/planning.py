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
        total_chapters: int = 25
    ) -> BookOutline:
        """
        生成完整的书籍大纲
        
        Args:
            timeline: 全局时间线
            style: 写作风格
            target_words: 目标字数
            total_chapters: 总章节数
        """
        logger.info(f"开始生成大纲，目标字数: {target_words}, 章节数: {total_chapters}")
        
        subject = timeline.subject
        events = timeline.events
        
        # 1. 基于时间线划分章节
        chapter_distribution = self._distribute_events_to_chapters(
            events, total_chapters
        )
        
        # 2. 为每个章节生成详细大纲
        chapters = []
        for i, chapter_events in enumerate(chapter_distribution, 1):
            chapter = await self._generate_chapter_outline(
                chapter_num=i,
                total_chapters=total_chapters,
                events=chapter_events,
                subject=subject,
                target_words=target_words // total_chapters
            )
            chapters.append(chapter)
        
        # 3. 生成前言和后记
        prologue = await self._generate_prologue(subject, events, style)
        epilogue = await self._generate_epilogue(subject, events, style)
        
        # 4. 构建完整大纲
        outline = BookOutline(
            title=f"{subject.name}传",
            subtitle=self._generate_subtitle(subject),
            subject_name=subject.name,
            style=style,
            total_chapters=total_chapters,
            target_total_words=target_words,
            chapters=chapters,
            prologue=prologue,
            epilogue=epilogue
        )
        
        logger.info(f"大纲生成完成: {outline.title}, 共 {len(chapters)} 章")
        return outline
    
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
        target_words: int
    ) -> ChapterOutline:
        """生成单章大纲"""
        
        # 提取事件信息
        events_text = "\n".join([
            f"- {e.date or '未知时间'}: {e.title} - {e.description[:100]}..."
            for e in events[:5]  # 限制事件数量
        ])
        
        # 确定章节时间范围
        dates = [e.date for e in events if e.date]
        time_start = min(dates) if dates else None
        time_end = max(dates) if dates else None
        
        prompt = f"""请为传记的第{chapter_num}章生成详细大纲。

传主: {subject.name}
章节位置: 第{chapter_num}章 / 共{total_chapters}章
时间范围: {time_start or '待定'} 至 {time_end or '待定'}
目标字数: {target_words}字

本章涉及的主要事件:
{events_text}

请生成以下内容（JSON格式）:
{{
  "title": "章节标题（8-12字，有吸引力）",
  "summary": "本章内容概要（50-100字）",
  "characters_present": ["本章出现的主要人物"],
  "sections": [
    {{
      "title": "小节标题",
      "target_words": {target_words // 4},
      "content_summary": "本节要写什么（50字左右）",
      "emotional_tone": "情感基调（如：沉重、激昂、温馨、悬疑）",
      "key_events": ["关联的事件"]
    }}
  ]
}}

要求:
1. 将本章分为4个小节
2. 每个小节有明确的内容边界
3. 小节之间要有逻辑递进关系
4. 情感基调要有起伏变化
"""
        
        messages = [
            {"role": "system", "content": "你是一位资深的传记文学编辑，擅长设计章节结构。请只返回JSON格式。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await self.llm.complete(messages, temperature=0.6)
            data = self._parse_json_response(response)
            
            # 构建小节大纲
            sections = []
            for i, sec_data in enumerate(data.get("sections", [])):
                sections.append(SectionOutline(
                    id=generate_id("section", chapter_num, i),
                    title=sec_data.get("title", f"第{i+1}节"),
                    target_words=sec_data.get("target_words", target_words // 4),
                    key_events=sec_data.get("key_events", []),
                    content_summary=sec_data.get("content_summary", ""),
                    emotional_tone=sec_data.get("emotional_tone", "平实"),
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
    
    def _default_chapter_outline(self, chapter_num: int, target_words: int) -> ChapterOutline:
        """生成默认章节大纲"""
        sections = []
        for i in range(4):
            sections.append(SectionOutline(
                id=generate_id("section", chapter_num, i),
                title=f"第{i+1}节",
                target_words=target_words // 4,
                content_summary="待生成内容",
                emotional_tone="平实",
            ))
        
        return ChapterOutline(
            id=generate_id("chapter", chapter_num),
            title=f"第{chapter_num}章",
            order=chapter_num,
            summary="本章内容概要待补充",
            sections=sections
        )
    
    async def _generate_prologue(
        self,
        subject: CharacterProfile,
        events: List,
        style: WritingStyle
    ) -> str:
        """生成前言"""
        prompt = f"""请为《{subject.name}传》撰写一段前言（300-500字）。

传主信息:
- 姓名: {subject.name}
- 出生: {subject.birth_date or '不详'} {subject.birth_place or ''}
- 职业: {', '.join(subject.occupation) if subject.occupation else '待考'}
- 性格: {', '.join(subject.personality_traits) if subject.personality_traits else '多元'}

写作风格: {style.value}

前言应该:
1. 交代写作缘起和采访背景
2. 简要介绍传主的历史地位和影响
3. 点明传记的核心主题和价值
4. 引发读者阅读兴趣
"""
        
        messages = [
            {"role": "system", "content": "你是一位资深出版人，擅长撰写传记前言。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await self.llm.complete(messages, temperature=0.7)
            return response.strip()
        except Exception as e:
            logger.error(f"生成前言失败: {e}")
            return f"{subject.name}是一位{subject.occupation[0] if subject.occupation else '非凡人物'}，本书通过深入采访，还原其真实的人生轨迹。"
    
    async def _generate_epilogue(
        self,
        subject: CharacterProfile,
        events: List,
        style: WritingStyle
    ) -> str:
        """生成后记"""
        prompt = f"""请为《{subject.name}传》撰写一段后记（300-500字）。

传主信息:
- 姓名: {subject.name}
- 价值观: {', '.join(subject.core_values) if subject.core_values else '坚韧、智慧'}

写作风格: {style.value}

后记应该:
1. 总结传主的一生
2. 提炼其人生智慧和启示
3. 表达作者的感悟和评价
4. 留给读者思考空间
"""
        
        messages = [
            {"role": "system", "content": "你是一位资深传记作家，擅长总结人生。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await self.llm.complete(messages, temperature=0.7)
            return response.strip()
        except Exception as e:
            logger.error(f"生成后记失败: {e}")
            return f"{subject.name}的一生，是一部充满启示的人生教科书。"
    
    def _generate_subtitle(self, subject: CharacterProfile) -> str:
        """生成副标题"""
        hints = []
        if subject.occupation:
            hints.append(subject.occupation[0])
        if subject.personality_traits:
            hints.append(subject.personality_traits[0])
        
        if hints:
            return f"一个{'的'.join(hints)}的一生"
        return "一部真实的人生记录"
    
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