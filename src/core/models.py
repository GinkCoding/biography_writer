"""
数据模型定义
"""
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from datetime import datetime


@dataclass
class SectionOutline:
    """小节大纲"""
    order: int
    title: str
    content_summary: str
    target_words: int
    section_type: str = "factual"  # factual, expanded, inferred
    key_events: List[str] = field(default_factory=list)
    inference_basis: str = ""


@dataclass
class ChapterOutline:
    """章节大纲"""
    order: int
    title: str
    time_range: str
    target_words: int
    sections: List[SectionOutline] = field(default_factory=list)


@dataclass
class BookOutline:
    """书籍大纲"""
    subject_name: str
    total_chapters: int
    target_total_words: int
    chapters: List[ChapterOutline] = field(default_factory=list)

    @classmethod
    def from_llm_response(cls, response: str) -> "BookOutline":
        """从LLM响应解析大纲"""
        # 提取JSON部分
        try:
            # 尝试直接解析
            data = json.loads(response)
        except json.JSONDecodeError:
            # 尝试从markdown代码块提取
            import re
            json_match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                raise ValueError("无法解析大纲JSON")

        chapters = []
        for ch_data in data.get("chapters", []):
            sections = []
            for sec_data in ch_data.get("sections", []):
                sections.append(SectionOutline(
                    order=sec_data.get("order", 0),
                    title=sec_data.get("title", ""),
                    content_summary=sec_data.get("content_summary", ""),
                    target_words=sec_data.get("target_words", 0),
                    section_type=sec_data.get("section_type", "factual"),
                    key_events=sec_data.get("key_events", []),
                    inference_basis=sec_data.get("inference_basis", "")
                ))

            chapters.append(ChapterOutline(
                order=ch_data.get("order", 0),
                title=ch_data.get("title", ""),
                time_range=ch_data.get("time_range", ""),
                target_words=ch_data.get("target_words", 0),
                sections=sections
            ))

        return cls(
            subject_name=data.get("subject_name", "未知"),
            total_chapters=data.get("total_chapters", 0),
            target_total_words=data.get("target_total_words", 0),
            chapters=chapters
        )

    def to_json(self) -> str:
        """转为JSON字符串"""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_text_summary(self) -> str:
        """转为文本摘要"""
        lines = [
            f"《{self.subject_name}传》",
            f"总章节: {self.total_chapters}章",
            f"目标字数: {self.target_total_words}字",
            ""
        ]
        for ch in self.chapters:
            lines.append(f"第{ch.order}章: {ch.title} ({ch.time_range})")
            for s in ch.sections:
                lines.append(f"  第{s.order}节 [{s.section_type}]: {s.title}")
        return "\n".join(lines)


@dataclass
class MaterialEvaluation:
    """素材评估报告"""
    sufficient: bool
    fact_based_capacity: int
    expanded_capacity: int
    inferred_capacity: int
    recommended_target: int
    expansion_strategy: Dict
    potential_issues: List[str]
    chapter_suggestion: Dict
    reasoning: str

    @classmethod
    def from_llm_response(cls, response: str) -> "MaterialEvaluation":
        """从LLM响应解析评估报告"""
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                raise ValueError("无法解析评估JSON")

        return cls(
            sufficient=data.get("sufficient", False),
            fact_based_capacity=data.get("fact_based_capacity", 0),
            expanded_capacity=data.get("expanded_capacity", 0),
            inferred_capacity=data.get("inferred_capacity", 0),
            recommended_target=data.get("recommended_target", 50000),
            expansion_strategy=data.get("expansion_strategy", {}),
            potential_issues=data.get("potential_issues", []),
            chapter_suggestion=data.get("chapter_suggestion", {}),
            reasoning=data.get("reasoning", "")
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_text_summary(self) -> str:
        lines = [
            f"素材充足度: {'充足' if self.sufficient else '不足'}",
            f"基于事实可写: {self.fact_based_capacity}字",
            f"扩写后可写: {self.expanded_capacity}字",
            f"推断后可写: {self.inferred_capacity}字",
            f"建议目标: {self.recommended_target}字",
            f"\n扩写策略:",
            f"  重度扩写事件: {', '.join(self.expansion_strategy.get('heavy_expansion_events', []))}",
            f"  可推断空档: {', '.join(self.expansion_strategy.get('inference_gaps', []))}",
            f"  推断原则: {self.expansion_strategy.get('inference_principles', '')}",
            f"\n潜在问题:",
        ]
        for issue in self.potential_issues:
            lines.append(f"  - {issue}")
        return "\n".join(lines)


@dataclass
class DimensionReview:
    """单维度审核结果"""
    passed: bool
    issues: List[Dict] = field(default_factory=list)
    score: int = 0
    suggestions: List[str] = field(default_factory=list)


@dataclass
class ReviewReport:
    """综合审核报告"""
    fact_review: DimensionReview
    continuity_review: DimensionReview
    repetition_review: DimensionReview
    literary_review: DimensionReview
    round_number: int = 1

    @classmethod
    def from_dimension_results(cls, results: Dict[str, Any]) -> "ReviewReport":
        """从各维度结果创建报告"""
        def make_review(r):
            if isinstance(r, dict):
                return DimensionReview(
                    passed=r.get("passed", False),
                    issues=r.get("issues", []),
                    score=r.get("score", 0),
                    suggestions=r.get("suggestions", [])
                )
            return r

        return cls(
            fact_review=make_review(results.get("fact", {})),
            continuity_review=make_review(results.get("continuity", {})),
            repetition_review=make_review(results.get("repetition", {})),
            literary_review=make_review(results.get("literary", {}))
        )

    @classmethod
    def from_llm_response(cls, response: str, version_name: str = "") -> "ReviewReport":
        """从LLM响应解析"""
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                data = {}

        def make_dim_review(issues, passed):
            return DimensionReview(
                passed=passed,
                issues=[{"description": i} for i in issues] if isinstance(issues, list) else [],
                score=100 if passed else 50
            )

        return cls(
            fact_review=make_dim_review(data.get("fact_issues", []), data.get("passed", True)),
            continuity_review=make_dim_review(data.get("continuity_issues", []), data.get("passed", True)),
            repetition_review=make_dim_review([], True),
            literary_review=make_dim_review([], True)
        )

    def all_passed(self) -> bool:
        """是否全部通过"""
        return all([
            self.fact_review.passed,
            self.continuity_review.passed,
            self.repetition_review.passed,
            self.literary_review.passed
        ])

    def calculate_score(self) -> int:
        """计算综合得分"""
        scores = [
            self.fact_review.score,
            self.continuity_review.score,
            self.repetition_review.score,
            self.literary_review.score
        ]
        return sum(scores) // len(scores)

    def is_perfect(self) -> bool:
        """是否完美通过（无问题且高分）"""
        return self.all_passed() and self.calculate_score() >= 95

    def to_text_summary(self) -> str:
        """转为文本摘要"""
        lines = [
            f"综合评分: {self.calculate_score()}",
            f"事实性: {'通过' if self.fact_review.passed else '未通过'} ({self.fact_review.score}分)",
            f"连贯性: {'通过' if self.continuity_review.passed else '未通过'} ({self.continuity_review.score}分)",
            f"重复性: {'通过' if self.repetition_review.passed else '未通过'} ({self.repetition_review.score}分)",
            f"文学性: {'通过' if self.literary_review.passed else '未通过'} ({self.literary_review.score}分)",
        ]

        all_issues = self.get_issues()
        if all_issues:
            lines.append(f"\n问题列表 ({len(all_issues)}个):")
            for i, issue in enumerate(all_issues[:5], 1):  # 最多显示5个
                lines.append(f"  {i}. {issue.get('type', '未知')}: {issue.get('description', '')[:50]}...")
        else:
            lines.append("\n无问题")

        return "\n".join(lines)

    def get_issues(self) -> List[Dict]:
        """获取所有问题"""
        all_issues = []
        for review in [self.fact_review, self.continuity_review, self.repetition_review, self.literary_review]:
            all_issues.extend(review.issues)
        return all_issues

    def get_issues_by_dimension(self) -> Dict[str, List[str]]:
        """按维度分类问题"""
        return {
            "fact": [i.get("description", str(i)) for i in self.fact_review.issues],
            "continuity": [i.get("description", str(i)) for i in self.continuity_review.issues],
            "repetition": [i.get("description", str(i)) for i in self.repetition_review.issues],
            "literary": [i.get("description", str(i)) for i in self.literary_review.issues]
        }

    def get_fixed_issues(self) -> List[str]:
        """获取已修复的问题（用于历史记录）"""
        return []  # 由外部调用者根据历史对比确定

    def get_remaining_issues(self) -> List[str]:
        """获取待修复的问题"""
        return [i.get("description", str(i)) for i in self.get_issues()]


@dataclass
class RevisionHistory:
    """修订历史记录"""
    round: int
    review: ReviewReport
    content: str
    quality_score: int
    word_count: int


@dataclass
class GenerationConfig:
    """生成配置"""
    max_revision_rounds: int = 5
    temperature_outline: float = 0.5
    temperature_chapter: float = 0.6
    temperature_review: float = 0.2
    timeout_outline: int = 600
    timeout_chapter: int = 900
    timeout_review: int = 60
    enable_competition: bool = True
