#!/usr/bin/env python3
"""
示例：使用版本选择和EPUB导出功能

本示例演示如何：
1. 生成传记并收集多个章节版本
2. 使用版本选择器选择最佳章节
3. 导出为多种格式（TXT, Markdown, JSON, EPUB）
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.engine import BiographyEngine
from src.models import WritingStyle


async def main():
    """主流程示例"""
    engine = BiographyEngine()

    # 1. 初始化项目
    interview_file = Path("interviews/sample_interview.txt")
    if not interview_file.exists():
        print(f"示例文件不存在: {interview_file}")
        print("请准备采访文件后运行此示例")
        return

    print("=" * 60)
    print("传记生成与导出示例")
    print("=" * 60)

    book_id = await engine.initialize_from_interview(
        interview_file=interview_file,
        subject_hint="传主姓名",
        style=WritingStyle.LITERARY,
        target_words=100000
    )
    print(f"\n项目初始化完成: {book_id}")

    # 2. 生成传记
    print("\n开始生成传记...")
    book = await engine.generate_book(
        progress_callback=lambda msg: print(f"  {msg}")
    )

    print(f"\n生成完成!")
    print(f"  - 总章节: {len(book.chapters)}")
    print(f"  - 总字数: {book.total_word_count}")

    # 3. 查看版本选择报告
    print("\n" + "=" * 60)
    print("版本选择报告")
    print("=" * 60)
    version_report = engine.get_version_report()
    print(version_report)

    # 4. 导出为多种格式
    print("\n" + "=" * 60)
    print("导出书籍")
    print("=" * 60)

    # 准备封面图片（可选）
    cover_image = Path("assets/cover.jpg") if Path("assets/cover.jpg").exists() else None

    # 导出所有格式
    exported_files = await engine.save_book(
        book=book,
        formats=["txt", "md", "json", "epub"],
        cover_image=cover_image,
        use_version_selection=True  # 启用版本选择
    )

    print("\n导出完成:")
    for format_name, file_path in exported_files.items():
        if format_name != "chapters_dir":
            print(f"  [{format_name}] {file_path}")

    # 5. EPUB 特别说明
    if "epub" in exported_files:
        print("\n" + "=" * 60)
        print("EPUB 文件信息")
        print("=" * 60)
        epub_path = exported_files["epub"]
        print(f"文件路径: {epub_path}")
        print(f"文件大小: {epub_path.stat().st_size / 1024:.1f} KB")
        print("\n兼容性说明:")
        print("  - 支持 iBooks (Apple)")
        print("  - 支持 微信读书")
        print("  - 支持 多看阅读")
        print("  - 支持 Kindle (需通过 Calibre 转换)")
        print("  - 符合 EPUB 3.0 标准")

    print("\n" + "=" * 60)
    print("所有任务完成!")
    print("=" * 60)


async def demo_version_selection():
    """
    演示版本选择功能（无需完整生成）
    """
    from src.generator import BookFinalizer, finalize_and_export
    from src.models import BiographyBook, BookOutline, GeneratedChapter, GeneratedSection, ChapterOutline
    from datetime import datetime

    print("=" * 60)
    print("版本选择功能演示")
    print("=" * 60)

    # 创建示例大纲
    outline = BookOutline(
        title="示例传记",
        subject_name="张三",
        style="literary",
        target_total_words=10000,
        chapters=[
            ChapterOutline(
                order=i,
                title=f"第{i}章",
                summary=f"第{i}章摘要",
                target_words=3000
            )
            for i in range(1, 4)
        ]
    )

    # 创建示例章节（模拟多个版本）
    chapters = []
    for i in range(1, 4):
        chapter = GeneratedChapter(
            id=f"chapter_{i}",
            outline=outline.chapters[i-1],
            sections=[
                GeneratedSection(
                    id=f"section_{i}_1",
                    chapter_id=f"chapter_{i}",
                    title=f"第{i}章第1节",
                    content=f"这是第{i}章的内容示例。" * 100,
                    word_count=800,
                    facts_verified=True,
                    issues=[]
                )
            ]
        )
        chapters.append(chapter)

    # 使用一站式导出函数
    output_dir = Path("output/demo")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\n导出中...")
    results = finalize_and_export(
        chapters=chapters,
        outline=outline,
        book_id="demo_book",
        output_dir=output_dir
    )

    print("\n导出完成:")
    for format_name, file_path in results.items():
        print(f"  [{format_name}] {file_path}")

    print("\n演示完成!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="传记生成与导出示例")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="仅运行版本选择演示（无需采访文件）"
    )

    args = parser.parse_args()

    if args.demo:
        asyncio.run(demo_version_selection())
    else:
        asyncio.run(main())
