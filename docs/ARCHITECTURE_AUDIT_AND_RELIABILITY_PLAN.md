# 架构审计与稳定性优化报告

## 审计结论（摘要）

项目核心五层架构思路是合理的，但在“可观测性闭环”和“运行时稳定性”上存在关键断点，直接导致你提到的“卡住且看不出是否正常运行”。

本轮已完成一批高优先级修复，重点解决：
1. 长任务过程可见性（控制台 + 文件）
2. 节点产物落盘与索引
3. 运行态卡死风险（死锁）
4. 仓库卫生与敏感信息风险

## 主要问题（按严重级别）

## P0
- `src/observability/runtime_monitor.py` 存在可重入死锁风险：`start_run()/end_run()` 在持锁状态下调用 `log_event()`，而 `log_event()` 再次申请同一把锁。表现是任务在启动或结束阶段“无输出卡住”。
- `src/cli.py` 发生缩进错误，导致 CLI 无法正常解析执行（初始化链路直接失效）。

## P1
- `src/engine.py` 在 `load_project -> generate_book` 场景下没有强制启动 runtime run，导致 `status/events/artifacts` 不落盘，排障链路断裂。
- `config/settings.yaml` 存在明文 API Key，存在泄露风险。

## P2
- 仓库缺少运行产物忽略策略，`.cache/output/.observability/.vector_db` 导致状态噪音过高、审查成本高。
- 运行态缺少独立查询入口，初始化阶段若 outline 尚未生成，用户无法快速确认流程是否在前进。

## 已实施优化

### 1) 运行态监控修复与增强
- 文件：`src/observability/runtime_monitor.py`
- 修改：
  - `threading.Lock` -> `threading.RLock`，消除重入死锁。
  - `status.json` 增加路径字段：`run_dir/events_file/status_file/artifacts_dir/manifest_file`。
  - `events.jsonl` 增加 `sequence`，便于事件顺序追踪。
  - 新增 `artifacts_manifest.json`，自动登记每个节点产物（阶段、文件、大小、时间）。

### 2) 引擎运行态闭环
- 文件：`src/engine.py`
- 修改：
  - `initialize_from_interview()` 记录 `run_id`，并输出监控文件位置信息。
  - 新增 `_ensure_runtime_run()`，确保 `generate_book()`/`generate_single_chapter()` 在任意入口都有 run 上下文。
  - `initialize_from_interview()` 接入 `llm` 进度回调，初始化阶段也能看到心跳。
  - `generate_single_chapter()` 补齐 run 完成/失败收敛，避免悬挂运行态。
  - `get_progress()` 输出 `run_id/events_file/artifacts_dir/event_count`。

### 3) LLM 调用稳定性
- 文件：`src/llm_client.py`
- 修改：
  - OpenAI/兼容接口与智谱接口均增加请求级 timeout（含 SDK 不支持 timeout 的兼容回退）。
  - 异步 loop API 调整为 `get_running_loop()`。
  - 配合既有 heartbeat 与重试日志，提升“在跑还是卡住”的可感知性。

### 4) CLI 交互体验
- 文件：`src/cli.py`
- 修改：
  - 修复 `init` 命令缩进错误。
  - `status` 命令展示运行阶段、最后消息、事件数和监控文件路径。
  - 新增 `runtime-status` 命令：无需依赖 outline，可直接查看最新运行态并 tail 最近事件。
  - 欢迎面板加入 `runtime-status` 指引。

### 5) 仓库与安全卫生
- 文件：`.gitignore`
- 修改：忽略 `.cache/.vector_db/.observability/output/.env*/*.log` 等运行与敏感文件。
- 文件：`config/settings.yaml`
- 修改：清空明文 API Key。

### 6) 文档化
- 文件：`README.md`
- 修改：增加运行态查看方式和 `.observability/runs/<run_id>/` 目录说明。

## 架构合理性评估

## 保留
- 五层架构边界总体清晰，数据流向符合“素材 -> 知识 -> 规划 -> 生成 -> 审校”逻辑。
- `WorkflowTracer + Metrics + RuntimeMonitor` 的多维观测方向正确。

## 建议继续演进
- 将 `engine.py` 进一步拆分为 `Orchestrator`（编排）与 `RunContext`（运行态），降低单文件复杂度。
- 将“重试、超时、心跳”策略提取成统一策略模块，避免散落在客户端调用路径。
- 对 run 增加阶段级 SLA（例如每层最大耗时阈值）并输出 stall 告警事件。

## 验证结果

- 语法检查：`python3 -m compileall -q src tests` 通过。
- 测试现状：
  - `test_templates_simple.py` 可运行并通过。
  - 其余测试受本机 Python 包架构冲突阻塞（`numpy/pydantic_core` 为 x86_64，当前解释器为 arm64），属于环境问题，不是本轮改动引入。

## 后续执行建议

1. 先修本机依赖架构（arm64 统一）并恢复完整 pytest 回归。
2. 增加 `runtime-status --follow` 持续追踪模式（当前为快照 + tail）。
3. 在健康报告中增加“每层耗时分布 + 超时重试次数”用于性能瓶颈定位。
4. 为 `.observability/runs` 增加自动清理策略（按天/按数量）。
