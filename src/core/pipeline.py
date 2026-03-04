"""
全自动传记生成流水线 - LLM Driven Architecture
"""
import asyncio
import json
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger

from src.core.agents import (
    FactChecker, ContinuityChecker, RepetitionChecker, LiteraryChecker,
    QualitySelector
)
from src.core.facts_db import FactsDatabase
from src.core.models import (
    MaterialEvaluation, BookOutline, ChapterOutline,
    ReviewReport, RevisionHistory, GenerationConfig
)
from src.llm_client import LLMClient
from src.core.vector_store import SimpleVectorStore


@dataclass
class PipelineState:
    """流水线状态"""
    project_id: str
    material_path: Path
    output_dir: Path
    target_words: int = 100000
    current_phase: str = "init"
    outline: Optional[BookOutline] = None
    evaluation: Optional[MaterialEvaluation] = None
    generated_chapters: List[Dict] = field(default_factory=list)
    errors: List[Dict] = field(default_factory=list)


class BiographyPipeline:
    """全自动传记生成流水线"""

    def __init__(self, config: Optional[GenerationConfig] = None, output_dir: Optional[Path] = None):
        self.config = config or GenerationConfig()
        self.llm = LLMClient()
        self.output_dir = output_dir

        # 初始化事实数据库（轻量级JSON存储）
        facts_db_path = output_dir / "meta" / "facts_db.json" if output_dir else Path("facts_db.json")
        self.facts_db = FactsDatabase(facts_db_path)

        # 初始化向量存储（用于重复检测）
        vector_store_path = output_dir / "meta" / "vector_store.json" if output_dir else Path("vector_store.json")
        self.vector_store = SimpleVectorStore(vector_store_path)

        # 初始化审核Agent
        self.fact_checker = FactChecker(self.llm, self.facts_db)
        self.continuity_checker = ContinuityChecker(self.llm, self.facts_db)
        self.repetition_checker = RepetitionChecker(self.llm, self.vector_store)
        self.literary_checker = LiteraryChecker(self.llm)
        self.quality_selector = QualitySelector(self.llm)

    async def run(self, material_path: Path, output_dir: Path, target_words: int = 100000) -> Path:
        """
        运行完整流水线

        Returns:
            最终传记文件路径
        """
        state = PipelineState(
            project_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
            material_path=material_path,
            output_dir=output_dir,
            target_words=target_words
        )

        logger.info(f"🚀 启动传记生成流水线: {state.project_id}")

        try:
            # Phase 1: 素材评估
            state.current_phase = "material_evaluation"
            state.evaluation = await self._evaluate_material(state)

            # Phase 2 & 3: 大纲生成 + 竞争审核
            state.current_phase = "outline_generation"
            state.outline = await self._generate_outline_with_competition(state)

            # Phase 4-6: 逐章生成+审核+修订
            state.current_phase = "chapter_generation"
            await self._generate_all_chapters(state)

            # Phase 7: 终审与组装
            state.current_phase = "final_assembly"
            final_path = await self._assemble_final_book(state)

            logger.info(f"✅ 流水线完成: {final_path}")
            return final_path

        except Exception as e:
            logger.error(f"❌ 流水线失败 [{state.current_phase}]: {e}")
            state.errors.append({"phase": state.current_phase, "error": str(e)})
            raise

    async def _evaluate_material(self, state: PipelineState) -> MaterialEvaluation:
        """
        Phase 1: 素材评估

        让LLM全面分析素材，判断能否支撑目标字数，制定扩写策略
        """
        material_text = state.material_path.read_text(encoding='utf-8')

        target_words = state.target_words
        # 计算合理范围（目标字数的±10%）
        min_words = int(target_words * 0.9)
        max_words = int(target_words * 1.1)

        prompt = f"""你是一位资深的传记编辑和写作顾问。请对以下采访素材进行全面评估，判断是否足以支撑一本约{target_words // 10000}万字的传记（合理范围：{min_words}-{max_words}字）。

【完整采访素材】
{material_text}

【评估任务】
1. 分析素材的内容构成：
   - 时间跨度（最早到最晚的年份）
   - 核心事件数量
   - 细节丰富度（对话、场景、数字等）
   - 人物关系复杂度
   - 情感深度（是否有内心独白、重大转折等）

2. 判断能否支撑约{target_words}字（允许±10%浮动，即{min_words}-{max_words}字）：
   - 素材本身可支撑多少字（严格基于事实）
   - 通过合理扩写（细节描写）可扩展到多少字
   - 通过合理推断（填补空档年份）可再扩展到多少字
   - 是否建议调整目标字数（建议在合理范围内）

3. 制定扩写策略：
   - 哪些事件需要重度扩写（增加场景、对话、心理描写）
   - 哪些年份存在信息空档，可合理推断
   - 推断的原则和边界（平淡、符合人设、不违和）

4. 识别潜在问题：
   - 时间线矛盾
   - 信息缺失的关键节点
   - 需要核实的事实

【输出格式】
请输出JSON格式：
{{
    "sufficient": false,
    "fact_based_capacity": 15000,
    "expanded_capacity": 45000,
    "inferred_capacity": 85000,
    "recommended_target": 80000,
    "expansion_strategy": {{
        "heavy_expansion_events": ["事件1", "事件2"],
        "inference_gaps": ["1987-1989年", "1995-1996年"],
        "inference_principles": "平淡日常、符合人设、不违和"
    }},
    "potential_issues": ["问题1", "问题2"],
    "chapter_suggestion": {{
        "recommended_chapters": 5,
        "chapter_themes": ["主题1", "主题2", ...]
    }},
    "reasoning": "详细的分析推理过程"
}}"""

        logger.info("📊 Phase 1: 素材评估...")

        response = await self.llm.complete(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            thinking=True,
            max_tokens=4000,
            timeout=300
        )

        try:
            evaluation = MaterialEvaluation.from_llm_response(response)
            logger.info(f"   ✓ 评估完成: 建议目标{evaluation.recommended_target}字")

            # 保存评估报告
            eval_path = state.output_dir / "meta" / "material_evaluation.json"
            eval_path.parent.mkdir(parents=True, exist_ok=True)
            eval_path.write_text(evaluation.to_json(), encoding='utf-8')

            return evaluation

        except Exception as e:
            logger.error(f"评估解析失败: {e}")
            raise

    async def _generate_outline_with_competition(self, state: PipelineState) -> BookOutline:
        """
        Phase 2 & 3: 大纲生成 + 竞争审核

        同时生成两个版本（标准 + 调整参数），选择质量更好的
        """
        material_text = state.material_path.read_text(encoding='utf-8')
        evaluation = state.evaluation

        logger.info("📝 Phase 2: 大纲生成（竞争模式）...")

        # 并行生成两个版本
        version_a, version_b = await asyncio.gather(
            self._generate_outline_version(state, material_text, evaluation, temperature=0.5),
            self._generate_outline_version(state, material_text, evaluation, temperature=0.7),
            return_exceptions=True
        )

        # 检查异常
        versions = []
        for v, name in [(version_a, "A"), (version_b, "B")]:
            if isinstance(v, Exception):
                logger.warning(f"   版本{name}生成失败: {v}")
            else:
                versions.append((name, v))

        if len(versions) == 0:
            raise RuntimeError("所有大纲版本生成失败")

        if len(versions) == 1:
            logger.info(f"   只有一个版本成功，使用版本{versions[0][0]}")
            selected = versions[0][1]
        else:
            # 竞争审核选择
            logger.info("   开始竞争审核...")
            selected = await self._competitive_select_outline(versions)

        # 保存大纲
        outline_path = state.output_dir / "meta" / "outline.json"
        outline_path.parent.mkdir(parents=True, exist_ok=True)
        outline_path.write_text(selected.to_json(), encoding='utf-8')

        logger.info(f"   ✓ 大纲确定: {selected.total_chapters}章")
        return selected

    async def _generate_outline_version(
        self, state: PipelineState, material: str, evaluation: MaterialEvaluation, temperature: float
    ) -> BookOutline:
        """生成单个大纲版本"""

        prompt = f"""你是一位专业的传记作家和图书策划人。请基于以下采访素材和评估报告，设计一本传记的详细大纲。

【目标】
- 总字数: 约{state.target_words // 10000}万字（合理范围：{int(state.target_words * 0.9)}-{int(state.target_words * 1.1)}字，允许±10%浮动）
- 章节数: 建议{evaluation.chapter_suggestion.get('recommended_chapters', 5)}章

重要：字数是参考值，不必严格精确。重点是内容充实、叙事完整。

【采访素材】
{material[:8000]}...
[素材共{len(material)}字，以上为前8000字]

【素材评估报告】
{evaluation.to_text_summary()}

【大纲设计要求】
1. 严格检查时间线顺序，确保章节按时间排列，无时间颠倒
2. 检查事件之间无重复叙述
3. 每章包含明确的时间跨度
4. 每节标注类型：
   - "factual": 完全基于采访事实
   - "expanded": 事实基础上的文学扩写
   - "inferred": 合理推断内容（会标注※）

5. 推断内容设计原则：
   - 用于填补素材中的时间空档
   - 内容必须平淡、日常、符合人设
   - 不能出现强烈戏剧性事件
   - 不能涉及道德敏感内容
   - 必须与已知事实无矛盾

【输出格式】
输出JSON格式大纲：
{{
    "subject_name": "传主姓名",
    "total_chapters": 5,
    "target_total_words": {state.target_words},
    "chapters": [
        {{
            "order": 1,
            "title": "章节标题",
            "time_range": "1965-1978",
            "target_words": 18000,
            "sections": [
                {{
                    "order": 1,
                    "title": "小节标题",
                    "content_summary": "内容概要",
                    "target_words": 4500,
                    "section_type": "factual|expanded|inferred",
                    "key_events": ["关键事件"],
                    "inference_basis": "如是推断，说明推断依据"
                }}
            ]
        }}
    ],
    "timeline_check": "时间线检查说明，确保无颠倒",
    "repetition_check": "重复检查说明，确保无重复事件"
}}"""

        response = await self.llm.complete(
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            thinking=True,
            max_tokens=6000,
            timeout=600
        )

        return BookOutline.from_llm_response(response)

    async def _competitive_select_outline(
        self, versions: List[Tuple[str, BookOutline]]
    ) -> BookOutline:
        """竞争选择最优大纲"""

        # 并行审核两个版本
        review_tasks = []
        for name, outline in versions:
            review_tasks.append(self._review_outline(outline, name))

        reviews = await asyncio.gather(*review_tasks)

        # 如果有明显胜出者，直接返回
        for (name, outline), review in zip(versions, reviews):
            if review.is_perfect():
                logger.info(f"   ✓ 版本{name}完美通过审核")
                return outline

        # 否则让LLM选择
        prompt = f"""请比较以下两个大纲版本，选择质量更好的一个。

【版本{versions[0][0]}】
{versions[0][1].to_text_summary()}

审核结果:
{reviews[0].to_text_summary()}

【版本{versions[1][0]}】
{versions[1][1].to_text_summary()}

审核结果:
{reviews[1].to_text_summary()}

【选择标准】
1. 时间线清晰度和准确性
2. 章节划分的合理性
3. 推断内容的设计是否合理
4. 总字数分配的合理性

请输出JSON：{{"selected_version": "A或B", "reason": "选择理由"}}"""

        response = await self.llm.complete(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1000
        )

        result = json.loads(response)
        selected_name = result.get("selected_version", "A")

        for name, outline in versions:
            if name == selected_name:
                logger.info(f"   ✓ 竞争选择: 版本{name}")
                return outline

        return versions[0][1]  # 默认返回第一个

    async def _review_outline(self, outline: BookOutline, version_name: str) -> ReviewReport:
        """大纲审核"""
        prompt = f"""请审核以下传记大纲的结构质量。

【大纲】
{outline.to_text_summary()}

【审核维度】
1. 时间线检查：章节是否按时间顺序排列？是否有时间颠倒？
2. 重复检查：同一事件是否在不同章节重复出现？
3. 逻辑检查：章节划分是否合理？时间跨度是否均衡？
4. 推断设计：推断内容是否合理？是否符合"平淡、不违和"原则？

【输出】
JSON格式：
{{
    "passed": true,
    "time_issues": [],
    "repetition_issues": [],
    "logic_issues": [],
    "inference_issues": [],
    "suggestions": []
}}"""

        response = await self.llm.complete(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2000,
            timeout=120
        )

        return ReviewReport.from_llm_response(response, version_name)

    async def _generate_all_chapters(self, state: PipelineState):
        """生成所有章节"""
        outline = state.outline

        logger.info(f"📖 Phase 4: 章节生成 ({outline.total_chapters}章)")

        for i, chapter in enumerate(outline.chapters, 1):
            logger.info(f"\n   第{i}章: {chapter.title}")

            chapter_content = await self._generate_single_chapter(
                chapter, outline, state, i
            )

            state.generated_chapters.append({
                "order": i,
                "title": chapter.title,
                "content": chapter_content
            })

    async def _generate_single_chapter(
        self, chapter: ChapterOutline, outline: BookOutline, state: PipelineState, chapter_num: int
    ) -> str:
        """生成单章（含审核迭代）"""

        # 准备前序摘要（最近3章）
        previous_summaries = self._get_previous_summaries(state, 3)

        # 初始生成
        content = await self._generate_chapter_draft(
            chapter, outline, state.material_path.read_text(encoding='utf-8'), previous_summaries
        )

        # 迭代修订（最多5轮）
        revision_history = []
        max_rounds = 5

        for round_num in range(1, max_rounds + 1):
            logger.info(f"      审核轮次 {round_num}/{max_rounds}")

            # 使用LLM分析人物关系（动态理解，取代硬编码规则）
            logger.info("         分析人物关系...")
            relationship_analyses = await self._analyze_person_relationships(content, chapter_num)

            # 并行4维度审核（传入关系分析结果）
            review = await self._parallel_review(
                content, chapter, outline, state, previous_summaries, relationship_analyses
            )

            if review.all_passed():
                logger.info(f"      ✓ 全部通过")
                break

            # 检查质量退化
            if len(revision_history) >= 2:
                degradation = self._detect_degradation(revision_history, review)
                if degradation:
                    logger.warning(f"      ⚠ 检测到质量退化: {degradation['type']}")
                    # 回滚到最佳版本
                    best_version = max(revision_history, key=lambda x: x['quality_score'])
                    content = best_version['content']
                    break

            # 累积式修订
            content = await self._revise_chapter(
                content, review, revision_history, chapter, outline
            )

            # 记录历史
            revision_history.append({
                'round': round_num,
                'review': review,
                'content': content,
                'quality_score': review.calculate_score(),
                'word_count': len(content)
            })

        # 保存章节
        chapter_file = state.output_dir / "chapters" / f"{chapter_num:02d}_{chapter.title}.txt"
        chapter_file.parent.mkdir(parents=True, exist_ok=True)

        # 添加章节头部信息
        header = self._make_chapter_header(chapter, revision_history)
        chapter_file.write_text(header + "\n\n" + content, encoding='utf-8')

        # 更新向量存储（用于后续章节的重复检测）
        self.vector_store.add_chapter(
            chapter_num=chapter_num,
            title=chapter.title,
            content=content,
            summary=content[:200],
            key_events=[s.title for s in chapter.sections]
        )

        # 更新事实数据库
        self._update_facts_db(content, chapter, chapter_num)

        return content

    async def _generate_chapter_draft(
        self, chapter: ChapterOutline, outline: BookOutline, material: str, previous_summaries: List[str]
    ) -> str:
        """生成章节初稿"""

        sections_plan = "\n".join([
            f"- 第{s.order}节 [{s.section_type}]: {s.title} (目标{s.target_words}字)\n"
            f"  概要: {s.content_summary}\n"
            f"  {'推断依据: ' + s.inference_basis if s.inference_basis else ''}"
            for s in chapter.sections
        ])

        prompt = f"""你是一位专业的传记作家。请撰写传记的以下章节。

【全书信息】
书名: 《{outline.subject_name}传》
写作风格: 文学性传记，注重场景描写、对话和心理刻画

【前序章节摘要】（保持连贯性）
{chr(10).join(previous_summaries) if previous_summaries else "本章为第一章"}

【本章规划】
章节: {chapter.title}
时间跨度: {chapter.time_range}
目标字数: 约{chapter.target_words}字（参考值，允许±10%浮动，重点是内容充实）

【小节规划】
{sections_plan}

【原始采访素材】（相关片段）
{material[:5000]}...

【写作要求】
1. 严格遵循小节规划，确保每节内容符合标注的类型：
   - factual: 严格基于素材，可增加文学描写但不能编造事实
   - expanded: 在事实骨架上增加场景、对话、心理描写
   - inferred: 合理推断的内容，行文自然不标注，最后统一加脚注※

2. 推断内容写作原则（仅用于inferred小节）：
   - 必须是平淡的日常事件（工作、生活琐事）
   - 必须符合人物年龄、身份、时代背景
   - 不能出现强烈戏剧性（恋爱、冲突、重大转折）
   - 不能与已知事实矛盾
   - 服务于叙事连贯，填补时间空档

3. 文学性要求：
   - 每个场景要有感官细节（视觉、听觉、气味）
   - 通过动作和对话展现人物性格，避免"他很XX"的标签
   - 段落长度有变化，避免通篇短段落或长段落
   - 时代背景自然融入，不要大段背景介绍

4. 禁止事项：
   - 不要出现"待补充"、"此处省略"等占位符
   - 不要套路化描写（"尘埃在光柱中飞舞"等）
   - 不要AI声明（"我为您撰写"等）

【输出】
直接输出章节正文，不需要章节标题（已在文件头部），分节用空行分隔。"""

        response = await self.llm.complete(
            [{"role": "user", "content": prompt}],
            temperature=0.6,
            thinking=True,
            max_tokens=8000,
            timeout=900
        )

        return response

    async def _parallel_review(
        self, content: str, chapter: ChapterOutline, outline: BookOutline,
        state: PipelineState, previous_summaries: List[str],
        relationship_analyses: Optional[Dict] = None
    ) -> ReviewReport:
        """并行4维度审核"""

        material = state.material_path.read_text(encoding='utf-8')

        # 并行执行4个审核
        chapter_num = chapter.order if hasattr(chapter, 'order') else 0
        fact_task = self.fact_checker.review(content, material, chapter)
        continuity_task = self.continuity_checker.review(
            content, chapter, previous_summaries,
            chapter_num=chapter_num,
            facts_db=self.facts_db,
            relationship_analyses=relationship_analyses
        )
        repetition_task = self.repetition_checker.review(content, chapter_num=chapter_num)
        literary_task = self.literary_checker.review(content, chapter)

        fact_result, continuity_result, repetition_result, literary_result = await asyncio.gather(
            fact_task, continuity_task, repetition_task, literary_task,
            return_exceptions=True
        )

        # 处理异常
        results = {}
        for name, result in [
            ("fact", fact_result), ("continuity", continuity_result),
            ("repetition", repetition_result), ("literary", literary_result)
        ]:
            if isinstance(result, Exception):
                logger.warning(f"      {name}审核异常: {result}")
                results[name] = {"passed": False, "error": str(result)}
            else:
                results[name] = result

        return ReviewReport.from_dimension_results(results)

    def _detect_degradation(self, history: List[Dict], current: ReviewReport) -> Optional[Dict]:
        """检测质量退化"""

        if len(history) < 2:
            return None

        scores = [h['quality_score'] for h in history]
        current_score = current.calculate_score()

        # 信号1: 质量分连续下降
        if len(scores) >= 2 and current_score < scores[-1] < scores[-2]:
            return {"type": "score_declining", "scores": scores + [current_score]}

        # 信号2: 问题数量持续增加
        prev_issues = sum(len(h['review'].get_issues()) for h in history[-2:])
        current_issues = len(current.get_issues())
        if current_issues > prev_issues / 2:
            return {"type": "issues_increasing"}

        return None

    async def _revise_chapter(
        self, content: str, review: ReviewReport, history: List[Dict],
        chapter: ChapterOutline, outline: BookOutline
    ) -> str:
        """根据审核报告修订章节"""

        # 构建累积式修改记录
        history_text = ""
        for h in history:
            fixed = h['review'].get_fixed_issues()
            remaining = h['review'].get_remaining_issues()
            history_text += f"\n第{h['round']}轮:\n"
            if fixed:
                history_text += "  已修正: " + ", ".join(fixed) + "\n"
            if remaining:
                history_text += "  仍有问题: " + ", ".join(remaining) + "\n"

        # 当前待修复问题
        current_issues = review.get_issues_by_dimension()

        prompt = f"""你是一位专业的传记编辑。请根据审核意见修订以下章节内容。

【当前章节】
{content}

【修改历史】（请避免重复已修正的问题）
{history_text}

【当前待修复问题】
事实性问题: {current_issues.get('fact', [])}
连贯性问题: {current_issues.get('continuity', [])}
重复性问题: {current_issues.get('repetition', [])}
文学性问题: {current_issues.get('literary', [])}

【修订要求】
1. 保留已有改进，不要回退
2. 针对性修复当前问题列表
3. 不要引入新的问题（如不要为了修复文学性而编造事实）
4. 保持原有字数规模

【输出】
输出完整的修订后章节正文。"""

        response = await self.llm.complete(
            [{"role": "user", "content": prompt}],
            temperature=0.5,
            thinking=True,
            max_tokens=8000,
            timeout=600
        )

        return response

    def _get_previous_summaries(self, state: PipelineState, count: int) -> List[str]:
        """获取前序章节摘要"""
        summaries = []
        for ch in state.generated_chapters[-count:]:
            # 提取每章前500字作为摘要
            content = ch['content'][:500]
            summaries.append(f"《{ch['title']}》: {content}...")
        return summaries

    def _make_chapter_header(self, chapter: ChapterOutline, history: List[Dict]) -> str:
        """生成章节头部信息"""
        actual_words = len(history[-1]['content']) if history else 0
        header = f"""{chapter.title}
时间跨度: {chapter.time_range}
目标字数: 约{chapter.target_words}字（参考值，允许±10%浮动）
实际字数: 约{actual_words}字
修订轮次: {len(history)}轮

小节规划:
"""
        for s in chapter.sections:
            header += f"- 第{s.order}节 [{s.section_type}]: {s.title}\n"
        header += "\n" + "="*60 + "\n"
        return header

    def _update_facts_db(self, content: str, chapter: ChapterOutline, chapter_num: int):
        """更新事实数据库"""
        import re

        # 从章节标题提取时间范围
        time_range = chapter.time_range if hasattr(chapter, 'time_range') else ""
        years = re.findall(r'19\d{2}|20\d{2}', time_range)

        # 添加事件
        for section in chapter.sections:
            # 提取节标题中的关键信息
            section_title = section.title if hasattr(section, 'title') else ""

            # 尝试提取年份
            section_years = re.findall(r'19\d{2}|20\d{2}', section_title)
            event_year = int(section_years[0]) if section_years else (int(years[0]) if years else None)

            self.facts_db.add_event(
                name=section_title,
                year=event_year,
                location="",  # 从内容提取较复杂，暂不提取
                chapter=chapter_num,
                description=section.content_summary if hasattr(section, 'content_summary') else ""
            )

        # 从内容中提取人物（简单规则：2-4个中文字符且出现多次）
        potential_names = re.findall(r'[\u4e00-\u9fa5]{2,4}', content)
        name_counts = {}
        for name in potential_names:
            if name not in ['我们', '他们', '但是', '因为', '所以', '这个', '那个', '什么', '自己']:
                name_counts[name] = name_counts.get(name, 0) + 1

        # 出现多次的可能为人名
        for name, count in name_counts.items():
            if count >= 3:
                self.facts_db.add_person(
                    name=name,
                    relationship="未明确",  # 后续可以改进提取
                    chapter=chapter_num
                )

        # 提取人物关系线索（去世、冲突、和解等）
        self._extract_relationship_clues(content, chapter_num)

        # 从内容中提取地点
        location_patterns = ['市', '省', '县', '镇', '村']
        for pattern in location_patterns:
            locations = re.findall(rf'[\u4e00-\u9fa5]{{1,5}}{pattern}', content)
            for loc in set(locations):  # 去重
                self.facts_db.add_location(
                    name=loc,
                    chapter=chapter_num
                )

        # 保存更新
        self.facts_db.save()

    def _extract_relationship_clues(self, content: str, chapter_num: int):
        """
        提取人物关系线索（取代硬编码状态检测）

        代码只负责提取可能的线索，具体关系理解由LLM完成
        """
        # 关系事件关键词（更丰富的集合）
        clue_keywords = {
            'death': ['去世', '死亡', '病逝', '遇难', '牺牲', '过世', '离世', '辞世', '走了'],
            'breakup': ['断绝关系', '断绝父子关系', '断绝母女关系', '一刀两断', '恩断义绝'],
            'conflict': ['大吵', '争吵', '打架', '冲突', '翻脸', '闹翻', '决裂', '冷战'],
            'reconcile': ['和解', '和好', '原谅', '冰释前嫌', '重修旧好'],
            'departure': ['离开', '出走', '远行', '分手', '离婚', '分居'],
            'reunion': ['重逢', '团聚', '再见', '相遇'],
            ' estrangement': ['疏远', '渐行渐远', '不再来往', '冷淡', '隔阂']
        }

        for person_name in self.facts_db.persons:
            if person_name not in content:
                continue

            # 找到人物在内容中的所有位置
            for match in re.finditer(person_name, content):
                # 获取上下文（前后150字符，更丰富的上下文）
                start = max(0, match.start() - 150)
                end = min(len(content), match.end() + 150)
                context = content[start:end]

                # 检查各类线索
                for clue_type, keywords in clue_keywords.items():
                    for keyword in keywords:
                        if keyword in context:
                            # 添加线索（而非硬编码状态）
                            self.facts_db.add_relationship_clue(
                                name=person_name,
                                chapter=chapter_num,
                                clue_type=clue_type,
                                description=f"{keyword}",
                                context=context[:100]  # 保存部分上下文
                            )

                            # 特殊处理：去世是物理状态，需要额外记录
                            if clue_type == 'death':
                                self.facts_db.update_physical_status(
                                    name=person_name,
                                    status="deceased",
                                    chapter=chapter_num
                                )

                            logger.info(f"   记录关系线索: {person_name} 于第{chapter_num}章 [{clue_type}] {keyword}")
                            break  # 只记录第一个匹配的关键词

    async def _analyze_person_relationships(self, content: str, chapter_num: int) -> Dict[str, Any]:
        """
        使用LLM分析人物关系

        Returns:
            各人物的关系分析结果
        """
        from src.core.relationship_analyzer import PersonRelationshipAnalyzer

        analyzer = PersonRelationshipAnalyzer(self.llm)
        analyses = {}

        for person_name in self.facts_db.persons:
            usage_context = self.facts_db.check_person_usage(person_name, chapter_num)

            analysis = await analyzer.analyze_relationship(
                person_name=person_name,
                chapter=chapter_num,
                relationship_history=usage_context["clues_before"],
                physical_status=usage_context["physical_status"],
                death_chapter=usage_context["death_chapter"],
                current_content=content
            )

            analyses[person_name] = analysis

        return analyses

    async def _assemble_final_book(self, state: PipelineState) -> Path:
        """Phase 7: 终审与组装"""
        logger.info("📚 Phase 7: 终审与组装...")

        # 全局连贯审核
        await self._global_continuity_check(state)

        # 生成推断标注附录
        inferred_notes = await self._generate_inferred_appendix(state)

        # 组装完整传记
        full_content = f"""《{state.outline.subject_name}传》

本书基于采访素材撰写，部分内容（标注※）为基于时代背景和人物经历的合理推断。

{'='*60}

"""

        for ch in state.generated_chapters:
            full_content += f"\n\n{ch['content']}\n\n"
            full_content += "="*60 + "\n"

        # 添加附录
        full_content += "\n\n附录：推断内容说明\n" + "="*60 + "\n\n"
        full_content += inferred_notes

        # 保存完整版
        full_path = state.output_dir / "biography_full.txt"
        full_path.write_text(full_content, encoding='utf-8')

        logger.info(f"   ✓ 完成: {full_path}")
        return full_path

    async def _global_continuity_check(self, state: PipelineState):
        """全局连贯审核"""
        # 简化版：检查章节间衔接
        # 实际实现可以添加更复杂的逻辑
        pass

    async def _generate_inferred_appendix(self, state: PipelineState) -> str:
        """生成推断内容说明附录"""
        # 汇总所有推断内容
        inferred_sections = []
        for ch in state.outline.chapters:
            for s in ch.sections:
                if s.section_type == "inferred":
                    inferred_sections.append(f"- 《{ch.title}》- {s.title}: {s.inference_basis}")

        if not inferred_sections:
            return "本书所有内容均基于采访事实，无推断内容。"

        return "本书以下章节包含基于时代背景和人物经历的合理推断：\n\n" + "\n".join(inferred_sections)
