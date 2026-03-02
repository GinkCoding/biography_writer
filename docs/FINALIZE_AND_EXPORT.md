# 终版选择与导出功能

本文档介绍传记生成系统的版本选择和导出功能。

## 功能概述

系统支持以下功能：

1. **版本选择**：从多个生成的章节版本中选择最佳内容
2. **格式导出**：支持 TXT, Markdown, JSON, EPUB 四种格式
3. **EPUB 生成**：生成格式正确、兼容性好的 EPUB 电子书

## 快速开始

### 基本使用

```python
import asyncio
from src.engine import BiographyEngine

async def main():
    engine = BiographyEngine()

    # 初始化并生成传记
    book_id = await engine.initialize_from_interview(
        interview_file=Path("interviews/sample.txt"),
        style=WritingStyle.LITERARY,
        target_words=100000
    )

    book = await engine.generate_book()

    # 导出所有格式（自动选择最佳版本）
    exported = await engine.save_book(
        book=book,
        formats=["txt", "md", "json", "epub"],
        cover_image=Path("assets/cover.jpg"),  # 可选
        use_version_selection=True
    )

    print(f"EPUB 文件: {exported['epub']}")

asyncio.run(main())
```

### 仅运行演示

```bash
# 运行版本选择演示（无需采访文件）
python example_finalize_and_export.py --demo
```

## 版本选择机制

### 工作原理

1. 每章生成后，系统自动计算质量评分
2. 如果某章需要重新生成，新版本会加入版本池
3. 最终选择时，系统从每个章节的历史版本中选择最佳版本
4. 最佳版本组合成完整书籍

### 评分标准

- **基础分**：按目标字数完成比例计算
- **验证加分**：通过事实核查 +2.0 分
- **问题扣分**：每个问题 -0.3 分

### 查看版本报告

```python
# 获取版本选择报告
report = engine.get_version_report()
print(report)
```

输出示例：

```markdown
# 版本选择报告

## 第1章
共生成 3 个版本
1. [✓] 14:32:10 - 3200字 - 评分8.5 - 0个问题
2. [✗] 14:35:22 - 2800字 - 评分6.2 - 2个问题
3. [✓] 14:40:15 - 3100字 - 评分7.8 - 1个问题
```

## EPUB 导出

### 特性

- **标准合规**：符合 EPUB 3.0 标准
- **中文字体优化**：支持思源宋体、Noto Serif CJK 等
- **封面支持**：可自定义封面图片
- **目录导航**：自动生成可点击目录
- **样式美观**：内置美观的 CSS 样式

### 兼容性

| 阅读器 | 支持情况 |
|--------|----------|
| Apple iBooks | ✅ 完全支持 |
| 微信读书 | ✅ 完全支持 |
| 多看阅读 | ✅ 完全支持 |
| Calibre | ✅ 完全支持 |
| Kindle | ⚠️ 需通过 Calibre 转换 |

### 自定义封面

```python
from pathlib import Path

# 使用自定义封面
cover = Path("assets/my_cover.jpg")
await engine.save_book(book, cover_image=cover)
```

支持的封面格式：
- JPG/JPEG
- PNG

### 手动导出 EPUB

```python
from src.generator import export_to_epub
from pathlib import Path

output_path = export_to_epub(
    book=book,
    output_path=Path("output/my_book.epub"),
    cover_image=Path("assets/cover.jpg")  # 可选
)
```

## 高级用法

### 使用 BookFinalizer 直接控制

```python
from src.generator import BookFinalizer

# 创建终版生成器
finalizer = BookFinalizer(output_dir=Path("output"))

# 添加章节版本（可以添加多个版本）
for chapter in chapters:
    finalizer.add_chapter_version(chapter, quality_score=8.5)

# 生成终版
final_book = finalizer.finalize_book(outline, book_id)

# 导出指定格式
results = finalizer.export_all_formats(
    final_book,
    cover_image=Path("cover.jpg")
)
```

### 一站式导出

```python
from src.generator import finalize_and_export

# 一次性完成版本选择和导出
results = finalize_and_export(
    chapters=chapters,
    outline=outline,
    book_id="my_book",
    output_dir=Path("output"),
    cover_image=Path("cover.jpg")
)

# results 包含所有格式的路径
print(results["txt"])    # TXT 文件路径
print(results["epub"])   # EPUB 文件路径
```

## 输出文件结构

```
output/
└── my_book/
    ├── metadata.json              # 元数据
    ├── outline.json               # 大纲
    ├── version_report.md          # 版本选择报告
    ├── My_Book_Title.txt          # 纯文本格式
    ├── My_Book_Title.md           # Markdown 格式
    ├── My_Book_Title.epub         # EPUB 格式
    └── chapters/                  # 分章节文件
        ├── 01_第一章.md
        ├── 02_第二章.md
        └── ...
```

## 故障排除

### EPUB 导出失败

```python
# 检查 ebooklib 是否安装
pip install ebooklib>=0.18

# 如果未安装，系统会给出警告并跳过 EPUB 导出
```

### 版本选择未生效

确保在初始化 ReviewOutputLayer 时启用了版本选择：

```python
review_layer = ReviewOutputLayer(
    llm=llm,
    timeline=timeline,
    output_dir=output_dir,
    enable_version_selection=True  # 确保为 True
)
```

### 封面图片不显示

- 确保图片格式为 JPG 或 PNG
- 确保图片路径正确
- 图片尺寸建议：1200x1600 像素（6:8 比例）

## 相关文件

- `src/generator/book_finalizer.py` - 版本选择和终版生成
- `src/generator/epub_exporter.py` - EPUB 导出器
- `src/layers/review_output.py` - 审校层集成
- `example_finalize_and_export.py` - 使用示例
