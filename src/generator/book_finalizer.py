"""书籍终版选择器与输出合并器

功能：
1. 从多个版本中选择最佳内容
2. 合并章节生成完整书籍
3. 输出为多种格式（Markdown, TXT, EPUB）
"""
import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from loguru import logger

from src.models import BiographyBook, GeneratedChapter, GeneratedSection, BookOutline
from src.utils import count_chinese_words, sanitize_filename


@dataclass
class ChapterVersion:
    """章节版本信息"""
    chapter_order: int
    chapter_title: str
    content: str
    word_count: int
    generation_time: datetime
    quality_score: float = 0.0  # 质量评分
    issues: List[str] = field(default_factory=list)
    is_verified: bool = False


@dataclass
class VersionSelectorResult:
    """版本选择结果"""
    selected_chapters: List[ChapterVersion]
    total_word_count: int
    quality_summary: Dict[str, any]


class ChapterVersionSelector:
    """章节版本选择器 - 从多个版本中选择最佳内容"""

    def __init__(self):
        self.version_history: Dict[int, List[ChapterVersion]] = {}

    def add_version(self, version: ChapterVersion):
        """添加一个章节版本到历史记录"""
        if version.chapter_order not in self.version_history:
            self.version_history[version.chapter_order] = []
        self.version_history[version.chapter_order].append(version)

    def select_best_versions(self) -> VersionSelectorResult:
        """
        从所有历史版本中选择最佳章节组合

        选择策略：
        1. 优先选择 facts_verified=True 的版本
        2. 质量评分高的优先
        3. 问题少的优先
        4. 字数接近目标字数的优先
        """
        selected = []
        quality_summary = {
            'total_chapters': len(self.version_history),
            'verified_count': 0,
            'total_issues': 0,
            'selection_reasons': []
        }

        for chapter_order, versions in sorted(self.version_history.items()):
            if not versions:
                continue

            # 计算每个版本的综合评分
            scored_versions = []
            for v in versions:
                # 基础分：质量评分
                score = v.quality_score

                # 验证加分
                if v.is_verified:
                    score += 2.0
                    quality_summary['verified_count'] += 1

                # 问题扣分
                score -= len(v.issues) * 0.3
                quality_summary['total_issues'] += len(v.issues)

                scored_versions.append((score, v))

            # 选择最高分版本
            scored_versions.sort(key=lambda x: x[0], reverse=True)
            best_score, best_version = scored_versions[0]

            # 记录选择原因
            reason = f"第{best_version.chapter_order}章《{best_version.chapter_title}》: "
            if best_version.is_verified:
                reason += "已通过事实核查"
            else:
                reason += f"质量评分{best_version.quality_score:.1f}"
            if best_version.issues:
                reason += f", 有{len(best_version.issues)}个问题"

            quality_summary['selection_reasons'].append(reason)

            selected.append(best_version)

        # 按章节顺序排序
        selected.sort(key=lambda x: x.chapter_order)

        total_words = sum(v.word_count for v in selected)

        return VersionSelectorResult(
            selected_chapters=selected,
            total_word_count=total_words,
            quality_summary=quality_summary
        )

    def get_version_history_report(self) -> str:
        """生成版本历史报告"""
        lines = ["# 版本选择报告\n"]

        for chapter_order, versions in sorted(self.version_history.items()):
            lines.append(f"\n## 第{chapter_order}章\n")
            lines.append(f"共生成 {len(versions)} 个版本\n")

            for i, v in enumerate(versions, 1):
                verified_mark = "✓" if v.is_verified else "✗"
                lines.append(f"{i}. [{verified_mark}] {v.generation_time.strftime('%H:%M:%S')} "
                           f"- {v.word_count}字 "
                           f"- 评分{v.quality_score:.1f} "
                           f"- {len(v.issues)}个问题")

        return '\n'.join(lines)


class BookFinalizer:
    """书籍终版生成器"""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.version_selector = ChapterVersionSelector()

    def add_chapter_version(
        self,
        chapter: GeneratedChapter,
        quality_score: float = 0.0
    ):
        """添加一个章节版本到选择池"""
        # 合并章节所有小节的内容
        full_content = chapter.full_content

        # 统计问题
        all_issues = []
        for section in chapter.sections:
            all_issues.extend(section.issues)

        # 检查是否所有小节都通过了事实核查
        all_verified = all(s.facts_verified for s in chapter.sections)

        version = ChapterVersion(
            chapter_order=chapter.outline.order,
            chapter_title=chapter.outline.title,
            content=full_content,
            word_count=chapter.word_count,
            generation_time=datetime.now(),
            quality_score=quality_score,
            issues=list(set(all_issues)),  # 去重
            is_verified=all_verified
        )

        self.version_selector.add_version(version)
        logger.info(f"添加第{chapter.outline.order}章版本: {chapter.word_count}字, "
                   f"评分{quality_score:.1f}")

    def finalize_book(
        self,
        outline: BookOutline,
        book_id: str
    ) -> BiographyBook:
        """
        生成终版书籍

        Returns:
            终版 BiographyBook 对象
        """
        logger.info("开始生成终版书籍...")

        # 选择最佳版本
        result = self.version_selector.select_best_versions()

        logger.info(f"版本选择完成: {len(result.selected_chapters)}章, "
                   f"{result.total_word_count}字")
        logger.info(f"其中 {result.quality_summary['verified_count']} 章通过事实核查")

        if result.quality_summary['total_issues'] > 0:
            logger.warning(f"终版共有 {result.quality_summary['total_issues']} 个待处理问题")

        # 构建章节对象
        final_chapters = []
        for version in result.selected_chapters:
            # 查找对应的大纲章节
            chapter_outline = None
            for c in outline.chapters:
                if c.order == version.chapter_order:
                    chapter_outline = c
                    break

            if not chapter_outline:
                logger.warning(f"找不到第{version.chapter_order}章的大纲信息")
                continue

            # 重建章节对象
            # 注意：这里简化处理，直接使用字符串内容
            chapter = self._rebuild_chapter_from_content(
                version, chapter_outline
            )
            final_chapters.append(chapter)

        # 按章节顺序排序
        final_chapters.sort(key=lambda c: c.outline.order)

        # 创建终版书籍
        final_book = BiographyBook(
            id=f"{book_id}_final",
            outline=outline,
            chapters=final_chapters,
            completed_at=datetime.now()
        )

        # 保存版本选择报告
        self._save_version_report(book_id)

        return final_book

    def _rebuild_chapter_from_content(
        self,
        version: ChapterVersion,
        outline: ChapterOutline
    ) -> GeneratedChapter:
        """从版本内容重建章节对象"""
        from src.models import GeneratedSection

        # 创建单个包含全部内容的 section
        # 实际使用时可能需要更复杂的分割逻辑
        main_section = GeneratedSection(
            id=f"section_{outline.order}_final",
            chapter_id=f"chapter_{outline.order}",
            title=version.chapter_title,
            content=version.content,
            word_count=version.word_count,
            generation_time=version.generation_time,
            facts_verified=version.is_verified,
            issues=version.issues
        )

        return GeneratedChapter(
            id=f"chapter_{outline.order}_final",
            outline=outline,
            sections=[main_section],
            transition_paragraph=None
        )

    def _save_version_report(self, book_id: str):
        """保存版本选择报告"""
        report = self.version_selector.get_version_history_report()
        report_path = self.output_dir / f"{book_id}_version_report.md"
        report_path.write_text(report, encoding='utf-8')
        logger.info(f"版本报告已保存: {report_path}")

    def export_to_txt(self, book: BiographyBook) -> Path:
        """导出为纯文本格式"""
        output_path = self.output_dir / f"{sanitize_filename(book.id)}.txt"

        lines = []

        # 标题
        lines.append(book.outline.title)
        if book.outline.subtitle:
            lines.append(book.outline.subtitle)
        lines.append(f"\n{book.outline.subject_name}传")
        lines.append("=" * 40)

        # 序言
        if book.outline.prologue:
            lines.append("\n【序】\n")
            lines.append(book.outline.prologue)
            lines.append("\n")

        # 正文
        for chapter in book.chapters:
            lines.append(f"\n\n{'=' * 40}")
            lines.append(f"\n{chapter.outline.title}\n")
            lines.append("=" * 40)

            if chapter.outline.summary:
                lines.append(f"\n{chapter.outline.summary}\n")

            for section in chapter.sections:
                lines.append(f"\n{section.title}\n")
                lines.append(section.content)

            if chapter.transition_paragraph:
                lines.append(f"\n{chapter.transition_paragraph}")

        # 后记
        if book.outline.epilogue:
            lines.append("\n\n" + "=" * 40)
            lines.append("\n【后记】\n")
            lines.append(book.outline.epilogue)

        # 统计信息
        lines.append("\n\n" + "=" * 40)
        lines.append("\n【书籍信息】")
        lines.append(f"总章节: {len(book.chapters)}")
        lines.append(f"总字数: {book.total_word_count}")
        lines.append(f"生成时间: {book.completed_at.strftime('%Y-%m-%d %H:%M')}")

        output_path.write_text('\n'.join(lines), encoding='utf-8')
        logger.info(f"TXT 导出完成: {output_path}")

        return output_path

    def export_to_markdown(self, book: BiographyBook) -> Path:
        """导出为 Markdown 格式"""
        output_path = self.output_dir / f"{sanitize_filename(book.id)}.md"

        lines = []

        # 标题
        lines.append(f"# {book.outline.title}")
        if book.outline.subtitle:
            lines.append(f"\n**{book.outline.subtitle}**")
        lines.append(f"\n*{book.outline.subject_name}传*")
        lines.append("\n---\n")

        # 序言
        if book.outline.prologue:
            lines.append("## 序\n")
            lines.append(book.outline.prologue)
            lines.append("\n---\n")

        # 正文
        for chapter in book.chapters:
            lines.append(f"\n# {chapter.outline.title}\n")

            if chapter.outline.summary:
                lines.append(f"> {chapter.outline.summary}\n")

            for section in chapter.sections:
                lines.append(f"## {section.title}\n")
                lines.append(section.content)
                lines.append("\n")

            if chapter.transition_paragraph:
                lines.append(f"\n*{chapter.transition_paragraph}*\n")

        # 后记
        if book.outline.epilogue:
            lines.append("\n---\n")
            lines.append("## 后记\n")
            lines.append(book.outline.epilogue)

        output_path.write_text('\n'.join(lines), encoding='utf-8')
        logger.info(f"Markdown 导出完成: {output_path}")

        return output_path

    def export_to_json(self, book: BiographyBook) -> Path:
        """导出为 JSON 格式（包含完整结构化数据）"""
        output_path = self.output_dir / f"{sanitize_filename(book.id)}.json"

        data = {
            "id": book.id,
            "title": book.outline.title,
            "subtitle": book.outline.subtitle,
            "subject": book.outline.subject_name,
            "metadata": {
                "total_chapters": len(book.chapters),
                "total_words": book.total_word_count,
                "created_at": book.created_at.isoformat(),
                "completed_at": book.completed_at.isoformat() if book.completed_at else None
            },
            "chapters": []
        }

        for chapter in book.chapters:
            chapter_data = {
                "order": chapter.outline.order,
                "title": chapter.outline.title,
                "summary": chapter.outline.summary,
                "time_period": {
                    "start": chapter.outline.time_period_start,
                    "end": chapter.outline.time_period_end
                },
                "word_count": chapter.word_count,
                "sections": []
            }

            for section in chapter.sections:
                chapter_data["sections"].append({
                    "id": section.id,
                    "title": section.title,
                    "content": section.content,
                    "word_count": section.word_count,
                    "verified": section.facts_verified,
                    "issues": section.issues
                })

            data["chapters"].append(chapter_data)

        output_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        logger.info(f"JSON 导出完成: {output_path}")

        return output_path

    def export_to_epub(self, book: BiographyBook, cover_image: Optional[Path] = None) -> Path:
        """导出为 EPUB 格式"""
        try:
            from src.generator.epub_exporter import export_to_epub

            output_path = self.output_dir / f"{sanitize_filename(book.id)}.epub"
            return export_to_epub(book, output_path, cover_image)

        except ImportError:
            logger.error("EPUB 导出失败: 未安装 ebooklib")
            raise

    def export_all_formats(
        self,
        book: BiographyBook,
        cover_image: Optional[Path] = None
    ) -> Dict[str, Path]:
        """
        导出所有可用格式

        Returns:
            格式到路径的映射字典
        """
        results = {}

        # TXT
        try:
            results['txt'] = self.export_to_txt(book)
        except Exception as e:
            logger.error(f"TXT 导出失败: {e}")

        # Markdown
        try:
            results['md'] = self.export_to_markdown(book)
        except Exception as e:
            logger.error(f"Markdown 导出失败: {e}")

        # JSON
        try:
            results['json'] = self.export_to_json(book)
        except Exception as e:
            logger.error(f"JSON 导出失败: {e}")

        # EPUB
        try:
            results['epub'] = self.export_to_epub(book, cover_image)
        except Exception as e:
            logger.error(f"EPUB 导出失败: {e}")

        return results


def finalize_and_export(
    chapters: List[GeneratedChapter],
    outline: BookOutline,
    book_id: str,
    output_dir: Path,
    cover_image: Optional[Path] = None
) -> Dict[str, Path]:
    """
    一站式终版生成和导出

    Args:
        chapters: 所有章节列表
        outline: 书籍大纲
        book_id: 书籍ID
        output_dir: 输出目录
        cover_image: 封面图片路径（可选）

    Returns:
        导出的文件路径字典
    """
    finalizer = BookFinalizer(output_dir)

    # 添加所有章节版本
    for chapter in chapters:
        # 计算质量评分（简单规则：字数比例 + 验证状态）
        target_words = chapter.outline.target_words
        word_ratio = min(chapter.word_count / max(target_words, 1), 1.0)
        verified_bonus = 1.0 if all(s.facts_verified for s in chapter.sections) else 0.0
        quality_score = word_ratio * 5 + verified_bonus * 5

        finalizer.add_chapter_version(chapter, quality_score)

    # 生成终版
    final_book = finalizer.finalize_book(outline, book_id)

    # 导出所有格式
    return finalizer.export_all_formats(final_book, cover_image)
