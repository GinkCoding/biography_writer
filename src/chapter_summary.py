"""
章节梗概生成器 - 用于保持跨章节人物一致性

在每章生成后，自动生成200-300字的章节梗概，包含：
- 核心人物及其关键信息（名字、关系、状态）
- 重要事件和转折点
- 人物关系变化
- 时间线推进

下一章生成时，将梗概注入提示词作为"前情提要"。
"""

import json
import re
from typing import Dict, List, Optional
from dataclasses import dataclass
from pathlib import Path

from src.llm_client import LLMClient
from src.utils import count_chinese_words


@dataclass
class ChapterSummary:
    """章节梗概"""
    chapter_num: int
    chapter_title: str
    summary: str  # 200-300字梗概
    key_characters: Dict[str, str]  # 人物名 -> 关键信息
    key_events: List[str]  # 重要事件
    character_relationships: Dict[str, str]  # 人物关系状态
    time_range: str  # 时间范围
    
    def to_prompt_text(self) -> str:
        """转换为提示词文本"""
        lines = [
            f"【第{self.chapter_num}章《{self.chapter_title}》前情提要】",
            "",
            self.summary,
            "",
            "【关键人物状态】"
        ]
        for name, info in self.key_characters.items():
            lines.append(f"  - {name}: {info}")
        
        if self.character_relationships:
            lines.extend(["", "【人物关系】"])
            for relation, status in self.character_relationships.items():
                lines.append(f"  - {relation}: {status}")
        
        return "\n".join(lines)


class ChapterSummaryGenerator:
    """章节梗概生成器"""
    
    def __init__(self, llm: LLMClient, book_id: str):
        self.llm = llm
        self.book_id = book_id
        self.summary_cache: Dict[int, ChapterSummary] = {}
        self.cache_file = Path(".cache") / f"{book_id}_chapter_summaries.json"
        self._load_cache()
    
    def _load_cache(self):
        """加载缓存"""
        if self.cache_file.exists():
            try:
                data = json.loads(self.cache_file.read_text(encoding='utf-8'))
                for item in data.get('summaries', []):
                    summary = ChapterSummary(**item)
                    self.summary_cache[summary.chapter_num] = summary
            except Exception:
                pass
    
    def _save_cache(self):
        """保存缓存"""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'summaries': [
                {
                    'chapter_num': s.chapter_num,
                    'chapter_title': s.chapter_title,
                    'summary': s.summary,
                    'key_characters': s.key_characters,
                    'key_events': s.key_events,
                    'character_relationships': s.character_relationships,
                    'time_range': s.time_range
                }
                for s in self.summary_cache.values()
            ]
        }
        self.cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    
    async def generate_summary(
        self,
        chapter_num: int,
        chapter_title: str,
        chapter_content: str,
        time_range: str,
        existing_summary: Optional[ChapterSummary] = None
    ) -> ChapterSummary:
        """
        生成章节梗概
        
        Args:
            chapter_num: 章节编号
            chapter_title: 章节标题
            chapter_content: 完整章节内容
            time_range: 时间范围
            existing_summary: 已有的梗概（用于更新）
        """
        # 检查缓存
        if chapter_num in self.summary_cache and not existing_summary:
            return self.summary_cache[chapter_num]
        
        # 构建提示词
        prompt = self._build_summary_prompt(chapter_content, chapter_title)
        
        # 调用LLM生成梗概
        response = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": "你是一位专业的编辑，擅长提炼故事核心要素。请用200-300字简洁概括章节内容，重点提取人物关键信息。只输出摘要正文。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
            temperature=0.3,
        )
        
        summary_text = response.strip()
        
        # 解析关键信息
        key_info = await self._extract_key_info(chapter_content)
        
        summary = ChapterSummary(
            chapter_num=chapter_num,
            chapter_title=chapter_title,
            summary=summary_text,
            key_characters=key_info.get('characters', {}),
            key_events=key_info.get('events', []),
            character_relationships=key_info.get('relationships', {}),
            time_range=time_range
        )
        
        # 缓存并保存
        self.summary_cache[chapter_num] = summary
        self._save_cache()
        
        return summary
    
    def _build_summary_prompt(self, content: str, title: str) -> str:
        """构建摘要提示词"""
        # 截取章节开头、中间、结尾各一部分
        total_chars = len(content)
        if total_chars > 3000:
            beginning = content[:1000]
            middle_start = total_chars // 2 - 500
            middle = content[middle_start:middle_start + 1000]
            end = content[-1000:]
            excerpt = f"【开头】\n{beginning}\n\n【中间】\n{middle}\n\n【结尾】\n{end}"
        else:
            excerpt = content
        
        return f"""请为《{title}》生成200-300字的章节梗概。

要求：
1. 包含核心情节发展
2. 明确关键人物及其状态（名字、身份、关键事件）
3. 突出重要转折
4. 语言简洁，用于下一章参考

章节内容：
{excerpt}

请输出：
1. 章节梗概（200-300字）
2. 关键人物列表（名字: 关键信息）
3. 重要事件列表
4. 人物关系状态"""
    
    async def _extract_key_info(self, content: str) -> Dict:
        """提取关键信息"""
        prompt = f"""从以下章节内容中提取关键信息：

{content[:2000]}

请提取并返回JSON格式：
{{
  "characters": {{"人物名": "关键信息（身份、状态、重要行动）"}},
  "events": ["重要事件1", "重要事件2"],
  "relationships": {{"人物A与人物B": "关系状态"}}
}}"""
        
        try:
            response = await self.llm.complete(
                [
                    {
                        "role": "system",
                        "content": "你是一位信息提取专家。请从文本中提取关键人物信息，只返回JSON格式。",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=600,
                temperature=0.1,
            )
            
            # 尝试解析JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass
        
        return {'characters': {}, 'events': [], 'relationships': {}}
    
    def get_previous_summaries(
        self,
        current_chapter: int,
        count: int = 3
    ) -> List[ChapterSummary]:
        """
        获取前几章的梗概
        
        Args:
            current_chapter: 当前章节号
            count: 获取前几章的梗概数量
        """
        summaries = []
        for i in range(max(1, current_chapter - count), current_chapter):
            if i in self.summary_cache:
                summaries.append(self.summary_cache[i])
        return summaries
    
    def build_continuity_context(
        self,
        current_chapter: int,
        max_summaries: int = 3
    ) -> str:
        """
        构建连续性上下文（用于注入提示词）
        
        Args:
            current_chapter: 当前章节号
            max_summaries: 最多包含前几章的梗概
        """
        summaries = self.get_previous_summaries(current_chapter, max_summaries)
        
        if not summaries:
            return ""
        
        parts = ["\n【前情提要 - 请务必保持人物信息一致】\n"]
        
        for summary in summaries:
            parts.append(summary.to_prompt_text())
            parts.append("\n" + "-" * 40 + "\n")
        
        parts.append("【人物一致性检查清单】\n")
        all_characters = {}
        for summary in summaries:
            all_characters.update(summary.key_characters)
        
        for name, info in all_characters.items():
            parts.append(f"  ✓ {name}: {info}")
        
        parts.append("\n【重要提醒】")
        parts.append("- 人物名字必须与上述一致")
        parts.append("- 人物关系必须与上述一致")
        parts.append("- 时间线必须连续")
        parts.append("- 如有新人物，需说明与已有人物的关系")
        
        return "\n".join(parts)


# 全局实例（按项目隔离，避免不同书串台）
_summary_generators: Dict[str, ChapterSummaryGenerator] = {}


def get_summary_generator(llm: Optional[LLMClient] = None, book_id: Optional[str] = None) -> ChapterSummaryGenerator:
    """获取全局梗概生成器实例"""
    global _summary_generators
    if not book_id:
        raise ValueError("获取章节梗概生成器时必须提供book_id")
    if book_id not in _summary_generators:
        if llm is None:
            raise ValueError("首次初始化需要提供LLMClient")
        _summary_generators[book_id] = ChapterSummaryGenerator(llm, book_id)
    return _summary_generators[book_id]
