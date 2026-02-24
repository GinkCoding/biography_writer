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
        
        # 提取事件信息（不截断，保留完整描述）
        events_text = "\n".join([
            f"- {e.date or '未知时间'}: {e.title} - {e.description}"
            for e in events[:8]  # 增加到8个事件
        ])
        
        # 确定章节时间范围
        dates = [e.date for e in events if e.date]
        time_start = min(dates) if dates else None
        time_end = max(dates) if dates else None
        
        # 推断时代背景
        era_hint = self._get_era_hint(time_start)
        
        prompt = f"""请为传记的第{chapter_num}章生成详细大纲。

传主: {subject.name}
章节位置: 第{chapter_num}章 / 共{total_chapters}章
时间范围: {time_start or '待定'} 至 {time_end or '待定'}
时代背景: {era_hint}
目标字数: {target_words}字

本章涉及的主要事件（来自原始采访）:
{events_text}

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
      "key_events": ["关联的具体事件名称"],
      "time_location": "具体时间和地点，如：1982年春，佛山陈家村"
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
        """生成默认章节大纲"""
        sections = []
        for i in range(4):
            sections.append(SectionOutline(
                id=generate_id("section", chapter_num, i),
                title=f"第{i+1}节",
                target_words=target_words // 4,
                content_summary="基于采访素材展开具体叙述",
                emotional_tone="平实",
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
        style: WritingStyle
    ) -> str:
        """生成前言"""
        # 提取关键信息用于前言
        key_events = [e.title for e in events[:5] if e.title]
        
        prompt = f"""请为《{subject.name}传》撰写一段前言（300-500字）。

传主信息:
- 姓名: {subject.name}
- 出生: {subject.birth_date or '不详'} {subject.birth_place or ''}
- 职业: {', '.join(subject.occupation) if subject.occupation else '待考'}
- 性格: {', '.join(subject.personality_traits) if subject.personality_traits else '多元'}

生平关键事件:
{chr(10).join(key_events)}

写作风格: {style.value}

前言应该:
1. 交代写作缘起和采访背景（何时何地采访）
2. 简要介绍传主的历史地位和影响
3. 点明传记的核心主题和价值
4. 引发读者阅读兴趣
5. 【关键】提及具体的采访时间、地点和方式，增强真实感
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
        style: WritingStyle
    ) -> str:
        """生成后记"""
        prompt = f"""请为《{subject.name}传》撰写一段后记（300-500字）。

传主信息:
- 姓名: {subject.name}
- 价值观: {', '.join(subject.core_values) if subject.core_values else '坚韧、智慧'}
- 主要经历: {subject.occupation[0] if subject.occupation else '丰富多彩'}

写作风格: {style.value}

后记应该:
1. 总结传主的一生（基于具体事实，而非空泛评价）
2. 提炼其人生智慧和启示
3. 表达作者基于采访的感悟
4. 留给读者思考空间
5. 【关键】引用采访中的原话或具体细节作为总结
"""
        
        messages = [
            {"role": "system", "content": "你是一位资深传记作家，擅长基于事实总结人生。"},
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
