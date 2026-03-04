#!/usr/bin/env python3
"""Export truly clean final book"""
import json
import re
from pathlib import Path
from datetime import datetime
from ebooklib import epub

base_path = Path("/Users/guoquan/work/Kimi/biography_writer/.observability/runs/bade1b72b4fc16cd_20260303_001855/artifacts/05_review")
output_dir = Path("/Users/guoquan/.openclaw/workspace")

def clean_text(text):
    """Aggressively clean all annotations"""
    if not text:
        return ""
    
    # Remove ALL annotation patterns
    text = re.sub(r'采访素材[^\n]*', '\n', text)
    text = re.sub(r'（来源：素材\d+）', '', text)
    text = re.sub(r'（注：.*?）', '', text)
    text = re.sub(r'，其余细节尚无直接证据[。.]?', '', text)
    text = re.sub(r'其余细节尚无直接证据', '', text)
    text = re.sub(r'\(采访开始.*?\)', '', text)
    text = re.sub(r'\s+', ' ', text)
    
    # Split by sentences and filter
    sentences = re.split(r'([.!?.!?])', text)
    clean_sentences = []
    for s in sentences:
        s = s.strip()
        if s and len(re.findall(r'[\u4e00-\u9fff]', s)) >= 3:
            # Skip if mostly annotations
            if not re.search(r'^(采访 | 证据 | 素材|其余细节)', s):
                clean_sentences.append(s)
    
    # Join sentences
    result = ''.join(clean_sentences)
    result = re.sub(r' +', '', result)
    result = re.sub(r'([.!?.!?])', r'\1\n\n', result)
    
    return result.strip()

# Load chapters
chapters = []
for i in range(1, 26):
    chapter_file = base_path / f"chapter_{i:02d}_reviewed.json"
    if chapter_file.exists():
        with open(chapter_file, 'r', encoding='utf-8') as f:
            chapter_data = json.load(f)
            title = chapter_data.get('outline', {}).get('title', f'第{i}章')
            chapters.append({'number': i, 'title': title, 'data': chapter_data})

total_words = sum(sum(s.get('word_count', 0) for s in ch['data'].get('sections', [])) for ch in chapters)

print(f"📊 Total: {len(chapters)} chapters, {total_words:,} words")

# Export TXT
txt_path = output_dir / "陈国伟传_干净版.txt"
with open(txt_path, 'w', encoding='utf-8') as f:
    f.write("="*60 + "\n陈国伟传\n" + "="*60 + "\n\n")
    f.write("副标题：一个 1982-1984: 藤编厂工人的重孝道\n")
    f.write("（为父母名声放弃偷渡）的真实人生\n\n")
    f.write(f"总字数：{total_words:,}字 | 总章节：25 章\n\n")
    f.write("="*60 + "\n\n")
    
    word_count = 0
    for ch in chapters:
        f.write(f"\n{'='*60}\n")
        f.write(f"第{ch['number']}章 {ch['title']}\n")
        f.write(f"{'='*60}\n\n")
        
        for section in ch['data'].get('sections', []):
            if section.get('title'):
                f.write(f"【{section['title']}】\n\n")
            
            content = section.get('content', '')
            if content:
                cleaned = clean_text(content)
                if cleaned:
                    f.write(cleaned + "\n\n")
                    word_count += len(cleaned) // 2
    
    f.write("\n" + "="*60 + "\n全书完\n" + "="*60 + "\n")

print(f"✅ TXT: {txt_path.name} ({txt_path.stat().st_size / 1024:.1f} KB, ~{word_count:,}字)")

# Export EPUB
epub_path = output_dir / "陈国伟传_干净版.epub"
book = epub.EpubBook()
book.set_identifier('chen-guowei-2026')
book.set_title('陈国伟传')
book.set_language('zh')
book.add_author('AI 传记写作系统')

css = epub.EpubItem(uid="style", file_name="style/main.css", media_type="text/css", 
    content='body{font-family:"PingFang SC",sans-serif;line-height:1.8;margin:5%}h1{text-align:center}h2{text-align:center;color:#555}p{text-indent:2em}')
book.add_item(css)

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
                for p in cleaned.split('\n\n'):
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

print(f"✅ EPUB: {epub_path.name} ({epub_path.stat().st_size / 1024:.1f} KB)")
print("\n✅ 干净版导出完成！")
