"""第四层：迭代生成层 (Iterative Generation)"""
import asyncio
from typing import List, Dict, Optional, AsyncIterator
from pathlib import Path
from datetime import datetime
from loguru import logger

from src.llm_client import LLMClient
from src.models import (
    BookOutline, ChapterOutline, SectionOutline,
    GeneratedSection, GeneratedChapter, GlobalState,
    WritingStyle, InterviewMaterial
)
from src.layers.data_ingestion import VectorStore
from src.utils import count_chinese_words, truncate_text, generate_id


class ContextAssembler:
    """上下文组装器"""
    
    def __init__(self, llm: LLMClient, vector_store: VectorStore):
        self.llm = llm
        self.vector_store = vector_store
    
    async def assemble_context(
        self,
        section: SectionOutline,
        chapter: ChapterOutline,
        outline: BookOutline,
        global_state: Dict,
        previous_section_summary: Optional[str] = None
    ) -> Dict[str, str]:
        """
        组装完整的生成上下文
        
        Returns:
            包含各部分内容的字典
        """
        # 1. 全局设定
        global_context = self._build_global_context(outline, global_state)
        
        # 2. 当前小节大纲
        section_context = self._build_section_context(section, chapter)
        
        # 3. 检索相关素材
        material_context = await self._retrieve_materials(section, chapter)
        
        # 4. 前文衔接
        continuity_context = self._build_continuity_context(
            previous_section_summary, global_state
        )
        
        # 5. 时代背景增强（可选）
        era_context = self._build_era_context(chapter.time_period_start)
        
        return {
            "global": global_context,
            "section": section_context,
            "materials": material_context,
            "continuity": continuity_context,
            "era": era_context,
        }
    
    def _build_global_context(self, outline: BookOutline, global_state: Dict) -> str:
        """构建全局上下文"""
        subject = global_state.get("subject_name", "传主")
        age = global_state.get("subject_age", "未知")
        
        return f"""=== 全局设定 ===
传记标题: {outline.title}
传主姓名: {subject}
当前年龄: {age}岁
写作风格: {outline.style.value}
整体进度: {global_state.get('chapter_progress', '')}
传记主题: {outline.chapters[0].summary if outline.chapters else ''}
"""
    
    def _build_section_context(self, section: SectionOutline, chapter: ChapterOutline) -> str:
        """构建小节上下文"""
        return f"""=== 当前小节大纲 ===
章节: {chapter.title} (第{chapter.order}章)
小节: {section.title}
目标字数: {section.target_words}字
内容概要: {section.content_summary}
情感基调: {section.emotional_tone}
关联事件: {', '.join(section.key_events) if section.key_events else '无特定事件'}
"""
    
    async def _retrieve_materials(
        self,
        section: SectionOutline,
        chapter: ChapterOutline
    ) -> str:
        """检索相关素材"""
        # 构建检索查询
        query = f"{chapter.title} {section.title} {section.content_summary}"
        
        materials = self.vector_store.search(query, n_results=5)
        
        if not materials:
            return "=== 相关素材 ===\n无直接相关素材\n"
        
        material_texts = []
        for i, m in enumerate(materials, 1):
            material_texts.append(
                f"[素材{i}] 来源: {m.source_file}\n"
                f"内容: {truncate_text(m.content, 200)}\n"
            )
        
        return "=== 相关素材 ===\n" + "\n".join(material_texts)
    
    def _build_continuity_context(
        self,
        previous_summary: Optional[str],
        global_state: Dict
    ) -> str:
        """构建上下文衔接信息"""
        parts = ["=== 上下文衔接 ==="]
        
        # 上一节摘要
        if previous_summary:
            parts.append(f"上一节结尾:\n{truncate_text(previous_summary, 150)}")
        
        # 最近章节摘要
        summaries = global_state.get("previous_summaries", [])
        if summaries:
            parts.append(f"前几章脉络:\n" + " → ".join(summaries[-3:]))
        
        # 频繁出现的人物
        frequent_chars = global_state.get("frequent_characters", [])
        if frequent_chars:
            char_list = ", ".join([f"{name}({count}次)" for name, count in frequent_chars[:5]])
            parts.append(f"活跃人物: {char_list}")
        
        return "\n".join(parts)
    
    def _build_era_context(self, time_period: Optional[str]) -> str:
        """构建时代背景（简化版，可扩展为外部知识库查询）"""
        if not time_period:
            return "=== 时代背景 ===\n未指定具体年代\n"
        
        year = time_period[:4] if len(time_period) >= 4 else ""
        
        # 简单的年代背景模板（可扩展）
        era_hints = {
            "1950": "新中国成立初期，百废待兴，充满干劲与激情",
            "1960": "困难时期，物质匮乏但精神充实",
            "1970": "文革时期，社会动荡，个人命运起伏",
            "1980": "改革开放初期，思想解放，机遇涌现",
            "1990": "市场经济浪潮，下海经商，社会转型",
            "2000": "新世纪，互联网兴起，全球化加速",
            "2010": "移动互联网时代，创业热潮，社会快速变革",
        }
        
        era_desc = ""
        for decade, desc in era_hints.items():
            if year.startswith(decade[:3]):
                era_desc = desc
                break
        
        return f"""=== 时代背景 ===
时间: {time_period[:4] if time_period else '未知'}年代
背景: {era_desc or '中国社会发展的重要时期'}
提示: 可适当融入当时的社会风貌、物价、流行文化等细节增强真实感
"""


class ContentGenerationEngine:
    """内容扩写引擎"""
    
    def __init__(self, llm: LLMClient):
        self.llm = llm
    
    async def generate_section(
        self,
        context: Dict[str, str],
        style: WritingStyle,
        target_words: int
    ) -> GeneratedSection:
        """
        生成单节内容
        """
        # 构建完整提示词
        system_prompt = self._build_system_prompt(style)
        user_prompt = self._build_generation_prompt(context, target_words)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # 调用LLM生成
        logger.info(f"正在生成内容: {context['section'].split(chr(10))[2] if chr(10) in context['section'] else '小节'}...")
        
        content = await self.llm.complete(
            messages,
            temperature=0.75,
            max_tokens=min(4000, target_words * 2)  # 粗略估算
        )
        
        # 清理和验证
        content = self._post_process_content(content)
        actual_words = count_chinese_words(content)
        
        # 如果字数不足，进行扩写
        if actual_words < target_words * 0.8:
            logger.warning(f"字数不足 ({actual_words}/{target_words})，进行扩写...")
            content = await self._expand_content(
                content, context, target_words - actual_words
            )
            actual_words = count_chinese_words(content)
        
        return GeneratedSection(
            id=generate_id("section_content"),
            chapter_id="",  # 由上层填充
            title=context.get("section_title", "小节"),
            content=content,
            word_count=actual_words,
            generation_time=datetime.now()
        )
    
    async def generate_section_stream(
        self,
        context: Dict[str, str],
        style: WritingStyle
    ) -> AsyncIterator[str]:
        """流式生成内容"""
        system_prompt = self._build_system_prompt(style)
        user_prompt = self._build_generation_prompt(context, 0)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        async for chunk in self.llm.complete_stream(messages, temperature=0.75):
            yield chunk
    
    def _build_system_prompt(self, style: WritingStyle) -> str:
        """构建系统提示词"""
        # 加载风格配置
        import yaml
        from pathlib import Path
        
        style_file = Path(__file__).parent.parent.parent / "config" / "styles.yaml"
        with open(style_file, "r", encoding="utf-8") as f:
            styles_config = yaml.safe_load(f)
        
        style_config = styles_config.get("styles", {}).get(style.value, {})
        base_prompt = style_config.get("system_prompt", "")
        
        # 添加通用要求
        full_prompt = f"""{base_prompt}

=== 写作要求 ===
1. 基于提供的素材进行扩写，不要脱离素材随意发挥
2. 注重细节描写：场景、动作、对话、心理活动
3. 适当运用感官描写（视觉、听觉、嗅觉等）
4. 时间线和人物关系必须与上下文保持一致
5. 情感表达要符合指定的情感基调
6. 使用中文写作，语言流畅自然

=== 禁止事项 ===
1. 不得虚构不存在的人物
2. 不得篡改已发生事件的时间顺序
3. 不得编造不符合传主身份的言论
4. 避免过度堆砌华丽辞藻而缺乏实质内容
"""
        return full_prompt
    
    def _build_generation_prompt(self, context: Dict[str, str], target_words: int) -> str:
        """构建生成提示词"""
        word_hint = f"\n=== 字数要求 ===\n本节目标字数：{target_words}字\n" if target_words else ""
        
        return f"""请根据以下信息撰写传记内容：

{context.get('global', '')}

{context.get('section', '')}

{context.get('materials', '')}

{context.get('continuity', '')}

{context.get('era', '')}
{word_hint}

请直接输出正文内容，不要包含章节标题。确保内容紧扣大纲，事实准确，细节丰富。
"""
    
    def _post_process_content(self, content: str) -> str:
        """后处理生成的内容"""
        # 移除可能的格式标记
        content = content.strip()
        
        # 移除开头的标题标记
        if content.startswith("#"):
            content = content.lstrip("#").strip()
        
        # 规范化段落
        content = content.replace("\n\n\n", "\n\n")
        
        return content
    
    async def _expand_content(
        self,
        existing_content: str,
        context: Dict[str, str],
        additional_words: int
    ) -> str:
        """扩写内容以达到目标字数"""
        prompt = f"""请对以下内容进行扩写，增加约{additional_words}字的内容。

当前内容:
{existing_content}

扩写要求:
1. 在现有内容基础上增加细节描写
2. 可以补充：环境描写、心理活动、对话内容、他人反应等
3. 保持原有风格和叙事逻辑
4. 不要重复已有内容
5. 不要改变原有的事实陈述

请输出完整的扩写后内容（包含原文）。
"""
        
        messages = [
            {"role": "system", "content": "你是一位擅长细节描写作家。"},
            {"role": "user", "content": prompt}
        ]
        
        expanded = await self.llm.complete(messages, temperature=0.7)
        return expanded.strip()


class IterativeGenerationLayer:
    """迭代生成层主类"""
    
    def __init__(self, llm: LLMClient, vector_store: VectorStore):
        self.llm = llm
        self.context_assembler = ContextAssembler(llm, vector_store)
        self.generation_engine = ContentGenerationEngine(llm)
    
    async def generate_chapter(
        self,
        chapter_outline: ChapterOutline,
        book_outline: BookOutline,
        global_state: Dict,
        progress_callback: Optional[callable] = None
    ) -> GeneratedChapter:
        """
        生成完整章节
        """
        logger.info(f"开始生成第{chapter_outline.order}章: {chapter_outline.title}")
        
        sections = []
        previous_summary = None
        
        for i, section_outline in enumerate(chapter_outline.sections):
            # 更新进度
            if progress_callback:
                progress_callback(f"第{chapter_outline.order}章 - {section_outline.title}")
            
            # 组装上下文
            context = await self.context_assembler.assemble_context(
                section=section_outline,
                chapter=chapter_outline,
                outline=book_outline,
                global_state=global_state,
                previous_section_summary=previous_summary
            )
            
            # 提取小节标题
            context["section_title"] = section_outline.title
            
            # 生成内容
            section = await self.generation_engine.generate_section(
                context=context,
                style=book_outline.style,
                target_words=section_outline.target_words
            )
            section.chapter_id = chapter_outline.id
            
            sections.append(section)
            
            # 更新摘要供下一节使用
            previous_summary = truncate_text(section.content, 200)
            
            logger.info(f"  完成小节 {i+1}/{len(chapter_outline.sections)}: {section.word_count}字")
        
        # 生成过渡段落
        transition = await self._generate_transition(chapter_outline, book_outline)
        
        return GeneratedChapter(
            id=generate_id("chapter_gen", chapter_outline.order),
            outline=chapter_outline,
            sections=sections,
            transition_paragraph=transition
        )
    
    async def _generate_transition(
        self,
        chapter: ChapterOutline,
        outline: BookOutline
    ) -> Optional[str]:
        """生成与下一章的过渡段落"""
        # 如果是最后一章，不需要过渡
        if chapter.order >= outline.total_chapters:
            return None
        
        # 获取下一章标题
        next_chapter = None
        for c in outline.chapters:
            if c.order == chapter.order + 1:
                next_chapter = c
                break
        
        if not next_chapter:
            return None
        
        prompt = f"""请为以下两章之间写一段过渡文字（50-100字），作为本章结尾：

本章: {chapter.title} - {chapter.summary}

下章: {next_chapter.title} - {next_chapter.summary}

要求:
1. 自然承接本章内容
2. 引出下一章主题
3. 营造悬念或期待感
4. 不要重复本章已写内容
"""
        
        messages = [
            {"role": "system", "content": "你是一位擅长结构衔接的作家。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            transition = await self.llm.complete(messages, temperature=0.7)
            return transition.strip()
        except Exception as e:
            logger.error(f"生成过渡段落失败: {e}")
            return None