"""EPUB 导出器 - 生成格式正确、兼容性好的 EPUB 文件"""
import re
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from loguru import logger

try:
    from ebooklib import epub
    EBOOKLIB_AVAILABLE = True
except ImportError:
    EBOOKLIB_AVAILABLE = False
    logger.warning("ebooklib 未安装，EPUB 导出功能不可用")

from src.models import BiographyBook, GeneratedChapter


class EPUBExporter:
    """EPUB 导出器"""

    def __init__(self):
        if not EBOOKLIB_AVAILABLE:
            raise ImportError("请安装 ebooklib: pip install ebooklib")

    def export(
        self,
        book: BiographyBook,
        output_path: Path,
        cover_image: Optional[Path] = None
    ) -> Path:
        """
        导出为 EPUB 格式

        Args:
            book: 传记书籍对象
            output_path: 输出文件路径
            cover_image: 封面图片路径（可选）

        Returns:
            生成的 EPUB 文件路径
        """
        logger.info(f"开始生成 EPUB: {output_path}")

        # 创建 EPUB 书籍
        epub_book = epub.EpubBook()

        # 设置元数据
        self._set_metadata(epub_book, book)

        # 添加封面
        if cover_image and cover_image.exists():
            self._add_cover(epub_book, cover_image)

        # 创建章节
        chapters = self._create_chapters(epub_book, book)

        # 创建目录
        self._create_toc(epub_book, book, chapters)

        # 创建导航
        self._create_navigation(epub_book, chapters)

        # 添加样式
        self._add_styles(epub_book)

        # 写入文件
        epub.write_epub(str(output_path), epub_book)

        logger.info(f"EPUB 生成完成: {output_path}")
        return output_path

    def _set_metadata(self, epub_book: epub.EpubBook, book: BiographyBook):
        """设置 EPUB 元数据"""
        # 标题
        title = book.outline.title
        if book.outline.subtitle:
            title = f"{title} - {book.outline.subtitle}"

        epub_book.set_identifier(book.id)
        epub_book.set_title(title)
        epub_book.set_language('zh-CN')

        # 作者信息
        epub_book.add_author(book.outline.subject_name)

        # 其他元数据
        epub_book.add_metadata('DC', 'description', f"{book.outline.subject_name}传记")
        epub_book.add_metadata('DC', 'date', book.created_at.strftime('%Y-%m-%d'))
        epub_book.add_metadata('DC', 'publisher', 'AI传记写作系统')

    def _add_cover(self, epub_book: epub.EpubBook, cover_path: Path):
        """添加封面"""
        with open(cover_path, 'rb') as f:
            cover_data = f.read()

        # 根据文件扩展名确定 MIME 类型
        ext = cover_path.suffix.lower()
        mime_type = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
        }.get(ext, 'image/jpeg')

        cover_image = epub.EpubImage(
            uid='cover-image',
            file_name='images/cover' + ext,
            media_type=mime_type,
            content=cover_data
        )
        epub_book.add_item(cover_image)

        # 创建封面页
        cover_content = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>封面</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            text-align: center;
        }}
        .cover {{
            width: 100%;
            height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}
        .cover img {{
            max-width: 80%;
            max-height: 60vh;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }}
        .cover-title {{
            font-size: 2.5em;
            color: white;
            margin-top: 30px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        .cover-subtitle {{
            font-size: 1.2em;
            color: rgba(255,255,255,0.9);
            margin-top: 10px;
        }}
    </style>
</head>
<body>
    <div class="cover">
        <img src="images/cover{cover_path.suffix}" alt="封面"/>
        <div class="cover-title">{epub_book.title}</div>
    </div>
</body>
</html>'''

        cover_page = epub.EpubHtml(
            title='封面',
            file_name='cover.xhtml',
            content=cover_content
        )
        epub_book.add_item(cover_page)
        epub_book.set_cover(file_name='images/cover' + cover_path.suffix, content=cover_data)

    def _create_chapters(self, epub_book: epub.EpubBook, book: BiographyBook) -> List[epub.EpubHtml]:
        """创建章节内容"""
        chapters = []

        # 序言
        if book.outline.prologue:
            prologue = self._create_html_chapter(
                epub_book,
                '序言',
                'prologue.xhtml',
                '序',
                book.outline.prologue,
                is_prologue=True
            )
            chapters.append(prologue)

        # 正文章节
        for i, chapter in enumerate(book.chapters, 1):
            chapter_html = self._create_chapter_content(epub_book, chapter, i)
            chapters.append(chapter_html)

        # 后记
        if book.outline.epilogue:
            epilogue = self._create_html_chapter(
                epub_book,
                '后记',
                'epilogue.xhtml',
                '后记',
                book.outline.epilogue,
                is_epilogue=True
            )
            chapters.append(epilogue)

        return chapters

    def _create_chapter_content(
        self,
        epub_book: epub.EpubBook,
        chapter: GeneratedChapter,
        chapter_num: int
    ) -> epub.EpubHtml:
        """创建单个章节内容"""
        # 构建章节内容
        content_parts = []

        # 章节标题
        content_parts.append(f'<h1 class="chapter-title">{chapter.outline.title}</h1>')

        # 章节简介（如果有）
        if chapter.outline.summary:
            content_parts.append(f'<p class="chapter-summary">{chapter.outline.summary}</p>')

        # 各小节内容
        for section in chapter.sections:
            # 小节标题
            content_parts.append(f'<h2 class="section-title">{section.title}</h2>')

            # 小节内容（将换行转换为段落）
            paragraphs = self._text_to_paragraphs(section.content)
            content_parts.extend(paragraphs)

        # 过渡段落（如果有）
        if chapter.transition_paragraph:
            content_parts.append(f'<p class="transition">{chapter.transition_paragraph}</p>')

        # 组装完整 HTML
        html_content = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <title>{chapter.outline.title}</title>
    <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
    {''.join(content_parts)}
</body>
</html>'''

        # 创建 EPUB 章节
        chapter_file = epub.EpubHtml(
            title=chapter.outline.title,
            file_name=f'chapter_{chapter_num:02d}.xhtml',
            content=html_content
        )

        epub_book.add_item(chapter_file)
        return chapter_file

    def _create_html_chapter(
        self,
        epub_book: epub.EpubBook,
        title: str,
        file_name: str,
        heading: str,
        content: str,
        is_prologue: bool = False,
        is_epilogue: bool = False
    ) -> epub.EpubHtml:
        """创建 HTML 章节"""
        css_class = 'prologue' if is_prologue else ('epilogue' if is_epilogue else '')

        paragraphs = self._text_to_paragraphs(content)

        html_content = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>{title}</title>
    <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
    <h1 class="chapter-title {css_class}">{heading}</h1>
    {''.join(paragraphs)}
</body>
</html>'''

        chapter = epub.EpubHtml(
            title=title,
            file_name=file_name,
            content=html_content
        )

        epub_book.add_item(chapter)
        return chapter

    def _text_to_paragraphs(self, text: str) -> List[str]:
        """将文本转换为 HTML 段落"""
        paragraphs = []

        # 分割段落
        raw_paragraphs = re.split(r'\n\n+', text.strip())

        for para in raw_paragraphs:
            para = para.strip()
            if not para:
                continue

            # 检查是否已经是标题（以 # 开头）
            if para.startswith('#'):
                level = len(para) - len(para.lstrip('#'))
                content = para.lstrip('#').strip()
                paragraphs.append(f'<h{min(level + 1, 6)}>{content}</h{min(level + 1, 6)}>')
            else:
                # 普通段落
                # 处理 Markdown 粗体 **text**
                para = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', para)
                # 处理 Markdown 斜体 *text*
                para = re.sub(r'\*(.+?)\*', r'<em>\1</em>', para)
                # 处理换行
                para = para.replace('\n', '<br/>')

                paragraphs.append(f'<p>{para}</p>')

        return paragraphs

    def _create_toc(self, epub_book: epub.EpubBook, book: BiographyBook, chapters: List[epub.EpubHtml]):
        """创建目录"""
        # 创建目录页
        toc_items = []

        toc_items.append('<h1>目录</h1>')
        toc_items.append('<nav epub:type="toc">')
        toc_items.append('<ol>')

        for i, chapter in enumerate(book.chapters, 1):
            chapter_file = f'chapter_{i:02d}.xhtml'
            toc_items.append(f'<li><a href="{chapter_file}">{chapter.outline.title}</a></li>')

        toc_items.append('</ol>')
        toc_items.append('</nav>')

        toc_html = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <title>目录</title>
    <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
    {''.join(toc_items)}
</body>
</html>'''

        toc_page = epub.EpubHtml(
            title='目录',
            file_name='toc.xhtml',
            content=toc_html
        )

        epub_book.add_item(toc_page)

        # 设置目录（NCX）
        epub_book.toc = chapters

    def _create_navigation(self, epub_book: epub.EpubBook, chapters: List[epub.EpubHtml]):
        """创建导航文档"""
        # 添加所有章节到 spine（阅读顺序）
        epub_book.spine = ['nav'] + chapters

        # 创建导航文档
        nav_content = '''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <title>导航</title>
    <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
    <nav epub:type="toc">
        <h1>目录</h1>
        <ol>
'''

        for chapter in chapters:
            nav_content += f'            <li><a href="{chapter.file_name}">{chapter.title}</a></li>\n'

        nav_content += '''        </ol>
    </nav>
</body>
</html>'''

        nav = epub.EpubNav(content=nav_content)
        epub_book.add_item(nav)

    def _add_styles(self, epub_book: epub.EpubBook):
        """添加 CSS 样式"""
        css_content = '''
/* 基础样式 */
body {
    font-family: "Noto Serif CJK SC", "Source Han Serif SC", "SimSun", serif;
    font-size: 1.1em;
    line-height: 1.8;
    color: #333;
    margin: 0;
    padding: 2em;
    text-align: justify;
}

/* 章节标题 */
h1.chapter-title {
    font-size: 2em;
    font-weight: bold;
    text-align: center;
    margin: 2em 0 1em 0;
    color: #222;
    border-bottom: 2px solid #764ba2;
    padding-bottom: 0.5em;
}

h1.chapter-title.prologue,
h1.chapter-title.epilogue {
    color: #667eea;
    border-bottom-color: #667eea;
}

/* 小节标题 */
h2.section-title {
    font-size: 1.5em;
    font-weight: bold;
    margin: 1.5em 0 0.8em 0;
    color: #444;
}

/* 段落 */
p {
    margin: 0.8em 0;
    text-indent: 2em;
}

/* 章节简介 */
p.chapter-summary {
    font-style: italic;
    color: #666;
    border-left: 3px solid #764ba2;
    padding-left: 1em;
    margin: 1em 0;
    text-indent: 0;
}

/* 过渡段落 */
p.transition {
    text-align: center;
    font-style: italic;
    color: #888;
    margin: 2em 0;
    text-indent: 0;
}

/* 目录样式 */
nav[epub:type="toc"] h1 {
    font-size: 1.8em;
    text-align: center;
    margin-bottom: 1em;
}

nav[epub:type="toc"] ol {
    list-style: none;
    padding: 0;
}

nav[epub:type="toc"] li {
    margin: 0.5em 0;
    padding: 0.3em 0;
    border-bottom: 1px dotted #ddd;
}

nav[epub:type="toc"] a {
    color: #333;
    text-decoration: none;
}

nav[epub:type="toc"] a:hover {
    color: #764ba2;
}

/* 强调 */
strong {
    font-weight: bold;
    color: #222;
}

em {
    font-style: italic;
}

/* 分页 */
@media print {
    h1.chapter-title {
        page-break-before: always;
    }
    h1.chapter-title:first-of-type {
        page-break-before: auto;
    }
}
'''

        style = epub.EpubItem(
            uid="style",
            file_name="style.css",
            media_type="text/css",
            content=css_content
        )
        epub_book.add_item(style)


def export_to_epub(
    book: BiographyBook,
    output_path: Path,
    cover_image: Optional[Path] = None
) -> Path:
    """
    导出书籍为 EPUB 格式的便捷函数

    Args:
        book: 传记书籍对象
        output_path: 输出文件路径
        cover_image: 封面图片路径（可选）

    Returns:
        生成的 EPUB 文件路径
    """
    exporter = EPUBExporter()
    return exporter.export(book, output_path, cover_image)
