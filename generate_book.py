#!/usr/bin/env python3
"""
传记生成主脚本 - 工程化生成十万字传记

使用方法:
    python3 generate_book.py [--chapter N] [--resume]

选项:
    --chapter N    只生成第N章
    --resume       从断点继续生成
"""
import sys
import argparse
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent))

from src.generator.chapter_generator import ChapterGenerator
from src.generator.book_builder import BookBuilder
from src.generator.specs import get_chapter_specs, get_book_metadata


def main():
    parser = argparse.ArgumentParser(description='生成传记')
    parser.add_argument('--chapter', type=int, help='只生成指定章节')
    parser.add_argument('--resume', action='store_true', help='从断点继续')
    parser.add_argument('--assemble-only', action='store_true', help='只合并已有章节')
    args = parser.parse_args()
    
    # 初始化
    output_dir = "output/过河_陈国伟传"
    generator = ChapterGenerator(output_dir)
    builder = BookBuilder(output_dir)
    metadata = get_book_metadata()
    
    print("=" * 60)
    print("《过河：陈国伟传》生成系统")
    print("=" * 60)
    print(f"目标字数: {metadata['target_words']:,}字")
    print(f"预计章节: 5章")
    print()
    
    if args.assemble_only:
        # 只合并已有章节
        chapter_files = list(Path(output_dir).glob("*_详细版.md"))
        builder.build_book(metadata, chapter_files)
        return
    
    # 获取章节规格
    chapter_specs = get_chapter_specs()
    
    # 读取采访素材
    source_file = Path("interviews/陈国伟采访.txt")
    if source_file.exists():
        source_material = source_file.read_text(encoding='utf-8')
        print(f"已加载素材: {source_file.name} ({len(source_material):,}字符)")
    else:
        print(f"警告: 未找到素材文件 {source_file}")
        source_material = ""
    
    print()
    
    # 生成章节
    generated_chapters = []
    
    for spec in chapter_specs:
        # 如果指定了章节号，跳过其他章节
        if args.chapter and spec.chapter_num != args.chapter:
            continue
        
        # 检查是否需要生成
        if args.resume:
            progress = generator.load_progress(spec.chapter_num)
            if progress and progress.get("status") == "completed":
                print(f"[跳过] 第{spec.chapter_num}章已完成")
                chapter_file = Path(output_dir) / f"{spec.chapter_num:02d}_{spec.title}_详细版.md"
                if chapter_file.exists():
                    generated_chapters.append(chapter_file)
                continue
        
        # 生成章节
        try:
            chapter_content = generator.generate_chapter(spec, source_material)
            chapter_file = Path(output_dir) / f"{spec.chapter_num:02d}_{spec.title}_详细版.md"
            generated_chapters.append(chapter_file)
        except Exception as e:
            print(f"[错误] 生成第{spec.chapter_num}章时出错: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print()
    print("=" * 60)
    
    # 合并书籍
    if generated_chapters:
        print("[开始合并书籍]")
        
        # 收集所有章节文件
        all_chapters = []
        for i in range(1, 6):
            # 优先使用详细版
            detailed = Path(output_dir) / f"{i:02d}_*_详细版.md"
            standard = Path(output_dir) / f"{i:02d}_*_*.md"
            
            found = False
            for f in Path(output_dir).glob(f"{i:02d}_*_详细版.md"):
                all_chapters.append(f)
                found = True
                break
            
            if not found:
                for f in Path(output_dir).glob(f"{i:02d}_第一章_*.md"):
                    all_chapters.append(f)
                    found = True
                    break
                for f in Path(output_dir).glob(f"{i:02d}_第二章_*.md"):
                    all_chapters.append(f)
                    found = True
                    break
                for f in Path(output_dir).glob(f"{i:02d}_第三章_*.md"):
                    all_chapters.append(f)
                    found = True
                    break
                for f in Path(output_dir).glob(f"{i:02d}_第四章_*.md"):
                    all_chapters.append(f)
                    found = True
                    break
                for f in Path(output_dir).glob(f"{i:02d}_第五章_*.md"):
                    all_chapters.append(f)
                    found = True
                    break
        
        # 去重并保持顺序
        seen = set()
        unique_chapters = []
        for f in all_chapters:
            if f.name not in seen:
                seen.add(f.name)
                unique_chapters.append(f)
        
        if unique_chapters:
            output_file = builder.build_book(metadata, unique_chapters)
            print(f"\n[成功] 书籍已生成: {output_file}")
        else:
            print("[警告] 未找到可合并的章节文件")
    else:
        print("[警告] 没有新生成的章节")
    
    print("=" * 60)


if __name__ == "__main__":
    main()
