# LLM-Driven 传记生成架构设计

## 系统目标
打造全自动流水线，从采访素材到成书无需人工干预（仅最后检查结果），以大模型为核心决策引擎。

---

## 一、流水线架构（7阶段）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           全自动传记生成流水线                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Phase 1: 素材评估                                                            │
│  ├─ 输入：完整采访素材.txt + target_words=100000                              │
│  ├─ LLM调用：thinking=true, temperature=0.3                                   │
│  ├─ 超时：300s                                                                │
│  └─ 输出：素材评估报告（JSON）                                                 │
│                                                                             │
│  Phase 2: 大纲生成                                                            │
│  ├─ 输入：素材 + 评估报告                                                     │
│  ├─ LLM调用：thinking=true, temperature=0.5                                   │
│  ├─ 超时：600s                                                                │
│  └─ 输出：详细大纲（JSON，含每节factual/inferred/expanded标注）               │
│                                                                             │
│  Phase 3: 大纲审核 ←───┐                                                      │
│  ├─ 输入：大纲JSON                                                         │
│  ├─ 4个审核Agent并行（无需thinking）                                          │
│  ├─ 超时：120s                                                                │
│  ├─ 输出：大纲审核报告                                                        │
│  └─ 如问题严重，返回Phase 2（最多3轮）                                        │
│                        │                                                      │
│  Phase 4: 章节生成 ────┘                                                      │
│  ├─ For each 章节：                                                           │
│  │   ├─ 输入：大纲 + 素材片段 + 前序摘要（最近3章）                            │
│  │   ├─ LLM调用：thinking=true, temperature=0.6                               │
│  │   ├─ 超时：900s（长文本生成）                                              │
│  │   └─ 输出：章节初稿.txt                                                     │
│  │                                                                           │
│  │   Phase 5: 分级审核（4Agent并行）                                          │
│  │   ├─ 事实审核 + 连贯审核 + 重复审核 + 文学审核（并行）                      │
│  │   ├─ 无需thinking, temperature=0.2                                         │
│  │   ├─ 单个超时：60s                                                         │
│  │   └─ 输出：合并审核报告（结构化+自然语言）                                  │
│  │                                                                           │
│  │   Phase 6: 迭代修订（最多5轮）                                             │
│  │   ├─ 输入：当前版本 + 审核报告 + 历史修改记录（累积式）                     │
│  │   ├─ LLM调用：thinking=true, temperature=0.5                               │
│  │   ├─ 超时：600s                                                            │
│  │   ├─ 质量退化检测 → 如退化严重，取历史最佳版本                              │
│  │   └─ 循环直到：全部通过 或 达5轮 或 检测到退化                              │
│  │                                                                           │
│  └─ End For                                                                   │
│                                                                               │
│  Phase 7: 终审与组装                                                          │
│  ├─ 输入：全部章节txt + 推断标注清单                                          │
│  ├─ 全局连贯审核（章节间衔接）                                                │
│  ├─ 生成完整传记：整合版.txt + 分章节/01_xxx.txt, 02_xxx.txt...                │
│  └─ 生成推断说明附录（所有※标记的推断依据汇总）                                │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、LLM调用策略详细设计

### 2.1 何时使用Thinking模式

| 阶段 | Thinking | 原因 |
|------|----------|------|
| 素材评估 | ✅ | 需要复杂推理判断素材充足度 |
| 大纲生成 | ✅ | 需要时间线规划、章节分配推理 |
| 大纲审核 | ❌ | 只需比对检查，无需创造性思考 |
| 章节生成 | ✅ | 需要内容规划、叙事结构设计 |
| 分级审核 | ❌ | 专项判断，结构化输出即可 |
| 迭代修订 | ✅ | 需要权衡多个审核意见，决定如何修改 |
| 终审组装 | ❌ | 主要是格式化工作 |

### 2.2 上下文管理策略

#### 大纲阶段上下文（全量）
```
[系统提示]
[完整采访素材：3200字]
[输出要求]
```

#### 章节生成上下文（滑动窗口）
```
[系统提示：写作风格、约束]
[大纲：本章结构]
[素材片段：RAG检索相关部分]
[前序摘要：最近3章的核心事件（每章200字）]
[推断标注：本节哪些内容可推断]
```

#### 审核阶段上下文（精准）
```
[系统提示：审核维度、标准]
[当前章节全文]
[原始素材（仅事实审核需要）]
```

#### 修订阶段上下文（累积）
```
[系统提示：修订规则]
[当前版本全文]
[历史修改记录]
[审核报告：新问题 + 已通过检查]
```

### 2.3 Temperature配置

| 阶段 | Temperature | 原因 |
|------|-------------|------|
| 素材评估 | 0.3 | 客观判断，减少偏差 |
| 大纲生成 | 0.5 | 需要一定创造性但不离谱 |
| 章节生成 | 0.6 | 文学创作需要温度 |
| 审核 | 0.2 | 严格、一致 |
| 修订 | 0.5 | 平衡创意与约束 |

### 2.4 超时配置

```yaml
# config/settings.yaml
llm:
  timeouts:
    material_evaluation: 300    # 素材评估
    outline_generation: 600     # 大纲生成
    outline_review: 120         # 大纲审核
    chapter_generation: 900     # 章节生成（长文本）
    content_review: 60          # 单维度审核
    chapter_revision: 600       # 章节修订
    final_assembly: 180         # 终审组装

  max_retries: 3
  retry_delay: 2
```

---

## 三、审核Agent详细设计

### 3.1 并行审核架构

```python
# 伪代码
async def review_chapter(chapter_text, outline, materials, previous_summaries):
    # 4个审核并行执行
    results = await asyncio.gather(
        fact_checker.review(chapter_text, materials),
        continuity_checker.review(chapter_text, outline, previous_summaries),
        repetition_checker.review(chapter_text, vector_store),
        literary_checker.review(chapter_text, style_requirements)
    )

    # 合并报告
    return merge_review_reports(results)
```

### 3.2 各审核Agent职责

#### Agent 1: 事实审核 (FactChecker)
```yaml
输入: 章节全文 + 原始采访素材
检查项:
  - 时间矛盾: 章节中的时间是否与素材冲突
  - 地点矛盾: 地点描述是否与素材一致
  - 人物矛盾: 人物关系/数量是否矛盾
  - 事件矛盾: 事件顺序/细节是否矛盾
输出格式:
  passed: bool
  issues:
    - type: "time_contradiction"
      location: "第3段"
      description: "素材中1985年在广州，章节写1985年在北京"
      severity: "critical"
```

#### Agent 2: 连贯审核 (ContinuityChecker)
```yaml
输入: 章节全文 + 大纲 + 前序章节摘要
检查项:
  - 时间跳跃: 是否出现不合理的时间跳跃
  - 人物断裂: 新人物是否缺乏介绍
  - 伏笔回收: 前文伏笔是否回应
  - 章间衔接: 与前一章结尾是否连贯
输出格式:
  passed: bool
  issues:
    - type: "timeline_gap"
      description: "从1985年直接跳到1988年，缺少3年过渡"
      severity: "warning"
```

#### Agent 3: 重复审核 (RepetitionChecker)
```yaml
输入: 章节全文 + 已生成章节向量库
检查项:
  - 内容重复: 与已生成章节是否重复描述同事件
  - 车轱辘话: 同一段内是否有重复表达
  - 同义反复: 相同意思换说法重复
输出格式:
  passed: bool
  issues:
    - type: "event_duplicate"
      description: "本章第2节与第1章第3节都详细描述了同一次创业"
      severity: "major"
```

#### Agent 4: 文学审核 (LiteraryChecker)
```yaml
输入: 章节全文 + 写作风格要求
检查项:
  - 描写单薄: 场景是否缺乏感官细节
  - 对话生硬: 对话是否自然
  - 节奏问题: 段落长度是否变化、有无过度平铺
  - 情感标签: 是否存在"他很伤心"类标签，而非通过动作表现
输出格式:
  passed: bool
  issues:
    - type: "weak_description"
      location: "第5段"
      description: "1986年工厂场景缺乏视觉/听觉细节"
      suggestion: "可增加机器声音、光线、气味等描写"
      severity: "minor"
```

### 3.3 审核报告合并格式

```json
{
  "overall_passed": false,
  "round": 1,
  "dimensions": {
    "fact": {"passed": true, "issues": []},
    "continuity": {"passed": false, "issues": [...]},
    "repetition": {"passed": true, "issues": []},
    "literary": {"passed": false, "issues": [...]}
  },
  "summary_for_llm": "自然语言描述，包含：\n1. 已通过的检查\n2. 待修复的问题（带位置和建议）\n3. 优先级排序"
}
```

---

## 四、迭代修订机制

### 4.1 历史修改记录（累积式）

```python
revision_history = [
    {
        "round": 1,
        "issues_fixed": [
            {"type": "time", "from": "1985年北京", "to": "1985年广州", "status": "fixed"}
        ],
        "issues_remaining": [
            {"type": "continuity", "description": "缺少1986-1987过渡"}
        ],
        "new_issues": [],
        "word_count": 5200,
        "quality_score": 75
    },
    {
        "round": 2,
        "issues_fixed": [
            {"type": "continuity", "description": "已补充1986年内容", "status": "fixed"}
        ],
        "issues_remaining": [],
        "new_issues": [
            {"type": "literary", "description": "新增段落描写过于夸张", "status": "new"}
        ],
        "word_count": 5800,
        "quality_score": 82
    }
]
```

### 4.2 质量退化检测

```python
def detect_degradation(history, current_round):
    """
    检测修订质量是否退化
    """
    if len(history) < 2:
        return None

    last = history[-1]
    current = current_round

    # 退化信号1：质量分连续下降
    if len(history) >= 2:
        scores = [h['quality_score'] for h in history[-3:]]
        if scores == sorted(scores, reverse=True) and len(set(scores)) > 1:
            return {
                "type": "score_declining",
                "message": f"质量分连续下降: {scores}",
                "action": "ROLLBACK_BEST"
            }

    # 退化信号2：同一问题反复出现
    recurring = find_recurring_issues(history)
    if len(recurring) >= 2:
        return {
            "type": "recurring_issues",
            "message": f"问题反复出现: {recurring}",
            "action": "ROLLBACK_BEST"
        }

    # 退化信号3：新问题持续增加
    new_issues_counts = [len(h.get('new_issues', [])) for h in history[-3:]]
    if len(new_issues_counts) >= 3 and new_issues_counts == sorted(new_issues_counts):
        return {
            "type": "new_issues_increasing",
            "message": f"新问题持续增加: {new_issues_counts}",
            "action": "ROLLBACK_BEST"
        }

    return None
```

### 4.3 回滚策略

当检测到退化时：
1. 从历史版本中选择质量分最高的版本
2. 记录退化原因
3. 继续下一轮但标记"已尝试回滚"
4. 如再次退化，保留最佳版本并退出迭代

---

## 五、推断内容策略

### 5.1 推断原则

```yaml
允许推断:
  - 日常生活细节（饮食、交通、居住环境）
  - 时代背景填充（政策、社会风气、常见职业）
  - 符合人设的平淡事件（"平淡期"的日常经营）

禁止推断:
  - 强烈情感事件（恋爱、离婚、重大冲突）
  - 道德敏感事件（违法、背叛、丑闻）
  - 重大决策原因（除非素材明确说明）

推断边界:
  - 不能与前序/后续已知事实矛盾
  - 不能改变人物基本性格
  - 平淡但不无聊，服务于叙事连贯
```

### 5.2 推断标注格式

```markdown
1986年到1988年间，陈国伟的工厂度过了相对平稳的两年。※
这段时间珠三角的制造业正蓬勃发展，像他这样的小作坊
主大多忙于应付订单，生活规律而单调。※

---
※ 推断依据：
1. 素材中1985年创业，1990年提到"已稳定"，中间年份无记录
2. 根据时代背景，1986-1988年珠三角制造业确实处于上升期
3. 主人公性格务实，推断其专注经营而非冒险扩张
```

---

## 六、输出规范

### 6.1 分章节输出

```
output/
├── biography_full.txt          # 完整整合版
├── chapters/
│   ├── 01_南海出生_匮乏年代的啼哭.txt
│   ├── 02_南风窗打开了.txt
│   ├── 03_闯深圳与第一桶金.txt
│   ├── 04_危机与转型.txt
│   └── 05_知天命.txt
├── appendix/
│   └── inferred_content_notes.txt  # 推断内容说明
└── meta/
    ├── outline.json              # 最终大纲
    ├── material_evaluation.json  # 素材评估报告
    └── generation_log.jsonl      # 生成日志
```

### 6.2 章节文件格式

```txt
第一章 南海出生：匮乏年代的啼哭
时间跨度：1965-1978
本章字数：18500字
推断内容比例：15%（约2700字）

============================================================

第一节 蛇年降生在河边

1965年的南海县...

[正文内容]

※ 本节推断内容：
- 第3段：1966年家庭生活细节（基于时代背景推断）
- 第7段：童年玩伴描述（合理推断）

============================================================

第二节 偷甘蔗与父亲的沉默

...
```

---

## 七、关键设计决策总结

| 决策点 | 选择 | 原因 |
|--------|------|------|
| Thinking使用 | 生成/评估/修订用，审核不用 | 创造性任务需要推理，判断任务不需要 |
| 审核并行度 | 4个Agent并行 | 检查维度独立，无依赖关系 |
| 迭代终止条件 | 5轮或退化检测 | 平衡质量与成本 |
| 上下文策略 | 滑动窗口 | 避免上下文溢出，保留必要信息 |
| 推断内容风格 | 平淡、符合人设 | 避免违和感，服务于叙事连贯 |
| 大纲审核 | 有 | 防止结构性问题后期难以修正 |
| 质量退化处理 | 回滚最佳版本 | 避免越改越差 |

---

## 八、待确认问题

1. **大纲审核不通过时的处理**：是直接重新生成（自动），还是调整参数后生成？
2. **章节审核维度优先级**：如果事实性通过但文学性不通过，是否允许降级输出（如标记为"初稿需润色"）？
3. **推断比例上限**：是否设定单章节推断内容的上限（如不超过30%）？
4. **向量存储**：重复审核需要向量库，使用内存ChromaDB还是持久化存储？
