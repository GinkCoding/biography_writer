# 传记生成质量问题深度分析

## 问题概述

| 问题 | 严重程度 | 类型 | 当前系统为何漏检 |
|------|---------|------|----------------|
| 妻子姓名不一致（秀芳→林晓芸） | 🔴 致命 | 全局一致性 | 逐章生成+缺乏人物档案追踪 |
| AI指令残留（"主旨运用："） | 🟡 严重 | 元数据清理 | 规则覆盖不全，非标准占位符 |
| 子女时间线矛盾 | 🔴 致命 | 逻辑一致性 | 缺乏因果推理和时序验证 |

---

## 根本原因分析

### 1. 妻子姓名不一致（秀芳 vs 林晓芸）

**为什么发生？**
```
逐章生成流程的问题：
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  第7章生成   │ → │  第8章生成   │ → │  第11章生成  │
│  妻子=秀芳   │    │  妻子=秀芳   │    │  妻子=林晓芸 │ ← LLM遗忘/幻觉
└─────────────┘    └─────────────┘    └─────────────┘
         ↑                              ↑
    上下文窗口包含                   上下文窗口丢失早期信息
    前几章内容                        或提示词强调不足
```

**现有系统为何漏检？**
- `EventTracker` 只追踪"事件"，不追踪"人物属性"
- `ReviewOutputLayer` 逐章审校，不对比跨章节的角色一致性
- 缺乏"人物档案表"的全局锁定机制

**这是小说创作中最严重的问题类型** - 主角改名等于推翻全书基础。

---

### 2. AI指令残留（"主旨运用："）

**为什么发生？**
```python
# ContentCleaner 当前规则
RULES = [
    (r'【[^】]*(?:修改说明|AI|重写|润色)[^】]*】', ''),  # 只匹配【】内
    (r'.*待补充.*', ''),  # 只匹配"待补充"
]
```

漏检原因：
- `"主旨运用："` 不在现有正则规则中
- 这是**指令性语言**而非元数据标记
- LLM可能在生成时混淆了"提示词大纲"和"正文"

**现有系统为何漏检？**
- 基于正则的清理是**白名单思维**，无法穷尽所有AI痕迹
- 没有**语义级**的AI痕迹检测

---

### 3. 子女时间线矛盾

**矛盾细节：**
```
第12章说: 2018年陈昊26岁 → 出生于1992年
第7-8章说: 1992-1993年在宝安租铁皮房艰苦创业

问题：如果92年有婴儿，为何全文不提抚养艰辛？
      为何创业描写只有"通宵刮毛边"而没有"照顾婴儿"？
```

**为什么发生？**
1. **大纲粒度不够细**：大纲只规定"第7章讲创业"，没规定"此时是否有孩子"
2. **逐章独立生成**：每章只检查"本章内容是否符合素材"，不检查"本章设定是否与全书一致"
3. **缺乏时间线验证器**：没有系统检查"事件A发生时，人物B的年龄/状态应该是什么"

**现有系统为何漏检？**
- `Timeline` 只记录事件顺序，不做因果推理
- `FinalReview` 检查"跨章节重复"，但不检查"跨章节因果一致性"

---

## 系统性解决方案

### 方案一：全局人物档案锁定（解决姓名不一致）

```python
class CharacterRegistry:
    """人物注册表 - 全局唯一真相源"""
    
    def __init__(self):
        self.characters: Dict[str, CharacterProfile] = {}
        self.locked_attributes: Set[str] = set()  # 锁定后不可更改
    
    def register(self, char_id: str, name: str, **attrs):
        """首次出现时注册，之后不可更改"""
        if char_id in self.characters:
            # 检查一致性
            existing = self.characters[char_id]
            if existing.name != name:
                raise ConsistencyError(
                    f"人物姓名冲突: {char_id} 在第X章叫'{existing.name}', "
                    f"在第Y章叫'{name}'"
                )
        else:
            self.characters[char_id] = CharacterProfile(
                id=char_id, name=name, **attrs
            )
            self.locked_attributes.add(f"{char_id}.name")
```

**集成点：**
- 在 `KnowledgeMemoryLayer` 中提取人物信息时强制注册
- 在 `generation_layer.generate_chapter()` 前注入人物档案到 prompt

---

### 方案二：语义级AI痕迹检测（解决指令残留）

```python
class AISemanticDetector:
    """基于LLM的AI痕迹语义检测"""
    
    PROMPT = """请判断以下文本是否含有AI创作痕迹或提示词残留：

待检测文本：
{text}

检查清单：
1. 是否含有创作指导类语言（如"主旨运用"、"象征意义"、"体现...精神"）
2. 是否含有元叙事内容（如"本章描写了..."、"通过...展现..."）
3. 是否含有未完成的占位符或标记
4. 是否含有括号内的创作说明
5. 是否像在"分析"而非"叙述"故事

输出：如果发现问题，输出 "[AI痕迹] 具体位置和问题"
      如果没有问题，输出 "通过""""
    
    async def detect(self, content: str) -> List[AIDetectionResult]:
        result = await self.llm.complete(self.PROMPT.format(text=content[:2000]))
        return self._parse_results(result)
```

**优势：**
- 不依赖正则规则，可检测未知模式的AI痕迹
- 利用LLM自身的"自我识别"能力

---

### 方案三：时间线因果验证器（解决逻辑矛盾）

```python
class TimelineConsistencyValidator:
    """时间线一致性验证器"""
    
    def validate_character_timeline(self, character: str, book: BiographyBook) -> List[ConsistencyError]:
        """
        验证人物时间线一致性
        
        例如：检查"孩子的年龄"与"父母的创业阶段"是否矛盾
        """
        errors = []
        
        # 收集人物在各章节的设定
        appearances = []
        for ch in book.chapters:
            # 提取该章节中人物的状态
            state = self._extract_character_state(ch, character)
            if state:
                appearances.append({
                    'chapter': ch.order,
                    'time_period': ch.time_period,
                    'age': state.get('age'),
                    'life_stage': state.get('life_stage'),
                    'mentioned_events': state.get('events', [])
                })
        
        # 检查一致性
        for i in range(len(appearances) - 1):
            curr, next_app = appearances[i], appearances[i + 1]
            
            # 检查年龄连续性
            if curr['age'] and next_app['age']:
                time_gap = self._estimate_years(curr['time_period'], next_app['time_period'])
                expected_age = curr['age'] + time_gap
                if abs(next_app['age'] - expected_age) > 1:
                    errors.append(ConsistencyError(
                        f"第{curr['chapter']}章说{character} {curr['age']}岁，"
                        f"第{next_app['chapter']}章说{next_app['age']}岁，"
                        f"时间跨度{time_gap}年，应为{expected_age}岁"
                    ))
            
            # 检查人生阶段一致性
            if '婴儿' in curr['life_stage'] and '创业' in curr['mentioned_events']:
                if '抚养' not in curr['mentioned_events']:
                    errors.append(ConsistencyError(
                        f"第{curr['chapter']}章：{character}是婴儿，"
                        f"但创业艰辛描写中未提及抚养孩子的困难"
                    ))
        
        return errors
```

---

### 方案四：增强型跨章节审校

当前系统只检查"是否重复"，需要增加：

```python
class CrossChapterReview:
    """跨章节一致性审校"""
    
    async def review(self, book: BiographyBook) -> ReviewReport:
        checks = [
            self._check_character_consistency(),      # 人物一致性
            self._check_timeline_consistency(),       # 时间线一致性
            self._check_event_uniqueness(),           # 事件去重（已有）
            self._check_narrative_voice(),            # 叙述口吻一致性
            self._check_geographical_consistency(),   # 地理信息一致性
        ]
        
        for check in checks:
            errors = await check(book)
            if errors:
                report.add_issues(errors)
        
        return report
```

---

## 立即可实施的快速修复

在实现上述系统方案前，可以立即添加的简单验证：

### 1. 人物姓名白名单检查
```python
# 在 generate_book 的章节循环中添加
if self.event_tracker:  # 复用 event_tracker 存储人物
    # 提取本章出现的人名
    names_in_chapter = extract_names(chapter.content)
    for name in names_in_chapter:
        if self.event_tracker.is_character(name):
            canonical_name = self.event_tracker.get_canonical_name(name)
            if canonical_name != name:
                logger.error(f"⚠️ 人物姓名不一致: '{name}' 应为 '{canonical_name}'")
```

### 2. AI痕迹关键词扩展
```python
# 扩展 ContentCleaner.RULES
ADDITIONAL_AI_MARKERS = [
    r'主旨运用[：:]',
    r'象征意义[：:]',
    r'体现了.*精神',
    r'通过.*展现.*',
    r'本章描写[了的是]',
]
```

### 3. 强制性的全文终审
```python
# 在 _perform_final_review_and_revision 中增加
async def _deep_consistency_check(self, book: BiographyBook):
    """深度一致性检查"""
    
    # 1. 提取所有人物及其出现章节
    character_mentions = {}
    for ch in book.chapters:
        for para in ch.content.split('\n'):
            # 简单的中文人名检测（2-4字，常见姓氏）
            names = extract_chinese_names(para)
            for name in names:
                if name not in character_mentions:
                    character_mentions[name] = []
                character_mentions[name].append(ch.order)
    
    # 2. 检测相似姓名（可能的拼写不一致）
    for name1, chaps1 in character_mentions.items():
        for name2, chaps2 in character_mentions.items():
            if name1 != name2 and similar_names(name1, name2):
                logger.warning(
                    f"⚠️ 发现相似姓名: '{name1}'(第{chaps1}章) vs "
                    f"'{name2}'(第{chaps2}章)，可能是同一人"
                )
```

---

## 总结：为什么当前系统失效

| 层级 | 当前机制 | 失效原因 |
|------|---------|---------|
| 生成层 | 逐章生成，上下文窗口有限 | 人物信息在11章后被遗忘/混淆 |
| 清理层 | 正则匹配特定模式 | 无法穷举所有AI痕迹变体 |
| 审校层 | 逐章审校，检查本章质量 | 不检查跨章节一致性 |
| 终审层 | 简单重复检测 | 不做因果推理和时间线验证 |

**核心问题**：系统缺乏**全局一致性保证机制**，每章都是"独立优化"而非"全局协调"。

需要的架构升级：
```
当前: [逐章生成] → [逐章审校] → [简单的全书终审]
         ↓
目标: [全局规划] → [逐章生成(受约束)] → [全局一致性验证] → [修订]
           ↑                                    ↓
           └──────── [全局知识图谱] ←──────────┘
```
