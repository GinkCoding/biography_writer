# 为什么即使给了完整上下文，LLM 还是会出现一致性问题

## 你的措施（已实施的）

```
生成阶段：
├── 输入：大纲 + 之前所有章节梗概 + 本章要点
├── LLM 生成本章内容
└── 保存

审核阶段：
├── 输入：完整全文(12章, 5万字) + 采访稿(3万字) + 审核指令
├── LLM 输出审核报告
└── 人工/自动修复
```

**理论上这应该足够，但实践中失效了。**

---

## 根本原因：LLM 的根本局限

### 1. 注意力衰减（The Lost in the Middle Problem）

**研究证据**：
- 论文《Lost in the Middle: How Language Models Use Long Contexts》(2023)
- 发现：LLM 对长上下文中间部分的信息召回率显著下降

**在你的场景中的表现**：
```
第11章生成时的输入：
┌──────────────────────────────────────────────────────────────┐
│  大纲(前面)                                                  │
│  第1章梗概                                                   │
│  第2章梗概                                                   │
│  ...                                                         │
│  第7章梗概  ← 妻子叫"秀芳"（关键信息在上下文中间）           │
│  ...                                                         │
│  第10章梗概                                                  │
│  【本章要点：妻子支持创业】                                    │ ← 提示词强调不够具体
└──────────────────────────────────────────────────────────────┘
          ↓
LLM 的注意力分布：
    强          弱          强
    ↑           ↓           ↑
  开头        中间        结尾
```

**结果**：生成第11章时，LLM 忘记了第7章的具体人名，根据"本章要点：妻子支持创业"自行发挥了"林晓芸"这个名字。

---

### 2. 生成时的"创造性漂移"（Generative Drift）

**LLM 的本质**：不是数据库查询，而是概率补全。

```python
# 第7章的 prompt 片段
"""前文：妻子秀芳..."""
# → LLM 学习到：妻子=秀芳

# 第11章的 prompt 片段  
"""妻子[MASK]慌张地跑进办公室"""
# → LLM 计算概率：
#    "秀芳": 0.15  （记忆中模糊）
#    "晓芸": 0.12  （训练数据常见组合）
#    "她": 0.20    （通用代词）
#    "林晓芸": 0.18 （训练数据中"妻子林XX"常见模式）
# 
# 当 "秀芳" 在上下文中的信号不够强时，
# LLM 会选择概率上"合理"的名字，而非"正确"的名字
```

**关键点**：LLM 不"知道"妻子的名字是固定的，它只是在生成"合理的下一个token"

---

### 3. 审核阶段的"确认偏误"（Confirmation Bias）

**你要求的终审 prompt 可能是这样**：
```
"请审核以下内容是否有问题：
[全文5万字]
[采访稿3万字]"
```

**LLM 审核时的问题**：

| 问题 | LLM 的"思维过程" | 结果 |
|------|------------------|------|
| 姓名不一致 | "第7章的妻子叫秀芳，第11章叫林晓芸...这可能是昵称？可能是笔名？可能是不同人？" | 未标记 |
| AI痕迹 | "'主旨运用：'这句话...可能是作者风格？可能是注释？" | 未标记 |
| 时间线矛盾 | "1992年有孩子...但创业艰辛...这听起来合理，很多家庭都这样" | 合理化矛盾 |

**根本问题**：
- LLM 审核是**开放式阅读**，没有**结构化核对清单**
- LLM 倾向于"合理化"文本，而非"挑刺"
- 8万字同时输入，信息过载导致审核流于表面

---

### 4. 缺乏强制约束机制（No Hard Constraints）

**当前系统的 soft prompt**：
```
"请遵循大纲，保持与之前章节一致"
```

**需要的 hard constraints**：
```python
# 生成前强制注入
MUST_USE_NAMES = {
    "妻子": "秀芳",
    "大儿子": "陈昊",
    "二儿子": "陈...",
}

# 生成后强制校验
def enforce_character_names(content: str) -> str:
    for role, name in MUST_USE_NAMES.items():
        # 如果检测到其他名字，强制替换或报错
        ...
```

**当前缺失**：系统只"建议"LLM保持一致，没有"强制"一致性。

---

## 具体案例分析

### 案例1：秀芳→林晓芸

**时间线**：
```
第7章：输入梗概包含"秀芳"
      ↓ 生成
      输出：妻子叫"秀芳" ✓
      
第8章：输入梗概包含"秀芳"  
      ↓ 生成
      输出：妻子叫"秀芳" ✓
      
...（中间6章没有妻子名字）...

第11章：输入梗概只写"妻子支持"，没有明确写"秀芳"
      ↓ 生成
      梗概中的"妻子" → LLM 补全为"林晓芸" ✗
```

**关键发现**：
- 不是 LLM"忘记"了，而是**梗概本身在第11章可能没有明确提及人名**
- 即使有，注意力衰减导致信号弱
- 没有全局的"人物姓名表"强制注入

### 案例2：AI指令残留

**发生的场景**：
```
用户 prompt：
"请生成第11章，注意体现'迁徙与重生'的主题..."

LLM 的 CoT（思维链）：
1. 用户要我体现"迁徙与重生"主题
2. 我应该让卡车象征战场
3. 写入："主旨运用：搬迁的卡车..."
4. 继续生成正文...

输出结果：
"主旨运用：搬迁的卡车，载着机器驶向新的战场。陈国的工厂在夕阳下..."
```

**为什么 ContentCleaner 没抓到？**
```python
# 你的规则
r'【[^】]*(?:修改说明|AI|重写|润色)[^】]*】'  # 只匹配【】内的

# 实际的残留
"主旨运用：搬迁的卡车..."  # 没有【】，是正文格式
```

**为什么终审没抓到？**
```
LLM 审核思维：
"这句话看起来像是叙述的一部分...也许是作者的文学手法？
 不是明显的AI痕迹，不标记了。"
```

### 案例3：子女时间线矛盾

**矛盾点**：
```
事实A：第12章说2018年陈昊26岁 → 1992年出生
事实B：第7章说1992年在铁皮房艰苦创业，没有孩子
```

**为什么 LLM 没发现矛盾？**

1. **信息分散在不同章节**：
   - 陈昊的年龄在第12章
   - 创业艰辛在第7章
   - 两章相距5章，上下文窗口需要包含12章才能对比

2. **缺乏显式推理要求**：
   ```
   你的审核 prompt："请检查是否有矛盾"
   
   需要的审核 prompt：
   """请按以下步骤检查：
   1. 列出所有人物及其出生年份
   2. 列出所有事件及其发生年份
   3. 交叉验证：事件发生时人物的年龄是否合理
   4. 特别关注：创业关键期(1992-1995)是否有孩子
   """
   ```

3. **LLM 不会主动做复杂推理**：
   - 除非你显式要求"列出所有时间并对比"
   - 否则 LLM 只是"通读"，不会"计算"

---

## 解决方案：从"建议"到"强制"

### 方案1：硬约束的人物姓名系统

```python
class EnforcedCharacterRegistry:
    """强制人物注册表 - 不允许LLM自由发挥"""
    
    def inject_to_prompt(self, chapter_outline: str) -> str:
        """在prompt中强制注入人物姓名表"""
        return f"""
【人物姓名表 - 必须严格遵守】
以下人物的姓名已经确定，全文必须使用这些名字，不得更改：
{self.format_character_list()}

【生成规则】
1. 必须使用上表中的确切姓名
2. 禁止创造新的人物姓名
3. 如果不知道如何称呼某人，使用"他"/"她"或描述性称呼

违反以上规则会导致内容被废弃。

---
{chapter_outline}
"""
```

### 方案2：生成后硬性校验

```python
async def generate_chapter_with_enforcement(...) -> Chapter:
    # 第一次生成
    content = await llm.generate(prompt)
    
    # 硬性校验
    validator = HardConstraintValidator(registry)
    violations = validator.check(content)
    
    if violations:
        # 自动修复或重新生成
        fixed_content = await auto_fix(content, violations)
        return fixed_content
    
    return content
```

### 方案3：结构化终审（而非开放式阅读）

```python
async def structured_final_review(book: BiographyBook) -> ReviewReport:
    """结构化终审 - 分步骤强制检查"""
    
    # 步骤1：提取所有事实（强制LLM结构化输出）
    facts = await llm.extract_facts(book, schema={
        "characters": [{"name": str, "first_appearance": int}],
        "events": [{"description": str, "year": int, "characters_involved": [str]}],
        "timeline": [{"chapter": int, "time_period": str}]
    })
    
    # 步骤2：基于提取的事实做逻辑验证（代码层面，不依赖LLM）
    contradictions = []
    
    # 检查姓名一致性
    name_variations = find_similar_names(facts.characters)
    if name_variations:
        contradictions.append(NameInconsistency(name_variations))
    
    # 检查时间线一致性
    for char in facts.characters:
        if char.name == "陈昊":
            birth_year = infer_birth_year(char, facts.events)
            for event in facts.events:
                if "创业" in event.description and event.year == birth_year:
                    if "带孩子" not in event.description:
                        contradictions.append(TimelineContradiction(
                            f"陈昊出生于{birth_year}年，"
                            f"但第{event.chapter}章创业艰辛中未提及抚养婴儿"
                        ))
    
    return ReviewReport(contradictions=contradictions)
```

---

## 总结：为什么你的措施不够

| 你的措施 | 预期效果 | 实际效果 | 为什么失效 |
|---------|---------|---------|-----------|
| 给大纲+梗概 | LLM记住所有设定 | 只记住开头和结尾 | Lost in the middle |
| 开放式终审 | LLM发现所有问题 | 只发现明显问题 | Confirmation bias + 信息过载 |
| 提示"保持一致" | LLM自觉遵守 | LLM自行发挥 | LLM是概率模型，非规则引擎 |

**核心结论**：
> LLM 擅长"生成合理的文本"，但不擅长"严格遵守约束"。
> 
> 需要把"约束"从 prompt 中拿出来，放到代码层面的强制校验中。

**关键转变**：
```
从：依赖 LLM 的记忆和自律
到：代码层强制 + LLM 生成
```
