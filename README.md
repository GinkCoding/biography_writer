# 传记写作工具（LLM-Driven 架构）

将采访文本转化为十万字长篇传记的AI写作系统。采用LLM驱动架构，让大模型成为核心决策者。

> **注意**：这是 `llm-driven-architecture` 分支，采用全新的7阶段流水线架构。如需查看旧版五层架构，请切换到 `main` 分支。

## 架构理念

本分支采用**LLM-Driven架构**，核心理念：

1. **LLM是决策者，不只是生成器** - 素材评估、大纲设计、质量判断都由LLM完成
2. **正面引导，而非硬约束** - 告诉LLM"要做什么"，而非"不能做什么"
3. **代码提取事实，LLM理解上下文** - 代码只记录线索，LLM理解复杂关系动态
4. **累积式修订** - 每轮修订附带历史，LLM看到完整的修改轨迹

## 7阶段流水线

```
采访素材 → [1.素材评估] → [2.大纲生成] → [3.大纲审核] → [4.章节生成] → [5.四维度审核] → [6.累积修订] → [7.终稿组装]
              ↓                ↓              ↓              ↓              ↓              ↓
         评估报告          双版本竞争      时间线检查      逐章扩展      并行审核       迭代优化
         建议字数          LLM选择最优      重复性检查      关系分析      事实/连贯/      带历史记录
         推断策略                                                  重复/文学      多轮迭代
```

## 快速开始

### 1. 安装依赖

```bash
cd /Users/guoquan/work/Kimi/biography_writer
pip install -r requirements.txt
```

### 2. 配置API密钥

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的API密钥
```

支持的模型提供商：
- **Kimi**（默认，推荐）: `kimi-k2-5-long-context`，128K上下文
- **OpenAI**: `gpt-4-turbo-preview`
- **智谱**: `zhipuai`

### 3. 运行流水线

```bash
# 基本用法
python run_pipeline.py /path/to/interview.txt

# 指定输出目录和目标字数
python run_pipeline.py /path/to/interview.txt --output ./output --target-words 100000

# 使用测试模式（验证流程，不实际调用LLM）
python test_pipeline_minimal.py
```

### 4. 查看结果

```bash
# 生成的传记位于
output/<项目ID>/biography_<日期>.md

# 中间产物
output/<项目ID>/
├── evaluation_report.json      # 素材评估报告
├── outline_final.json          # 最终大纲
├── chapters/                   # 各章节草稿
│   ├── chapter_01.md
│   ├── chapter_01_review.json  # 审核结果
│   └── chapter_01_v1.md        # 修订版本
├── facts_db.json               # 事实数据库
└── vector_store.json           # 向量存储
```

## 核心组件

### 事实数据库 (`facts_db.py`)

轻量级JSON存储，记录：
- **人物**: 姓名、关系、首次出场章节、物理状态（在世/去世）
- **关系线索**: 动态记录关系变化（如"大吵一架"、"和解"、"疏远"）
- **事件**: 时间、地点、描述
- **地点**: 名称、描述

关键特点：**代码只提取线索，LLM理解关系动态**。不硬编码"死亡=不能出现"，而是让LLM根据上下文判断合理的表达方式。

### 关系分析器 (`relationship_analyzer.py`)

使用LLM分析人物关系的微妙之处：
- 区分"大吵但未决裂" vs "彻底断绝"
- 理解"表面和解但心存芥蒂"
- 判断哪些互动在当前关系状态下是合理的

### 四维度审核 (`agents.py`)

每个章节生成后，并行运行4个审核Agent：

| Agent | 职责 | 检查内容 |
|-------|------|----------|
| **FactChecker** | 事实审核 | 与原始素材的矛盾（时间、地点、人物、事件、数字） |
| **ContinuityChecker** | 连贯审核 | 时间线连续性、章间衔接、人物关系一致性 |
| **RepetitionChecker** | 重复审核 | 跨章重复、章内重复、车轱辘话、信息密度 |
| **LiteraryChecker** | 文学审核 | 描写质量、对话质量、叙事节奏、情感表达 |

### 累积式修订

未通过的章节进入修订循环：
1. 收集所有审核意见
2. 保留修订历史（之前修改过什么）
3. LLM根据审核意见和历史进行修订
4. 重新审核，直到通过或达到最大迭代次数

## 配置选项

### 环境变量 (.env)

```bash
# Kimi（推荐）
LLM_PROVIDER=kimi
KIMI_API_KEY=your_kimi_api_key_here
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_MODEL=kimi-k2-5-long-context

# SiliconFlow Embedding（可选）
SILICONFLOW_API_KEY=your_siliconflow_api_key_here
```

### 生成参数 (config/settings.yaml)

```yaml
model:
  provider: openai
  base_url: https://coding.dashscope.aliyuncs.com/v1
  model: qwen3.5-plus
  max_tokens: 32768
  request_timeout_seconds: 300

generation:
  target_length: 10000      # 目标字数（默认1万字，可调整到10万）
  total_chapters: 25        # 章节数
  sections_per_chapter: 4   # 每章节数
  style: literary           # 风格
```

## 与旧版架构的区别

| 特性 | 旧版（main分支） | 新版（本分支） |
|------|-----------------|---------------|
| 架构 | 五层工程化架构 | 7阶段LLM流水线 |
| 素材处理 | 切分块，RAG检索 | 全素材给LLM理解 |
| 大纲生成 | 模板+规则 | LLM自由设计，双版本竞争 |
| 人物状态 | 硬编码（死亡=不能出现） | 线索记录，LLM理解语境 |
| 审核方式 | 单一FactChecker | 四维度并行审核 |
| 修订机制 | 单轮重写 | 累积式多轮修订 |
| 字数控制 | 严格限制每节字数 | 整体把控，弹性范围 |

## 文件结构

```
biography_writer/
├── run_pipeline.py              # 主入口脚本
├── test_pipeline_minimal.py     # 最小化测试
├── config/
│   ├── settings.yaml            # 模型配置
│   └── styles.yaml              # 写作风格
├── src/
│   ├── core/
│   │   ├── pipeline.py          # 7阶段流水线主逻辑
│   │   ├── agents.py            # 4个审核Agent
│   │   ├── models.py            # 数据模型
│   │   ├── facts_db.py          # 事实数据库
│   │   ├── relationship_analyzer.py  # 关系分析器
│   │   └── vector_store.py      # 向量存储
│   ├── llm_client.py            # LLM客户端（支持思考模式）
│   └── config.py                # 配置管理
├── interviews/                  # 采访文件存放目录
├── output/                      # 生成的传记输出目录
└── README.md                    # 本文件
```

## 技术特点

- **全素材理解**: 采访素材完整提供给LLM，而非切片检索
- **双版本竞争**: 大纲生成两版本，LLM选择最优
- **关系线索系统**: 不硬编码状态，记录线索让LLM理解动态
- **四维度审核**: 事实、连贯、重复、文学四个角度并行检查
- **累积式修订**: 带历史记录的多轮迭代优化
- **智能推断**: 合理推断缺失年份，自动标注推断内容
- **弹性字数**: 建议目标字数，允许±10%自然波动

## 注意事项

1. **API成本**: 本架构调用LLM次数较多（素材评估+大纲×2+大纲审核+章节×(生成+审核+修订)×轮数），10万字预计需要100-150次调用
2. **生成时间**: 全书生成可能需要1-3小时（取决于审核迭代次数）
3. **上下文长度**: 需要支持128K上下文的模型（如kimi-k2-5-long-context）
4. **事实核查**: 虽然有多重审核，重要传记仍建议人工复核
5. **隐私保护**: 涉及个人隐私的内容请谨慎处理

## License

MIT
