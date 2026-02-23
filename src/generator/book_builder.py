"""书籍构建器 - 合并所有章节为完整传记"""
import json
import re
from pathlib import Path
from typing import List, Dict
from datetime import datetime


class BookBuilder:
    """书籍构建器"""
    
    def __init__(self, output_dir: str = "output/过河_陈国伟传"):
        self.output_dir = Path(output_dir)
        self.chapters_dir = self.output_dir
        
    def build_book(self, metadata: Dict, chapter_files: List[Path]) -> Path:
        """
        构建完整书籍
        
        Args:
            metadata: 书籍元数据
            chapter_files: 章节文件列表
            
        Returns:
            生成的书籍文件路径
        """
        print("\n[开始构建完整书籍]")
        
        # 读取所有章节
        chapters_content = []
        total_words = 0
        
        for ch_file in sorted(chapter_files):
            if ch_file.exists():
                content = ch_file.read_text(encoding='utf-8')
                chapters_content.append(content)
                word_count = self._count_chinese_words(content)
                total_words += word_count
                print(f"  读取: {ch_file.name} ({word_count:,}字)")
        
        # 构建完整内容
        book_content = self._assemble_book(metadata, chapters_content, total_words)
        
        # 保存文件
        output_file = self.output_dir / f"{metadata['title']}_完整版_{total_words}字.md"
        output_file.write_text(book_content, encoding='utf-8')
        
        # 生成统计报告
        self._generate_report(metadata, total_words, len(chapters_content))
        
        print(f"\n[完成] 书籍构建完成")
        print(f"  总字数: {total_words:,}字")
        print(f"  章节数: {len(chapters_content)}")
        print(f"  输出文件: {output_file}")
        
        return output_file
    
    def _assemble_book(self, metadata: Dict, chapters: List[str], total_words: int) -> str:
        """组装完整书籍"""
        parts = []
        
        # 封面
        parts.append(self._generate_cover(metadata))
        
        # 目录
        parts.append(self._generate_toc(metadata, len(chapters)))
        
        # 序言
        parts.append(self._generate_preface(metadata))
        
        # 正文
        for i, chapter in enumerate(chapters, 1):
            parts.append(f"\n\n<!-- 第{i}章开始 -->\n\n")
            parts.append(chapter)
            parts.append(f"\n\n<!-- 第{i}章结束 -->\n\n")
        
        # 后记
        parts.append(self._generate_epilogue(metadata))
        
        # 附录
        parts.append(self._generate_appendix(metadata, total_words))
        
        return "".join(parts)
    
    def _generate_cover(self, metadata: Dict) -> str:
        """生成封面"""
        return f"""# {metadata['title']}

**{metadata['subtitle']}**

---

*一部关于{metadata['subject']}的传记*

---

著者：AI传记写作系统  
基于采访文本创作  
创作时间：{datetime.now().strftime('%Y年%m月')}

---

"""
    
    def _generate_toc(self, metadata: Dict, chapter_count: int) -> str:
        """生成目录"""
        toc_lines = ["## 目录\n"]
        
        toc_lines.append("1. [序](#序)")
        for i in range(1, chapter_count + 1):
            toc_lines.append(f"{i+1}. [第{i}章](#第{i}章)")
        toc_lines.append(f"{chapter_count+2}. [后记](#后记)")
        
        toc_lines.append("\n---\n")
        return "\n".join(toc_lines)
    
    def _generate_preface(self, metadata: Dict) -> str:
        """生成序言"""
        return f"""## 序

这是一本关于普通人的传记。

{metadata['subject']}，{metadata.get('subject_desc', '一位平凡而又不凡的人物')}。{'他' if metadata.get('gender') == '男' else '她'}的一生，与这个国家的命运紧密相连。

本书基于深度采访写成，力求还原一个真实、立体、有血有肉的人物形象。

---

"""
    
    def _generate_epilogue(self, metadata: Dict) -> str:
        """生成后记"""
        return f"""

---

## 后记

{metadata.get('epilogue_content', '每个人都有自己的故事，每个故事都值得被记录。')}

---

**全书完**

---

"""
    
    def _generate_appendix(self, metadata: Dict, total_words: int) -> str:
        """生成附录"""
        return f"""## 附录：创作说明

- **书名**: {metadata['title']}
- **传主**: {metadata['subject']}
- **总字数**: {total_words:,}字
- **创作方式**: AI辅助生成
- **素材来源**: 采访文本

---

*本书由AI传记写作系统生成*

"""
    
    def _generate_report(self, metadata: Dict, total_words: int, chapter_count: int):
        """生成统计报告"""
        report = {
            "title": metadata['title'],
            "subject": metadata['subject'],
            "total_words": total_words,
            "chapter_count": chapter_count,
            "target_words": metadata.get('target_words', 100000),
            "completion_rate": f"{(total_words / metadata.get('target_words', 100000) * 100):.1f}%",
            "generation_time": datetime.now().isoformat()
        }
        
        report_file = self.output_dir / "generation_report.json"
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    
    def _count_chinese_words(self, text: str) -> int:
        """统计中文字符数"""
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        return len(chinese_chars)
