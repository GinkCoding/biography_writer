"""章节生成器 - 工程化生成单章内容"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict


@dataclass
class SectionSpec:
    """小节规格"""
    title: str
    target_words: int
    key_events: List[str]
    characters: List[str]
    setting: str
    emotional_tone: str


@dataclass
class ChapterSpec:
    """章节规格"""
    chapter_num: int
    title: str
    time_range: str
    summary: str
    target_words: int
    sections: List[SectionSpec]


class ChapterGenerator:
    """章节生成器"""
    
    def __init__(self, output_dir: str = "output/过河_陈国伟传"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = Path(".cache/chapters")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_chapter(self, spec: ChapterSpec, source_material: str) -> str:
        """
        生成单章内容
        
        策略：
        1. 将章节拆分为多个小节
        2. 逐个生成小节
        3. 合并并润色
        """
        chapter_file = self.output_dir / f"{spec.chapter_num:02d}_{spec.title}_详细版.md"
        
        # 检查缓存
        if chapter_file.exists():
            print(f"[缓存命中] {chapter_file.name}")
            return chapter_file.read_text(encoding='utf-8')
        
        print(f"\n[开始生成] 第{spec.chapter_num}章: {spec.title}")
        print(f"目标字数: {spec.target_words}")
        print(f"小节数: {len(spec.sections)}")
        
        # 生成每个小节
        sections_content = []
        total_words = 0
        
        for i, section in enumerate(spec.sections, 1):
            print(f"  生成小节 {i}/{len(spec.sections)}: {section.title}")
            
            section_content = self._generate_section(
                section=section,
                chapter_context=spec,
                section_index=i,
                source_material=source_material
            )
            
            sections_content.append(section_content)
            total_words += len(section_content)
            
            # 保存进度
            self._save_progress(spec.chapter_num, i, total_words)
        
        # 合并章节
        full_chapter = self._assemble_chapter(spec, sections_content)
        
        # 保存到文件
        chapter_file.write_text(full_chapter, encoding='utf-8')
        
        print(f"[完成] 第{spec.chapter_num}章生成完成，实际字数: {len(full_chapter)}")
        
        return full_chapter
    
    def _generate_section(self, section: SectionSpec, chapter_context: ChapterSpec,
                          section_index: int, source_material: str) -> str:
        """生成单个小节"""
        # 这里构建提示词，调用AI生成
        # 返回生成的内容
        
        prompt = self._build_section_prompt(section, chapter_context, source_material)
        
        # 模拟生成过程（实际使用时替换为真实AI调用）
        content = self._mock_generate(prompt, section.target_words)
        
        return content
    
    def _build_section_prompt(self, section: SectionSpec, chapter_context: ChapterSpec,
                              source_material: str) -> Dict:
        """构建生成提示词"""
        return {
            "system": "你是一位专业的传记作家，擅长将采访素材扩写为细腻的文学性传记。",
            "context": {
                "chapter_title": chapter_context.title,
                "chapter_summary": chapter_context.summary,
                "time_range": chapter_context.time_range,
                "section_title": section.title,
                "section_index": "",
                "target_words": section.target_words,
                "key_events": section.key_events,
                "characters": section.characters,
                "setting": section.setting,
                "emotional_tone": section.emotional_tone
            },
            "source_material": source_material[:2000],  # 截取相关素材
            "requirements": [
                "使用文学性的语言，注重场景描写",
                "包含人物对话和心理活动",
                "融入时代背景和社会环境",
                "保持时间线和事实的准确性",
                f"目标字数：{section.target_words}字"
            ]
        }
    
    def _mock_generate(self, prompt: Dict, target_words: int) -> str:
        """
        模拟生成内容
        实际使用时，这里应该调用AI API
        """
        # 这里返回一个占位符，实际使用时替换为真实生成
        section_title = prompt["context"]["section_title"]
        return f"\n\n## {section_title}\n\n[此处为{target_words}字的详细内容]\n\n"
    
    def _assemble_chapter(self, spec: ChapterSpec, sections: List[str]) -> str:
        """组装完整章节"""
        parts = [
            f"# {spec.title}\n",
            f"\n*{spec.time_range}*\n",
            f"\n{spec.summary}\n",
            "\n---\n"
        ]
        
        for section_content in sections:
            parts.append(section_content)
        
        parts.append("\n---\n\n*本章完*\n")
        
        return "".join(parts)
    
    def _save_progress(self, chapter_num: int, section_index: int, total_words: int):
        """保存生成进度"""
        progress_file = self.cache_dir / f"ch{chapter_num}_progress.json"
        progress = {
            "chapter": chapter_num,
            "completed_sections": section_index,
            "total_words": total_words,
            "status": "in_progress" if section_index < 4 else "completed"
        }
        progress_file.write_text(json.dumps(progress, ensure_ascii=False), encoding='utf-8')
    
    def load_progress(self, chapter_num: int) -> Optional[Dict]:
        """加载生成进度"""
        progress_file = self.cache_dir / f"ch{chapter_num}_progress.json"
        if progress_file.exists():
            return json.loads(progress_file.read_text(encoding='utf-8'))
        return None
