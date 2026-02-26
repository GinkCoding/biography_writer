# 传记写作系统使用指南

## 系统架构

该系统采用五层架构设计：

1. **数据摄入层** (DataIngestionLayer): 处理采访稿，提取素材
2. **知识记忆层** (KnowledgeMemoryLayer): 构建时间线、关系图谱、人物小传
3. **规划层** (PlanningLayer): 生成书籍大纲和章节规划
4. **生成层** (GenerationLayer): 迭代生成章节内容
5. **审校输出层** (ReviewOutputLayer): 质量审查、版本选择、多格式导出

## 完整工作流程

### 步骤1: 准备环境

```bash
# 安装依赖
pip install -r requirements.txt

# 准备采访稿
mkdir -p interviews
cp your_interview.txt interviews/
```

### 步骤2: 完整生成流程

```python
import asyncio
from pathlib import Path

from src.config import settings
from src.llm_client import LLMClient
from src.layers import (
    DataIngestionLayer,
    KnowledgeMemoryLayer,
    PlanningLayer,
    IterativeGenerationLayer,
    ReviewOutputLayer,
)
from src.models import WritingStyle

async def generate_biography():
    # 初始化
    settings.ensure_dirs()
    llm = LLMClient()
    book_id = "biography_001"

    # 步骤1: 数据摄入
    print("[1/5] 数据摄入...")
    data_layer = DataIngestionLayer()
    materials = await data_layer.process_interview(
        Path("interviews/采访稿.txt"),
        subject_hint="传主姓名"
    )

    # 步骤2: 知识构建
    print("[2/5] 知识构建...")
    km_layer = KnowledgeMemoryLayer(llm)
    timeline, knowledge_graph, state_manager = await km_layer.build_knowledge_base(
        materials, book_id
    )

    # 步骤3: 大纲规划
    print("[3/5] 大纲规划...")
    planning_layer = PlanningLayer(llm)
    outline = await planning_layer.generate_outline(
        timeline=timeline,
        knowledge_graph=knowledge_graph,
        style=WritingStyle.LITERARY,
        target_words=100000
    )

    # 步骤4: 内容生成
    print("[4/5] 内容生成...")
    gen_layer = IterativeGenerationLayer(llm)
    review_layer = ReviewOutputLayer(
        llm, timeline, Path(settings.paths.output_dir),
        enable_version_selection=True  # 启用版本选择
    )

    book = outline.to_book(book_id)

    for chapter_outline in outline.chapters:
        # 生成章节
        chapter = await gen_layer.generate_chapter(
            chapter_outline=chapter_outline,
            outline=outline,
            global_state=state_manager.state
        )

        # 审查章节（自动添加到版本池）
        reviewed_chapter = await review_layer.review_chapter(
            chapter=chapter,
            chapter_context={"style": outline.style.value}
        )

        book.chapters.append(reviewed_chapter)
        state_manager.update_progress(chapter_outline.order, "completed")

    # 步骤5: 终版生成和导出
    print("[5/5] 终版生成和导出...")
    saved_files = await review_layer.finalize_book(
        book=book,
        formats=["txt", "md", "json", "epub"],
        cover_image=Path("cover.jpg"),  # 可选
        use_version_selection=True  # 从多个版本中选择最佳
    )

    print(f"生成完成！")
    for fmt, path in saved_files.items():
        print(f"  - {fmt}: {path}")

    return saved_files

if __name__ == "__main__":
    asyncio.run(generate_biography())
```

### 步骤3: 版本选择功能

系统支持为同一章节生成多个版本，并自动选择最佳版本：

```python
# 重新生成某章（保留旧版本）
old_version = review_layer.regenerate_chapter(3)

# 生成改进版本
new_chapter = await gen_layer.generate_chapter(
    chapter_outline=outline.chapters[2],
    outline=outline,
    global_state=state_manager.state,
    previous_chapter=book.chapters[1] if len(book.chapters) > 1 else None
)

# 审查并添加为新版本
reviewed = await review_layer.review_chapter(new_chapter, {...})
review_layer.add_chapter_version(reviewed, quality_score=8.5)

# 查看版本报告
report = review_layer.get_version_report()
print(report)
```

### 步骤4: 导出格式

系统支持多种导出格式：

- **TXT**: 纯文本格式，适合打印
- **MD**: Markdown格式，适合在线阅读
- **JSON**: 结构化数据，适合后续处理
- **EPUB**: 标准电子书格式，支持封面、目录、样式

```python
# 导出所有格式
saved_files = await review_layer.finalize_book(
    book,
    formats=["txt", "md", "json", "epub"],
    cover_image=Path("cover.jpg")
)

# 或使用 BookFinalizer 直接导出
from src.generator import BookFinalizer

finalizer = BookFinalizer(output_dir)
for chapter in chapters:
    finalizer.add_chapter_version(chapter)

final_book = finalizer.finalize_book(outline, book_id)
results = finalizer.export_all_formats(final_book, cover_image)
```

## 配置说明

### 模型配置 (config/settings.yaml)

```yaml
model:
  provider: kimi  # 或 openai, zhipuai
  api_key: ""
  model: kimi
  max_tokens: 4000
  temperature: 0.7

generation:
  target_length: 100000  # 目标字数
  total_chapters: 25     # 章节数
```

### 风格配置 (config/styles.yaml)

预定义风格：
- `documentary`: 纪实严谨
- `literary`: 文学散文
- `investigative`: 新闻调查

## 质量保障机制

1. **事实核查**: 自动核对时间、地点、人物一致性
2. **逻辑流检查**: 确保章节间过渡自然
3. **文学编辑**: 提升文学性和可读性
4. **跨章节一致性**: 维护人物称谓、伏笔回收
5. **循环检测**: 防止生成重复内容（车轱辘话）

## 常见问题

### Q: 如何避免AI生成占位符内容？
A: 系统内置了占位符检测和自动重写机制，同时有严格的事实底线约束。

### Q: 生成的内容有重复怎么办？
A: 系统使用语义指纹技术检测重复内容，会自动触发升级策略（提高temperature、分步生成等）。

### Q: 如何控制生成进度？
A: 使用 `--chapter N` 生成单章，或使用 `--resume` 从断点继续。

### Q: EPUB格式兼容性如何？
A: 使用标准 `ebooklib` 库生成，兼容主流阅读器（Apple Books、Kindle、微信读书等）。

## 验证系统

运行验证脚本检查系统完整性：

```bash
python3 validate_workflow.py
```

预期输出: `✓ 验证通过！系统可以按预期执行。`
