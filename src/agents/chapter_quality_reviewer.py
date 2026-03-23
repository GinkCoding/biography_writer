"""
章节整体质量评审Agent - 迭代式质量审核与修订
"""
import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class QualityIssue:
    """质量问题"""
    dimension: str  # outline, character, plot, literary
    severity: str  # critical, major, minor
    location: str
    description: str
    suggestion: str


@dataclass
class ChapterQualityReport:
    """章节质量评审报告"""
    score: int  # 0-100
    passed: bool
    critical_issues: int
    major_issues: int
    minor_issues: int
    issues: List[QualityIssue] = field(default_factory=list)
    outline_alignment: Dict = field(default_factory=dict)
    character_analysis: Dict = field(default_factory=dict)
    plot_coherence: Dict = field(default_factory=dict)
    literary_quality: Dict = field(default_factory=dict)
    reasoning: str = ""

    def has_critical_issues(self) -> bool:
        """是否存在严重问题"""
        return self.critical_issues > 0

    def meets_threshold(self, threshold: int = 90) -> bool:
        """是否达到通过阈值"""
        return self.score >= threshold and not self.has_critical_issues()

    def to_text_summary(self) -> str:
        """转为文本摘要"""
        lines = [
            f"综合评分: {self.score}/100",
            f"评审结果: {'通过' if self.passed else '未通过'}",
            f"问题统计: 严重{self.critical_issues}个, 主要{self.major_issues}个, 次要{self.minor_issues}个",
            "",
            "【各维度评分】",
            f"大纲符合度: {self.outline_alignment.get('score', 0)}/100",
            f"人物符合度: {self.character_analysis.get('score', 0)}/100",
            f"情节连贯度: {self.plot_coherence.get('score', 0)}/100",
            f"文学性: {self.literary_quality.get('score', 0)}/100",
        ]

        if self.issues:
            lines.append("\n【问题列表】")
            for i, issue in enumerate(self.issues[:10], 1):  # 最多显示10个
                lines.append(
                    f"{i}. [{issue.severity}] {issue.dimension}: {issue.description[:80]}"
                )

        return "\n".join(lines)


class ChapterQualityReviewer:
    """
    章节整体质量评审Agent

    职责：
    1. 评审章节是否符合大纲规划
    2. 评审人物行为是否符合人设
    3. 评审情节是否连贯合理
    4. 评审文学性是否达标
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def review(
        self,
        chapter_content: str,
        chapter_outline: Any,
        book_outline: Any,
        character_profile: str,
        previous_summaries: List[str],
        chapter_num: int,
        enable_thinking: bool = True
    ) -> ChapterQualityReport:
        """
        评审章节整体质量

        Args:
            chapter_content: 章节内容
            chapter_outline: 章节大纲
            book_outline: 全书大纲
            character_profile: 人物小传
            previous_summaries: 前文摘要
            chapter_num: 章节编号
            enable_thinking: 是否启用thinking模式（深度分析）

        Returns:
            ChapterQualityReport: 质量评审报告
        """
        logger.info(f"      开始章节质量评审 (第{chapter_num}章, thinking={enable_thinking})")

        # 构建评审上下文
        context = self._build_review_context(
            chapter_content, chapter_outline, book_outline,
            character_profile, previous_summaries, chapter_num
        )

        # 构建评审提示词
        prompt = self._build_review_prompt(context, chapter_num)

        # 调用LLM进行评审
        try:
            response = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.3,  # 评审需要较低温度保证稳定性
                thinking=enable_thinking,  # 根据参数决定是否启用thinking
                max_tokens=16384,
                timeout=180
            )

            # 解析评审结果
            report = self._parse_review_response(response)
            logger.info(f"      评审完成: 评分{report.score}, 严重问题{report.critical_issues}个")
            return report

        except Exception as e:
            logger.error(f"      评审异常: {e}")
            # 返回默认失败报告
            return ChapterQualityReport(
                score=0,
                passed=False,
                critical_issues=1,
                major_issues=0,
                minor_issues=0,
                issues=[QualityIssue(
                    dimension="system",
                    severity="critical",
                    location="评审过程",
                    description=f"评审系统异常: {str(e)}",
                    suggestion="请检查系统配置"
                )],
                reasoning=f"评审失败: {str(e)}"
            )

    def _build_review_context(
        self,
        chapter_content: str,
        chapter_outline: Any,
        book_outline: Any,
        character_profile: str,
        previous_summaries: List[str],
        chapter_num: int
    ) -> Dict[str, Any]:
        """构建评审上下文"""
        context = {
            "chapter_num": chapter_num,
            "chapter_title": getattr(chapter_outline, 'title', ''),
            "chapter_time_range": getattr(chapter_outline, 'time_range', ''),
            "chapter_target_words": getattr(chapter_outline, 'target_words', 0),
            "sections_plan": [],
            "book_subject": getattr(book_outline, 'subject_name', ''),
            "total_chapters": getattr(book_outline, 'total_chapters', 0),
            "character_profile": character_profile,
            "previous_summaries": previous_summaries,
            "chapter_content_length": len(chapter_content)
        }

        # 提取章节小节规划
        if hasattr(chapter_outline, 'sections'):
            for section in chapter_outline.sections:
                context["sections_plan"].append({
                    "order": getattr(section, 'order', 0),
                    "title": getattr(section, 'title', ''),
                    "type": getattr(section, 'section_type', 'factual'),
                    "summary": getattr(section, 'content_summary', ''),
                    "target_words": getattr(section, 'target_words', 0)
                })

        return context

    def _build_review_prompt(self, context: Dict, chapter_num: int) -> str:
        """构建评审提示词"""
        sections_text = "\n".join([
            f"  第{s['order']}节 [{s['type']}]: {s['title']} (目标{s['target_words']}字)\n"
            f"    概要: {s['summary']}"
            for s in context["sections_plan"]
        ])

        previous_text = "\n\n".join(context["previous_summaries"]) if context["previous_summaries"] else "本章为第一章"

        prompt = f"""你是一位资深的传记编辑和质量审核专家。请对以下章节进行全面的质量评审。

【全书信息】
书名: 《{context['book_subject']}传》
总章节: {context['total_chapters']}章
当前章节: 第{chapter_num}章

【人物小传】
{context['character_profile']}

【前文摘要】（用于连贯性审核）
{previous_text}

【本章大纲规划】
章节标题: {context['chapter_title']}
时间跨度: {context['chapter_time_range']}
目标字数: 约{context['chapter_target_words']}字（参考值，允许±10%浮动）

小节规划:
{sections_text}

【待审核章节内容】
[章节共{context['chapter_content_length']}字]
请基于上述信息进行全面评审。

【评审维度与要求】

1. **大纲符合度评审** (权重30%)
   - 是否按小节规划组织内容
   - 每个小节是否覆盖了规划的内容概要
   - 内容类型（factual/expanded/inferred）是否符合标注
   - 时间跨度是否在大纲范围内
   - 是否有遗漏或超出规划的内容

2. **人物行为符合度评审** (权重25%)
   - 人物言行是否符合人物小传中的性格特征
   - 人物在不同年龄段的行为是否符合成长规律
   - 人物决策是否符合其价值观和处境
   - 人物关系发展是否符合人设逻辑
   - 是否有OOC（Out of Character）问题

3. **情节连贯性评审** (权重25%)
   - 与前文的时间线是否连续或合理跳跃
   - 事件因果关系是否清晰合理
   - 情节推进是否有逻辑漏洞
   - 人物出场/退场是否自然
   - 是否有未交代的重要转折

4. **文学性评审** (权重20%)
   - 场景描写是否有感官细节（视觉、听觉、气味等）
   - 对话是否自然、符合人物身份和时代背景
   - 叙事节奏是否恰当（段落长度变化、详略得当）
   - 是否避免了套路化表达和AI痕迹
   - 情感表达是否通过具体行为展现而非标签

【问题严重程度定义】
- **critical（严重）**: 必须修复，否则影响作品质量
  - 与大纲严重偏离
  - 人物行为严重违背人设
  - 情节逻辑严重错误
  - 事实性错误

- **major（主要）**: 应该修复，影响阅读体验
  - 部分偏离大纲
  - 人物行为略显违和
  - 情节衔接不够自然
  - 文学性不足

- **minor（次要）**: 可选修复，锦上添花
  - 细节可以更丰富
  - 表达可以更精炼
  - 节奏可以调整

【输出格式】
请输出JSON格式：
{{
    "score": 85,
    "passed": false,
    "critical_issues": 1,
    "major_issues": 2,
    "minor_issues": 3,
    "issues": [
        {{
            "dimension": "outline",
            "severity": "critical",
            "location": "第2节",
            "description": "第2节规划为'工厂创业艰辛'，但实际内容主要写家庭生活，偏离大纲",
            "suggestion": "调整内容重心，增加工厂创业的细节描写"
        }},
        {{
            "dimension": "character",
            "severity": "major",
            "location": "第5段",
            "description": "人物在困境中选择放弃，与其小传中'坚韧不拔'的性格特征不符",
            "suggestion": "改为'他咬牙坚持，即使前路渺茫也不愿放弃'"
        }}
    ],
    "outline_alignment": {{
        "score": 80,
        "adherence": "基本符合，第2节有偏离",
        "details": "第1、3节符合规划，第2节内容偏离"
    }},
    "character_analysis": {{
        "score": 85,
        "consistency": "整体符合，个别行为略显违和",
        "details": "主要人物行为符合人设，第5段决策略显突兀"
    }},
    "plot_coherence": {{
        "score": 90,
        "coherence": "情节连贯，逻辑清晰",
        "details": "时间线清晰，事件因果关系合理"
    }},
    "literary_quality": {{
        "score": 75,
        "strengths": "对话自然，节奏尚可",
        "weaknesses": "场景描写缺乏感官细节，部分表达套路化",
        "details": "建议增加视觉、听觉等感官描写"
    }},
    "reasoning": "本章整体质量良好，但存在大纲偏离和人物行为违和问题，建议重点修订第2节内容和第5段人物行为。"
}}

【评分标准】
- 90-100分：优秀，无严重问题，可小修或直接通过
- 80-89分：良好，有少量主要问题，需要修订
- 70-79分：合格，有主要问题，需要重点修订
- 60-69分：待改进，有严重问题，需要大幅修订
- 60分以下：不合格，建议重写

【注意事项】
1. 评审要客观公正，不要过度苛刻或过于宽松
2. 问题定位要具体，便于后续修改
3. 建议要可操作，不要泛泛而谈
4. 综合评分要反映整体质量，不要因小问题大幅扣分"""

        return prompt

    def _parse_review_response(self, response: str) -> ChapterQualityReport:
        """解析LLM评审响应"""
        try:
            # 尝试直接解析JSON
            data = json.loads(response)
        except json.JSONDecodeError:
            # 尝试从markdown代码块提取
            import re
            json_match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                # 尝试提取花括号内容
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group(0))
                else:
                    raise ValueError("无法解析评审结果JSON")

        # 解析问题列表
        issues = []
        for issue_data in data.get("issues", []):
            issues.append(QualityIssue(
                dimension=issue_data.get("dimension", "unknown"),
                severity=issue_data.get("severity", "minor"),
                location=issue_data.get("location", ""),
                description=issue_data.get("description", ""),
                suggestion=issue_data.get("suggestion", "")
            ))

        # 构建评审报告
        return ChapterQualityReport(
            score=data.get("score", 0),
            passed=data.get("passed", False),
            critical_issues=data.get("critical_issues", 0),
            major_issues=data.get("major_issues", 0),
            minor_issues=data.get("minor_issues", 0),
            issues=issues,
            outline_alignment=data.get("outline_alignment", {}),
            character_analysis=data.get("character_analysis", {}),
            plot_coherence=data.get("plot_coherence", {}),
            literary_quality=data.get("literary_quality", {}),
            reasoning=data.get("reasoning", "")
        )


class ChapterRevisionAgent:
    """
    章节修订Agent

    根据评审报告进行针对性修订
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def revise(
        self,
        chapter_content: str,
        quality_report: ChapterQualityReport,
        chapter_outline: Any,
        book_outline: Any,
        character_profile: str,
        revision_round: int,
        enable_thinking: bool = False  # 修改阶段默认关闭thinking
    ) -> str:
        """
        根据评审报告修订章节

        Args:
            chapter_content: 当前章节内容
            quality_report: 质量评审报告
            chapter_outline: 章节大纲
            book_outline: 全书大纲
            character_profile: 人物小传
            revision_round: 修订轮次
            enable_thinking: 是否启用thinking模式

        Returns:
            str: 修订后的章节内容
        """
        logger.info(f"      开始第{revision_round}轮修订 (thinking={enable_thinking})")

        # 构建修订提示词
        prompt = self._build_revision_prompt(
            chapter_content, quality_report, chapter_outline,
            book_outline, character_profile, revision_round
        )

        # 调用LLM进行修订
        try:
            response = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.5,  # 修订需要一定创造性
                thinking=enable_thinking,  # 根据参数决定是否启用thinking
                max_tokens=16384,
                timeout=600
            )

            logger.info(f"      修订完成，内容长度{len(response)}字")
            return response

        except Exception as e:
            logger.error(f"      修订异常: {e}")
            # 返回原内容
            return chapter_content

    def _build_revision_prompt(
        self,
        chapter_content: str,
        quality_report: ChapterQualityReport,
        chapter_outline: Any,
        book_outline: Any,
        character_profile: str,
        revision_round: int
    ) -> str:
        """构建修订提示词"""
        # 按严重程度排序问题
        critical_issues = [i for i in quality_report.issues if i.severity == "critical"]
        major_issues = [i for i in quality_report.issues if i.severity == "major"]
        minor_issues = [i for i in quality_report.issues if i.severity == "minor"]

        issues_text = ""
        if critical_issues:
            issues_text += "\n【严重问题（必须修复）】\n"
            for i, issue in enumerate(critical_issues, 1):
                issues_text += f"{i}. [{issue.dimension}] {issue.location}\n"
                issues_text += f"   问题: {issue.description}\n"
                issues_text += f"   建议: {issue.suggestion}\n"

        if major_issues:
            issues_text += "\n【主要问题（应该修复）】\n"
            for i, issue in enumerate(major_issues, 1):
                issues_text += f"{i}. [{issue.dimension}] {issue.location}\n"
                issues_text += f"   问题: {issue.description}\n"
                issues_text += f"   建议: {issue.suggestion}\n"

        if minor_issues and revision_round < 3:  # 前几轮也处理次要问题
            issues_text += "\n【次要问题（可选修复）】\n"
            for i, issue in enumerate(minor_issues[:3], 1):  # 最多显示3个次要问题
                issues_text += f"{i}. [{issue.dimension}] {issue.location}\n"
                issues_text += f"   问题: {issue.description}\n"
                issues_text += f"   建议: {issue.suggestion}\n"

        sections_text = ""
        if hasattr(chapter_outline, 'sections'):
            sections_text = "\n".join([
                f"  第{s.order}节 [{s.section_type}]: {s.title}"
                for s in chapter_outline.sections
            ])

        prompt = f"""你是一位专业的传记编辑。请根据质量评审报告修订以下章节。

【修订轮次】
第{revision_round}轮修订

【章节大纲规划】
章节: {getattr(chapter_outline, 'title', '')}
时间跨度: {getattr(chapter_outline, 'time_range', '')}
目标字数: 约{getattr(chapter_outline, 'target_words', 0)}字

小节规划:
{sections_text}

【人物小传】
{character_profile[:1000]}...

【当前评审结果】
综合评分: {quality_report.score}/100
严重问题: {quality_report.critical_issues}个
主要问题: {quality_report.major_issues}个
次要问题: {quality_report.minor_issues}个

{issues_text}

【各维度分析】
大纲符合度: {quality_report.outline_alignment.get('score', 0)}/100
  {quality_report.outline_alignment.get('details', '')}

人物符合度: {quality_report.character_analysis.get('score', 0)}/100
  {quality_report.character_analysis.get('details', '')}

情节连贯度: {quality_report.plot_coherence.get('score', 0)}/100
  {quality_report.plot_coherence.get('details', '')}

文学性: {quality_report.literary_quality.get('score', 0)}/100
  {quality_report.literary_quality.get('details', '')}

【当前章节内容】
{chapter_content}

【修订要求】
1. **优先处理严重问题**：必须修复所有critical级别的问题
2. **处理主要问题**：尽可能修复major级别的问题
3. **保持原有优点**：不要因为修改而破坏已有的好内容
4. **控制修改范围**：针对性修改，不要大幅重写（除非严重问题很多）
5. **保持字数规模**：修订后字数应与原内容相近（±10%）

【修订原则】
- 大纲偏离：调整内容重心，补充规划内容，删除超出内容
- 人物违和：调整人物言行，使其符合性格特征和成长规律
- 情节问题：补充过渡，理顺因果关系，填补逻辑漏洞
- 文学性不足：增加感官细节，优化对话，调整叙事节奏

【输出要求】
直接输出修订后的完整章节内容，不需要任何说明或标记。"""

        return prompt
