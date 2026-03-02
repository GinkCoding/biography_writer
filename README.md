# 传记写作工具

将采访文本转化为十万字长篇传记的AI写作系统。

## 系统架构

基于五层架构设计：

1. **数据接入与解析层** - 清洗采访文本，切分话题块，存入向量数据库
2. **知识构建与全局记忆层** - 抽取实体关系，构建时间线，管理全局状态
3. **规划与编排层** - 确定写作风格，生成三级大纲（卷-章-节）
4. **迭代生成层** - 上下文组装，逐节生成，时代背景增强
5. **审校与输出层** - 双重Agent事实核查，逻辑校验，多格式输出

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

### 3. 准备采访文件

将采访文本放入 `interviews/` 目录，支持 `.txt` 或 `.md` 格式。

### 4. 初始化项目

```bash
python -m biography init
# 或指定文件
python -m biography init 张三采访.txt --subject 张三 --style literary
```

### 5. 生成传记

```bash
python -m biography write
# 或指定项目
python -m biography write --id <项目ID>
```

### 6. 查看运行态监控

```bash
# 查看项目状态（含运行阶段、最后消息、监控文件路径）
python -m biography status --id <项目ID>

# 不依赖outline，直接查看最近一次运行态（适合init阶段排障）
python -m biography runtime-status --id <项目ID> --tail 10

# 持续追踪运行事件（观察是否“卡住”）
python -m biography runtime-status --id <项目ID> --follow --interval 2

# 汇总本次运行的事件与节点产物，并输出 runtime_report.json
python -m biography runtime-report --id <项目ID>
```

## 可用写作风格

| 风格ID | 名称 | 特点 |
|--------|------|------|
| documentary | 纪实严谨 | 客观中立、史料详实 |
| literary | 文学散文 | 抒情描写、场景还原 |
| investigative | 新闻调查 | 抽丝剥茧、悬念设置 |
| memoir | 温情回忆 | 第一人称感、情感细腻 |
| inspirational | 励志传记 | 突出成长、强调转折 |

查看所有风格：
```bash
python -m biography styles
```

## 项目结构

```
biography_writer/
├── interviews/          # 采访文件存放目录
├── output/              # 生成的传记输出目录
├── config/
│   ├── settings.yaml    # 主配置
│   └── styles.yaml      # 风格模板
├── src/
│   ├── cli.py           # 命令行入口
│   ├── engine.py        # 主引擎
│   ├── layers/          # 五层架构实现
│   │   ├── data_ingestion.py
│   │   ├── knowledge_memory.py
│   │   ├── planning.py
│   │   ├── generation.py
│   │   └── review_output.py
│   └── ...
└── README.md
```

## 输出格式

生成完成后，输出目录包含：

```
output/<书名>_<日期>/
├── metadata.json           # 元数据
├── outline.json            # 完整大纲
├── <书名>.md               # Markdown完整版
├── <书名>.txt              # 纯文本完整版
└── chapters/               # 分章节文件
    ├── 01_童年时光.md
    ├── 02_求学之路.md
    └── ...
```

运行时监控文件位于：

```
.observability/runs/<run_id>/
├── status.json              # 当前阶段、最后消息、事件计数
├── events.jsonl             # 结构化事件流（started/running/heartbeat/completed/failed）
├── artifacts_manifest.json  # 节点产物清单（可直接用于整合分析）
└── artifacts/
    ├── 01_data_ingestion/*.json
    ├── 02_knowledge_memory/*.json
    ├── 03_planning/*.json
    ├── 04_generation/*.json
    ├── 05_review/*.json
    └── 06_output/*.json
```

## 技术特点

- **RAG检索增强**：基于向量数据库检索相关素材，防止幻觉
- **容错式关键信息提取**：采访稿提取失败自动降级，不因脏文本直接中断
- **滑动窗口记忆**：只携带必要上下文，避免灾难性遗忘
- **双重Agent审校**：生成Agent与审查Agent博弈，保证事实准确
- **时代背景增强**：自动融入对应年代的社会风貌细节
- **智能大纲规划**：基于时间线自动分配章节和篇幅

## 配置选项

编辑 `config/settings.yaml`：

```yaml
model:
  provider: openai  # 或 zhipu, deepseek
  model: gpt-4-turbo-preview
  max_tokens: 4000

generation:
  target_length: 100000  # 目标字数
  total_chapters: 25     # 章节数
  style: literary        # 默认风格
```

## 注意事项

1. **API成本**：10万字生成预计需要50-80次API调用，请注意成本
2. **生成时间**：全书生成可能需要30分钟到数小时
3. **事实核查**：AI可能产生幻觉，重要传记请人工复核
4. **隐私保护**：涉及个人隐私的内容请谨慎处理

## License

MIT
