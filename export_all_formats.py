#!/usr/bin/env python3
"""Export final book from reviewed chapters in all formats"""
import json
import os
import re
from pathlib import Path
from datetime import datetime
from ebooklib import epub

# Paths
base_path = Path("/Users/guoquan/work/Kimi/biography_writer/.observability/runs/bade1b72b4fc16cd_20260303_001855/artifacts/05_review")
output_dir = Path("/Users/guoquan/work/Kimi/biography_writer/output/bade1b72b4fc16cd")
output_dir.mkdir(exist_ok=True)

def clean_text(text):
    """Remove annotations"""
    if not text:
        return ""
    # Remove source markers
    text = re.sub(r'（来源：素材\d+）', '', text)
    text = re.sub(r'（注：.*?）', '', text)
    text = re.sub(r'，其余细节尚无直接证据[。.]?', '', text)
    text = re.sub(r'采访素材[^\n]*', '', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()

# Load all chapters
chapters = []
for i in range(1, 26):
    chapter_file = base_path / f"chapter_{i:02d}_reviewed.json"
    if chapter_file.exists():
        with open(chapter_file, 'r', encoding='utf-8') as f:
            chapter_data = json.load(f)
            title = chapter_data.get('outline', {}).get('title', f'第{i}章')
            chapters.append({
                'number': i,
                'title': title,
                'data': chapter_data
            })
            print(f"✅ Loaded chapter {i}: {title}")

total_words = sum(
    sum(s.get('word_count', 0) for s in ch['data'].get('sections', []))
    for ch in chapters
)

print(f"\n📊 Total: {len(chapters)} chapters, {total_words:,} words")

# 1. Export TXT
print("\n📄 Generating TXT...")
txt_path = output_dir / "陈国伟传.txt"
with open(txt_path, 'w', encoding='utf-8') as f:
    f.write("=" * 60 + "\n")
    f.write("                    陈国伟传\n")
    f.write("=" * 60 + "\n\n")
    f.write("副标题：一个 1982-1984: 藤编厂工人的重孝道\n")
    f.write("          （为父母名声放弃偷渡）的真实人生\n\n")
    f.write(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    f.write(f"总字数：{total_words:,}字\n")
    f.write(f"总章节：{len(chapters)}章\n\n")
    f.write("AI 传记写作系统 出品\n")
    f.write("=" * 60 + "\n\n\n")
    
    # TOC
    f.write("目  录\n" + "-" * 60 + "\n")
    for ch in chapters:
        f.write(f"第{ch['number']}章  {ch['title']}\n")
    f.write("\n\n")
    
    # Content
    for ch in chapters:
        f.write("=" * 60 + "\n")
        f.write(f"第{ch['number']}章  {ch['title']}\n")
        f.write("=" * 60 + "\n\n")
        
        for section in ch['data'].get('sections', []):
            if section.get('title'):
                f.write(f"\n【{section['title']}】\n\n")
            
            content = section.get('content', '')
            if content:
                cleaned = clean_text(content)
                if cleaned:
                    f.write(cleaned + "\n\n")
        
        f.write("\n\n")
    
    f.write("=" * 60 + "\n全书完\n" + "=" * 60 + "\n")

print(f"✅ TXT saved: {txt_path} ({txt_path.stat().st_size / 1024:.1f} KB)")

# 2. Export Markdown
print("\n📝 Generating Markdown...")
md_path = output_dir / "陈国伟传.md"
with open(md_path, 'w', encoding='utf-8') as f:
    f.write("# 陈国伟传\n\n")
    f.write("## 副标题：一个 1982-1984: 藤编厂工人的重孝道（为父母名声放弃偷渡）的真实人生\n\n")
    f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}  \n")
    f.write(f"**总字数**: {total_words:,}字  \n")
    f.write(f"**总章节**: {len(chapters)}章\n\n")
    f.write("---\n\n")
    
    # TOC
    f.write("## 目录\n\n")
    for ch in chapters:
        f.write(f"- 第{ch['number']}章 {ch['title']}\n")
    f.write("\n---\n\n")
    
    # Content
    for ch in chapters:
        f.write(f"## 第{ch['number']}章 {ch['title']}\n\n")
        
        for section in ch['data'].get('sections', []):
            if section.get('title'):
                f.write(f"### {section['title']}\n\n")
            
            content = section.get('content', '')
            if content:
                cleaned = clean_text(content)
                if cleaned:
                    # Format paragraphs
                    paras = re.split(r'\n\n+', cleaned)
                    for p in paras:
                        if p.strip():
                            f.write(p.strip() + "\n\n")
        
        f.write("---\n\n")
    
    f.write("**全书完**\n")

print(f"✅ Markdown saved: {md_path} ({md_path.stat().st_size / 1024:.1f} KB)")

# 3. Export EPUB
print("\n📚 Generating EPUB...")
epub_path = output_dir / "陈国伟传.epub"
book = epub.EpubBook()
book.set_identifier('chen-guowei-biography-2026')
book.set_title('陈国伟传')
book.set_language('zh')
book.add_author('AI 传记写作系统')

# CSS
style = '''
body { font-family: "PingFang SC", "Microsoft YaHei", sans-serif; line-height: 1.8; margin: 5%; }
h1 { text-align: center; margin: 2em 0; font-size: 1.8em; }
h2 { text-align: center; margin: 1.5em 0 1em; font-size: 1.4em; }
p { text-indent: 2em; margin: 0.8em 0; }
.chapter { margin: 2em 0; }
'''
css = epub.EpubItem(uid="style", file_name="style/main.css", media_type="text/css", content=style)
book.add_item(css)

# Chapters
epub_chapters = []
for ch in chapters:
    content = f'<h1>第{ch["number"]}章 {ch["title"]}</h1>\n'
    
    for section in ch['data'].get('sections', []):
        if section.get('title'):
            content += f'<h2>{section["title"]}</h2>\n'
        
        sec_content = section.get('content', '')
        if sec_content:
            cleaned = clean_text(sec_content)
            if cleaned:
                for p in re.split(r'\n\n+', cleaned):
                    if p.strip():
                        content += f'<p>{p.strip()}</p>\n'
    
    epub_ch = epub.EpubHtml(title=ch['title'], file_name=f'chapter_{ch["number"]:02d}.xhtml', lang='zh')
    epub_ch.content = content
    epub_ch.add_item(css)
    epub_chapters.append(epub_ch)
    book.add_item(epub_ch)

book.add_item(epub.EpubNcx())
book.add_item(epub.EpubNav())
book.spine = ['nav'] + epub_chapters
epub.write_epub(epub_path, book, {})

print(f"✅ EPUB saved: {epub_path} ({epub_path.stat().st_size / 1024:.1f} KB)")

# 4. Export JSON (metadata + chapter list)
print("\n📋 Generating JSON...")
json_path = output_dir / "陈国伟传_metadata.json"
metadata = {
    "title": "陈国伟传",
    "subtitle": "一个 1982-1984: 藤编厂工人的重孝道（为父母名声放弃偷渡）的真实人生",
    "generated_at": datetime.now().isoformat(),
    "total_chapters": len(chapters),
    "total_words": total_words,
    "chapters": [
        {
            "number": ch['number'],
            "title": ch['title'],
            "word_count": sum(s.get('word_count', 0) for s in ch['data'].get('sections', []))
        }
        for ch in chapters
    ]
}
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(metadata, f, ensure_ascii=False, indent=2)

print(f"✅ JSON saved: {json_path}")

print("\n" + "=" * 60)
print("✅ 所有格式导出完成！")
print("=" * 60)
print(f"\n输出目录：{output_dir}")
print("\n生成的文件:")
for f in output_dir.glob("陈国伟传.*"):
    print(f"  • {f.name} ({f.stat().st_size / 1024:.1f} KB)")
