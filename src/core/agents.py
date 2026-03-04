"""
审核Agent实现 - 4个专项审核 + 质量选择器
"""
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


@dataclass
class DimensionReview:
    """单维度审核结果"""
    passed: bool
    issues: List[Dict] = field(default_factory=list)
    score: int = 0  # 0-100
    suggestions: List[str] = field(default_factory=list)


class FactChecker:
    """事实审核Agent - 检查与原始素材的矛盾"""

    def __init__(self, llm, facts_db=None):
        self.llm = llm
        self.facts_db = facts_db

    async def review(self, content: str, material: str, chapter_context: Any) -> DimensionReview:
        """
        审核内容中的事实是否与原始素材一致
        """
        prompt = f"""你是一位严格的事实核查编辑。请仔细比对章节内容和原始采访素材，找出所有事实矛盾。

【审核原则】
1. 时间矛盾：章节中的年份、日期是否与素材一致
2. 地点矛盾：地点描述是否与素材矛盾
3. 人物矛盾：人物姓名、关系、数量是否矛盾
4. 事件矛盾：事件顺序、细节、结果是否矛盾
5. 数字矛盾：年龄、金额、数量等数字是否矛盾

【原始采访素材】
{material[:8000]}
...
[素材共{len(material)}字]

【待审核章节】
{content[:10000]}
...
[章节共{len(content)}字]

【输出要求】
请输出JSON格式：
{{
    "passed": false,
    "issues": [
        {{
            "type": "time_contradiction",
            "location": "第3段第2行",
            "chapter_content": "1985年他在北京",
            "material_content": "1985年我在广州",
            "severity": "critical"
        }}
    ],
    "score": 85,
    "suggestions": ["建议修改为广州"]
}}

注意：
- 只有明确矛盾才报问题，不要过度敏感
- location要具体到段落
- severity分为: critical（必须改）、major（应该改）、minor（可改可不改）
- 如果没有问题，passed为true，issues为空数组"""

        try:
            response = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=3000,
                timeout=60
            )

            result = json.loads(response)
            return DimensionReview(
                passed=result.get("passed", False),
                issues=result.get("issues", []),
                score=result.get("score", 0),
                suggestions=result.get("suggestions", [])
            )
        except Exception as e:
            return DimensionReview(
                passed=False,
                issues=[{"error": f"审核异常: {e}"}],
                score=0
            )


class ContinuityChecker:
    """连贯审核Agent - 检查时间线、章间衔接"""

    def __init__(self, llm, facts_db=None):
        self.llm = llm
        self.facts_db = facts_db

    async def review(self, content: str, chapter_context: Any, previous_summaries: List[str],
                     chapter_num: int = 0, facts_db: Any = None,
                     relationship_analyses: Optional[Dict] = None) -> DimensionReview:
        """
        审核章节内部和与前一章的连贯性

        Args:
            content: 章节内容
            chapter_context: 章节大纲信息
            previous_summaries: 前序章节摘要
            chapter_num: 当前章节编号
            facts_db: 事实数据库（检查人物状态）
        """
        prev_text = "\n".join(previous_summaries) if previous_summaries else "本章为第一章"

        # 构建人物关系信息（优先使用LLM分析结果，否则使用facts_db原始数据）
        person_relationship_info = ""

        if relationship_analyses:
            # 使用LLM分析的关系结果（更智能、更 nuanced）
            person_relationship_info = "\n【人物关系分析（由LLM理解）】\n"
            for name, analysis in relationship_analyses.items():
                person_relationship_info += f"\n  【{name}】\n"
                person_relationship_info += f"    状态: {analysis.relationship_state}\n"
                person_relationship_info += f"    互动: {'可直接互动' if analysis.can_direct_interaction else '不宜直接互动'}\n"
                person_relationship_info += f"    回忆: {'可以回忆提及' if analysis.can_be_remembered else '不宜回忆提及'}\n"
                if analysis.appropriate_usage:
                    person_relationship_info += f"    建议: {analysis.appropriate_usage}\n"
                if analysis.inappropriate_usage:
                    person_relationship_info += f"    避免: {analysis.inappropriate_usage}\n"
                if analysis.reasoning:
                    person_relationship_info += f"    依据: {analysis.reasoning[:100]}...\n"

        elif facts_db and chapter_num > 0:
            # 回退：使用原始线索（没有LLM分析时）
            person_relationship_info = "\n【人物关系线索（代码提取，供参考）】\n"
            for name in facts_db.persons:
                usage = facts_db.check_person_usage(name, chapter_num)
                if usage["relationship_history"] != "无显著关系变化记录":
                    person_relationship_info += f"\n  【{name}】\n"
                    person_relationship_info += f"    物理状态: {'已故' if usage['physical_status'] == 'deceased' else '在世'}\n"
                    person_relationship_info += f"    关系历史:\n{usage['relationship_history']}\n"

        prompt = f"""你是一位专业的叙事连贯性编辑。请审核以下章节的连贯性。

【前序章节摘要】
{prev_text}
{person_relationship_info}

【当前章节】
{content}

【审核维度】
1. 章间衔接：
   - 当前章节开头是否自然承接前序章节
   - 时间线是否连续（或合理跳跃）
   - 人物关系状态是否一致（根据上述关系分析）

2. 章内连贯：
   - 时间线是否清晰（无混乱的时间跳跃）
   - 段落间逻辑是否顺畅
   - 新出现的人物/地点是否有交代

3. 逻辑错误检查（结合关系分析）：

   critical（必须修复）：
   - 违反关系分析中的限制（如不宜互动的人物进行了直接对话）
   - 时间线严重矛盾（如年龄倒退）

   major（应该修复）：
   - 人物互动方式与关系状态不符（如冷淡期写热情互动）
   - 关系变化缺乏过渡

4. 情感表达质量：
   - 人物互动是否符合当前关系状态
   - 回忆与现实的比例是否恰当

【输出要求】
JSON格式：
{{
    "passed": true,
    "issues": [
        {{
            "type": "logic_error",
            "location": "第3段",
            "description": "父亲在第1章已去世，但本段直接对话'父亲说：你要好好工作'（去世后不应再说话）",
            "severity": "critical",
            "suggestion": "改为回忆形式：'他想起父亲生前常说的那句话：你要好好工作'"
        }},
        {{
            "type": "continuity_issue",
            "location": "第5段",
            "description": "提到父亲时未说明是回忆，可能造成读者困惑",
            "severity": "major",
            "suggestion": "增加过渡，如'看着这张照片，他不禁想起父亲'"
        }}
    ],
    "score": 90,
    "suggestions": ["建议明确区分现实与回忆的界限"]
}}

判断标准：
- 回忆/怀念已故人物是正常情感表达，不应禁止
- 只有让已故人物"复活"参与现实互动才是逻辑错误
- 注意语气：回忆应该是传主的内心活动或叙述，而非人物的实时表现"""

        try:
            response = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=3000,
                timeout=60
            )

            result = json.loads(response)
            return DimensionReview(
                passed=result.get("passed", False),
                issues=result.get("issues", []),
                score=result.get("score", 0),
                suggestions=result.get("suggestions", [])
            )
        except Exception as e:
            return DimensionReview(
                passed=False,
                issues=[{"error": f"审核异常: {e}"}],
                score=0
            )


class RepetitionChecker:
    """重复审核Agent - 检查内容重复和车轱辘话"""

    def __init__(self, llm, vector_store=None):
        self.llm = llm
        self.vector_store = vector_store

    async def review(self, content: str, chapter_num: int = None) -> DimensionReview:
        """
        审核内容是否重复或与之前章节重复

        Args:
            content: 当前章节内容
            chapter_num: 当前章节编号（用于排除自身）
        """
        # 使用向量存储计算相似度
        similar_chapters = []
        if self.vector_store:
            similar_chapters = self.vector_store.find_similar_chapters(content, threshold=0.6)
            # 排除自身
            similar_chapters = [ch for ch in similar_chapters if ch['chapter_num'] != chapter_num]

        # 获取之前章节的摘要
        prev_summaries = ""
        if self.vector_store:
            prev_summaries = "\n".join(self.vector_store.get_all_summaries()[-3:])

        prompt = f"""你是一位注重文字简洁性的编辑。请审核以下章节是否存在重复问题。

【已生成章节摘要】（检查是否与之前内容重复）
{prev_summaries if prev_summaries else "本章为第一章"}

【当前章节】
{content}

【审核维度】
1. 跨章重复：
   - 本章事件是否与之前章节重复叙述
   - 同一细节是否在多章出现

2. 章内重复：
   - 同一段内是否有意思重复的句子
   - 是否用不同说法表达同一个意思（同义反复）

3. 车轱辘话：
   - 是否有循环论证
   - 是否有无意义的重复强调

4. 信息密度：
   - 段落是否信息量过低（用大量文字说少量内容）

【向量存储相似度分析】
{chr(10).join([f"- 与第{ch['chapter_num']}章《{ch['title']}》相似度: {ch['similarity']:.2f}" for ch in similar_chapters]) if similar_chapters else "暂无明显相似章节"}

【输出要求】
JSON格式：
{{
    "passed": true,
    "issues": [
        {{
            "type": "cross_chapter_repeat",
            "location": "第2节",
            "description": "本章详细描述1985年创业，与第1章第3节内容重复",
            "severity": "major"
        }}
    ],
    "score": 92,
    "suggestions": ["删除重复内容，或改为简要提及"]
}}"""

        try:
            response = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=3000,
                timeout=60
            )

            result = json.loads(response)
            return DimensionReview(
                passed=result.get("passed", False),
                issues=result.get("issues", []),
                score=result.get("score", 0),
                suggestions=result.get("suggestions", [])
            )
        except Exception as e:
            return DimensionReview(
                passed=False,
                issues=[{"error": f"审核异常: {e}"}],
                score=0
            )


class LiteraryChecker:
    """文学审核Agent - 检查文学性、描写质量"""

    def __init__(self, llm):
        self.llm = llm

    async def review(self, content: str, chapter_context: Any) -> DimensionReview:
        """
        审核文学性和写作质量
        """
        prompt = f"""你是一位文学编辑，专注于传记写作质量。请审核以下章节的文学性。

【待审核章节】
{content}

【审核维度】
1. 描写质量：
   - 场景是否有感官细节（视觉、听觉、气味、触觉）
   - 人物是否有具体动作而非抽象标签
   - 环境描写是否服务于叙事

2. 对话质量：
   - 对话是否自然（符合人物身份、时代背景）
   - 是否有"解释性对话"（为了告诉读者信息而说）

3. 叙事节奏：
   - 段落长度是否有变化
   - 叙述、描写、对话的比例是否恰当
   - 有无冗长的背景介绍

4. 情感表达：
   - 是否通过言行展现情感，而非标签（"他很伤心"）
   - 情感转变是否有铺垫

5. 套路化检查：
   - 是否有AI常见套路（"尘埃在光柱中飞舞"、"苦涩中带着回甘"等）
   - 是否有过度戏剧化

【输出要求】
JSON格式：
{{
    "passed": false,
    "issues": [
        {{
            "type": "weak_description",
            "location": "第5段",
            "description": "1986年工厂场景缺乏感官细节，只有笼统描述",
            "suggestion": "增加机器声音、光线、气味等具体描写",
            "severity": "minor"
        }},
        {{
            "type": "emotion_label",
            "location": "第8段",
            "description": "'他陷入了沉思，心中充满复杂的情绪'是情感标签",
            "suggestion": "改为具体动作，如'他点燃一支烟，盯着窗外看了很久'",
            "severity": "major"
        }}
    ],
    "score": 75,
    "suggestions": ["整体建议: 增加更多对话场景"]
}}"""

        try:
            response = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=3000,
                timeout=60
            )

            result = json.loads(response)
            return DimensionReview(
                passed=result.get("passed", False),
                issues=result.get("issues", []),
                score=result.get("score", 0),
                suggestions=result.get("suggestions", [])
            )
        except Exception as e:
            return DimensionReview(
                passed=False,
                issues=[{"error": f"审核异常: {e}"}],
                score=0
            )


class QualitySelector:
    """质量选择器 - 用于竞争生成时选择更优版本"""

    def __init__(self, llm):
        self.llm = llm

    async def select_better_outline(self, outline_a: Dict, review_a: Dict, outline_b: Dict, review_b: Dict) -> str:
        """选择更优的大纲版本"""
        prompt = f"""请比较以下两个大纲版本，选择质量更好的一个。

【版本A】
{json.dumps(outline_a, ensure_ascii=False, indent=2)[:5000]}

审核结果:
- 通过: {review_a.get('passed', False)}
- 问题数: {len(review_a.get('issues', []))}
- 评分: {review_a.get('score', 0)}

【版本B】
{json.dumps(outline_b, ensure_ascii=False, indent=2)[:5000]}

审核结果:
- 通过: {review_b.get('passed', False)}
- 问题数: {len(review_b.get('issues', []))}
- 评分: {review_b.get('score', 0)}

【选择标准】
1. 时间线清晰度和准确性
2. 章节划分的合理性
3. 推断内容的设计是否合理
4. 总字数分配的合理性

请输出JSON：
{{"selected_version": "A或B", "reason": "简要说明选择理由"}}"""

        try:
            response = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1000,
                timeout=60
            )

            result = json.loads(response)
            return result.get("selected_version", "A")
        except:
            # 默认选A
            return "A"
