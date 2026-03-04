"""
人物关系分析器 - 用LLM理解复杂的人物关系动态

取代硬编码状态机，使用LLM理解：
- 关系变化的微妙之处（"大吵但未决裂" vs "彻底断绝"）
- 情感的层次（"表面和解但心存芥蒂"）
- 互动的边界（哪些行为在哪种关系下是合理的）
"""
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class RelationshipAnalysis:
    """LLM对人物关系的分析结果"""
    person_name: str
    chapter: int

    # 物理状态（客观事实）
    physical_status: str  # "alive" | "deceased"

    # 关系动态（主观理解，可多维度）
    interaction_level: str  # "full" | "limited" | "none" - 互动程度
    emotional_tone: str  # "warm" | "neutral" | "cold" | "hostile" - 情感基调
    relationship_state: str  # 自由描述，如"表面和解但内心隔阂"、"冷战期"等

    # 具体限制
    can_direct_interaction: bool  # 能否直接互动（说话、在场）
    can_be_remembered: bool  # 能否被回忆/提及
    can_appear_in_memory: bool  # 能否在回忆场景中出现

    # 使用建议
    appropriate_usage: str  # 自由文本，如"可以提及但不宜描写亲密互动"
    inappropriate_usage: str  # 自由文本，如"不应描写父亲对传主说话"

    # 推理过程（让审核Agent可以理解判断依据）
    reasoning: str


class PersonRelationshipAnalyzer:
    """使用LLM分析人物关系的分析器"""

    def __init__(self, llm):
        self.llm = llm

    async def analyze_relationship(
        self,
        person_name: str,
        chapter: int,
        relationship_history: List[Dict],
        physical_status: str,
        death_chapter: Optional[int],
        current_content: str
    ) -> RelationshipAnalysis:
        """
        分析人物在指定章节的关系状态

        Args:
            person_name: 人物姓名
            chapter: 当前章节
            relationship_history: 之前所有章节的关系线索
            physical_status: 物理状态（alive/deceased）
            death_chapter: 如去世，记录章节
            current_content: 当前章节内容（用于理解上下文）

        Returns:
            RelationshipAnalysis 对象
        """

        # 构建关系历史文本
        history_text = "\n".join([
            f"第{c['chapter']}章: [{c['type']}] {c['description']}"
            for c in sorted(relationship_history, key=lambda x: x['chapter'])
        ]) if relationship_history else "此前无显著关系事件记录"

        # 物理状态说明
        physical_desc = "在世"
        if physical_status == "deceased" and death_chapter:
            physical_desc = f"已于第{death_chapter}章去世"
        elif physical_status == "deceased":
            physical_desc = "已去世"

        prompt = f"""你是一位资深的人物关系分析师。请分析传记中人物"{person_name}"在第{chapter}章的关系状态。

【人物物理状态】
{physical_desc}

【关系历史】（按时间顺序）
{history_text}

【当前章节片段】
{current_content[:1500]}...

【分析任务】
请根据关系历史，判断在第{chapter}章中，该人物与传主的关系状态。

注意：
1. 关系是复杂的，不只是"好/坏"或"在/不在"
2. 可能有"大吵一架但没决裂"、"表面和解但心存芥蒂"、"渐行渐远但未断交"等微妙状态
3. 去世人物也可以有不同方式的出现（回忆、提及、想象）

【输出格式】
请输出JSON：
{{
    "physical_status": "alive 或 deceased",
    "interaction_level": "full(可正常互动) / limited(有限互动) / none(无互动)",
    "emotional_tone": "warm(温暖) / neutral(中性) / cold(冷淡) / hostile(敌对)",
    "relationship_state": "一句话描述关系状态，如'大吵后冷战期，但未正式决裂'、'表面和解但内心仍有隔阂'",
    "can_direct_interaction": true/false,
    "can_be_remembered": true/false,
    "can_appear_in_memory": true/false,
    "appropriate_usage": "建议使用方式，如'可以提及往事，可以写传主想起父亲，但不宜描写父亲直接对传主说话'",
    "inappropriate_usage": "不建议的使用方式，如'不要写父亲在场并与传主对话，不要写亲密的父子互动'",
    "reasoning": "分析推理过程，解释为什么做出上述判断，引用具体的历史线索"
}}

示例判断：
- 如果父亲第1章去世：can_direct_interaction=false, can_be_remembered=true, relationship_state="已去世，仅存于回忆"
- 如果第2章大吵一架但未断绝：can_direct_interaction=true, emotional_tone="hostile", relationship_state="激烈冲突后的紧张期"
- 如果第3章"断绝关系"：can_direct_interaction=false, relationship_state="已正式断绝父子关系"
- 如果第4章"他想起了父亲"：这是合理的回忆，不违反任何限制"""

        try:
            response = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500,
                timeout=120
            )

            result = json.loads(response)

            return RelationshipAnalysis(
                person_name=person_name,
                chapter=chapter,
                physical_status=result.get("physical_status", physical_status),
                interaction_level=result.get("interaction_level", "full"),
                emotional_tone=result.get("emotional_tone", "neutral"),
                relationship_state=result.get("relationship_state", "关系正常"),
                can_direct_interaction=result.get("can_direct_interaction", True),
                can_be_remembered=result.get("can_be_remembered", True),
                can_appear_in_memory=result.get("can_appear_in_memory", True),
                appropriate_usage=result.get("appropriate_usage", ""),
                inappropriate_usage=result.get("inappropriate_usage", ""),
                reasoning=result.get("reasoning", "")
            )

        except Exception as e:
            # 失败时返回保守估计（允许大部分操作，但标记为不确定）
            return RelationshipAnalysis(
                person_name=person_name,
                chapter=chapter,
                physical_status=physical_status,
                interaction_level="unknown",
                emotional_tone="neutral",
                relationship_state="关系状态分析失败，请人工检查",
                can_direct_interaction=physical_status != "deceased",
                can_be_remembered=True,
                can_appear_in_memory=True,
                appropriate_usage="请根据上下文判断",
                inappropriate_usage="请根据上下文判断",
                reasoning=f"分析过程出错: {e}"
            )

    async def check_content_consistency(
        self,
        content: str,
        chapter: int,
        analyses: Dict[str, RelationshipAnalysis]
    ) -> List[Dict]:
        """
        检查内容与关系分析是否一致

        Returns:
            发现的不一致问题列表
        """
        if not analyses:
            return []

        # 构建分析摘要
        analysis_summary = "\n\n".join([
            f"【{name}】\n"
            f"状态: {a.relationship_state}\n"
            f"能否直接互动: {'是' if a.can_direct_interaction else '否'}\n"
            f"能否回忆: {'是' if a.can_be_remembered else '否'}\n"
            f"建议使用: {a.appropriate_usage}\n"
            f"不建议使用: {a.inappropriate_usage}"
            for name, a in analyses.items()
        ])

        prompt = f"""你是一位严格的内容一致性审核员。请检查以下章节内容是否符合人物关系限制。

【当前章节内容】
{content[:3000]}
...

【人物关系限制】
{analysis_summary}

【审核任务】
检查内容中是否有违反关系限制的地方：
1. 已去世/不能互动的人物是否进行了直接对话或互动？
2. 已决裂的人物是否被描写得过于亲密？
3. 关系冷淡期是否被描写得过于热情？

注意区分：
- 回忆/想起：✅ 通常是允许的（除非analysis明确禁止）
- 直接互动/对话：❌ 如果can_direct_interaction=false

【输出格式】
JSON数组，每个问题一个对象：
[
    {{
        "type": "interaction_violation / tone_mismatch / other",
        "location": "具体位置，如'第3段第2行'",
        "description": "具体问题描述",
        "current_text": "当前有问题的文本",
        "suggested_fix": "建议如何修改",
        "severity": "critical / major / minor"
    }}
]

如果没有问题，返回空数组 []"""

        try:
            response = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2000,
                timeout=120
            )

            return json.loads(response)

        except Exception as e:
            return [{"error": f"一致性检查失败: {e}"}]
