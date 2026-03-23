"""第五层：审校与输出层 (Review & Output)

提示词模板系统版本：
- 使用Jinja2模板引擎管理审校提示词
- 支持六维并行审查
- 结构化输出格式
"""
import json
import re
import difflib
from typing import List, Dict, Optional, Any, Tuple, Set
from pathlib import Path
from datetime import datetime
from loguru import logger

from src.llm_client import LLMClient
from src.models import (
    GeneratedSection, GeneratedChapter, BookOutline, ChapterOutline,
    Timeline, FactCheckResult, BiographyBook, CharacterProfile
)
from src.utils import save_json, count_chinese_words, sanitize_filename
from src.generator.book_finalizer import BookFinalizer, ChapterVersion
from src.prompt_manager import PromptManager, get_prompt_manager, ContextLevel
from src.observability.runtime_monitor import get_runtime_monitor

# 六维并行审查系统
from src.checkers import (
    ParallelReview, ParallelReviewResult, ReviewDimension,
    quick_review, BaseChecker, ReviewReport, ReviewIssue, IssueSeverity
)


# AI占位符和模板化内容检测规则
AI_PLACEHOLDER_PATTERNS = [
    r'鉴于.*尚待补充',
    r'此处为通用型.*模板',
    r'.*待补充.*',
    r'.*待完善.*',
    r'.*待填写.*',
    r'请补充具体细节',
    r'此处需要展开',
    r'后续补充.*',
    r'章节概要.*待',
    r'内容.*待.*完善',
    r'由于您尚未提供.*',
    r'我为您撰写了一段通用',
    r'适用于多数.*风格',
    r'注：.*为通用型',
    r'示例段落',
    r'模板内容',
    r'占位符',
    r'主旨运用\s*[：:]',
    r'本段功能\s*[：:]',
    r'段落功能\s*[：:]',
    r'转场提示\s*[：:]',
    r'写作提示\s*[：:]',
    r'写作要求\s*[：:]',
    r'本章任务\s*[：:]',
]

# 模板化套话黑名单
TEMPLATE_PHRASES_BLACKLIST = [
    # 光影套路
    '尘埃在光柱中飞舞',
    '尘埃在光柱中起舞',
    '尘埃在光束中',
    '光柱中的尘埃',
    '光束中的尘埃',
    '阳光透过窗户',
    '晨光透过窗户',
    '晨光熹微',
    '夕阳的余晖',
    '夕阳西下',
    '月光如水',
    '月光洒在',
    # 时间套路
    '时光的流逝',
    '时光荏苒',
    '岁月如梭',
    '白驹过隙',
    '转眼间',
    '弹指一挥间',
    '时光飞逝',
    # 喝茶套路
    '苦涩中带着回甘',
    '凉茶早已凉透',
    '凉茶已经凉透',
    '凉茶已经凉',
    '凉茶早已凉',
    '端起茶杯',
    '端起搪瓷杯',
    '端起瓷杯',
    '抿了一口茶',
    # 命运套路
    '命运的齿轮',
    '命运的齿轮悄然转动',
    '命运的齿轮开始转动',
    '历史的车轮',
    '时代的列车',
    # 悬念套路
    '暴风雨前的宁静',
    '真相正伺机而动',
    '真相伺机而动',
    '暗流涌动',
    '风暴正在酝酿',
    # 场景套路
    '桌上摊开的文件',
    '摊开的文件',
    '一叠文件',
    '摊开的资料',
    '点了一根烟',
    '点燃一支烟',
    '烟雾缭绕',
    '望着远方',
    '看着窗外',
    '望向窗外',
    # 心理套路
    '陷入了沉思',
    '陷入沉思',
    '陷入了深深的沉思',
    '百感交集',
    '心中充满',
    '倍感欣慰',
    '深感',
    '由衷地',
    '发自内心',
    '情不自禁地',
    # 空泛套路
    '关系着民生冷暖',
    '肩上担子很重',
    '肩上的担子',
    '这是一个特殊的年代',
    '那是一个特殊的年代',
    '重要的决定',
    '历史的洪流',
    '时代的浪潮',
    '风云变幻',
    '波澜壮阔',
    '跌宕起伏',
    '不平凡',
    '意义重大',
    '深刻影响',
] + [
    # 变体模式（用于正则匹配）
    r'尘埃.*光.*舞',
    r'光.*尘埃',
    r'苦.*甘',
    r'甘.*苦',
]

# 空洞悬念表达
EMPTY_SUSPENSE_PHRASES = [
    '但他不知道的是',
    '然而他不知道',
    '没人能想到',
    '谁也没想到',
    '没人想到',
    '谁也想不到',
    '命运的齿轮',
    '风暴正在酝酿',
    '暗流涌动',
    '更大的挑战',
    '等待着他的',
    '未来充满了未知',
    '前方的路还很长',
    '这一切只是开始',
]

# 过渡套话
TRANSITION_CLICHES = [
    '不仅如此',
    '更重要的是',
    '值得一提的是',
    '令人深思的是',
    '无独有偶',
    '正所谓',
    '古人云',
    '常言道',
    '俗话说',
    '时光倒流到',
    '把时间拨回到',
    '让我们回到',
    '回到.*年前',
    '在那个年代',
    '在那个时期',
]

# 情感标签堆砌
EMOTION_LABELS = [
    '感到无比',
    '心中充满',
    '充满.*情感',
    '充满.*情绪',
    '倍感',
    '深感',
    '深切地',
    '由衷地',
    '发自内心',
    '情不自禁地',
    '难以抑制',
    '眼眶湿润',
    '热泪盈眶',
    '热泪盈眶',
]

# 语义级套话模式（正则）
SEMANTIC_TEMPLATE_PATTERNS = [
    (r'尘埃.*光.*舞|光.*尘埃|光柱.*尘|光束.*尘', "光柱尘埃意象"),
    (r'苦.*甘|甘.*苦|先苦.*后甜', "苦尽甘来变体"),
    (r'命运.*齿轮|齿轮.*命运|命运.*转动|命运.*交织', "命运齿轮变体"),
    (r'滴答|咔嚓.*声|钟表.*声|秒针.*走|时间.*走', "钟表声意象"),
    (r'端起.*杯|拿起.*杯|喝.*茶|喝.*水|抿.*茶', "喝茶喝水套路"),
    (r'望着.*窗外|看向.*窗外|窗外.*景|窗外.*树', "窗外套路"),
    (r'点.*烟|抽.*烟|烟雾.*缭绕|烟圈.*升起', "抽烟套路"),
    (r'陷入.*沉思|沉思.*片刻|默.*语|久.*不语', "沉思套路"),
    (r'微.*笑|嘴角.*扬|眼.*神|目.*光', "神态套路（过度使用）"),
]


class ContentQualityChecker:
    """内容质量检查器 - 检测AI占位符和模板化内容"""
    
    def __init__(self):
        self.placeholder_pattern = re.compile('|'.join(AI_PLACEHOLDER_PATTERNS), re.IGNORECASE)
    
    def check_content_quality(self, section: GeneratedSection) -> List[Dict]:
        """
        检查内容质量问题
        
        Returns:
            违规项列表
        """
        violations = []
        content = section.content
        
        # 1. 检测AI占位符
        placeholder_violations = self._check_placeholders(content)
        violations.extend(placeholder_violations)
        
        # 2. 检测模板化内容
        template_violations = self._check_template_phrases(content)
        violations.extend(template_violations)
        
        # 3. 检测空洞悬念
        suspense_violations = self._check_empty_suspense(content)
        violations.extend(suspense_violations)
        
        # 4. 检测内容实质性
        substance_violations = self._check_content_substance(content)
        violations.extend(substance_violations)
        
        # 5. 检测重复意象
        imagery_violations = self._check_repetitive_imagery(content)
        violations.extend(imagery_violations)
        
        return violations
    
    def _check_placeholders(self, content: str) -> List[Dict]:
        """检测AI占位符残留"""
        violations = []
        
        matches = self.placeholder_pattern.findall(content)
        if matches:
            # 去重并限制报告数量
            unique_matches = list(set(matches))[:3]
            violations.append({
                "type": "AI占位符残留",
                "description": f"发现AI生成占位符: {', '.join(unique_matches)}",
                "severity": "high"
            })
        
        return violations
    
    def _check_template_phrases(self, content: str) -> List[Dict]:
        """检测模板化套话（增强版）"""
        violations = []
        found_phrases = []
        
        # 1. 精确匹配检测
        for phrase in TEMPLATE_PHRASES_BLACKLIST:
            if isinstance(phrase, str) and phrase in content:
                found_phrases.append(phrase)
        
        # 2. 语义级模式检测（正则）
        semantic_matches = []
        for pattern, desc in SEMANTIC_TEMPLATE_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                semantic_matches.append(desc)
        
        # 3. 过渡套话检测
        transition_matches = []
        for phrase in TRANSITION_CLICHES:
            if phrase in content:
                transition_matches.append(phrase)
        
        # 4. 情感标签检测
        emotion_matches = []
        for pattern in EMOTION_LABELS:
            matches = re.findall(pattern, content)
            if matches:
                emotion_matches.extend(matches)
        
        # 合并所有发现
        all_issues = found_phrases + semantic_matches + transition_matches + emotion_matches
        
        # 降低阈值：只要发现1个就警告
        if len(found_phrases) >= 1:
            violations.append({
                "type": "模板化套话",
                "description": f"发现{len(found_phrases)}个套路化表达: {', '.join(found_phrases[:3])}",
                "severity": "medium"
            })
        
        if semantic_matches:
            violations.append({
                "type": "语义级套话",
                "description": f"发现语义套路: {', '.join(list(set(semantic_matches))[:3])}",
                "severity": "low"
            })
        
        if len(transition_matches) >= 2:
            violations.append({
                "type": "过渡套话",
                "description": f"过度使用过渡句式: {', '.join(transition_matches[:3])}",
                "severity": "low"
            })
        
        if len(emotion_matches) >= 3:
            violations.append({
                "type": "情感标签堆砌",
                "description": f"使用过多情感标签({len(emotion_matches)}处): {', '.join(list(set(emotion_matches))[:3])}",
                "severity": "medium"
            })
        
        return violations
    
    def _check_empty_suspense(self, content: str) -> List[Dict]:
        """检测空洞的悬念设置（全文检测）"""
        violations = []
        
        # 全文检测空洞悬念
        found_suspense = []
        for phrase in EMPTY_SUSPENSE_PHRASES:
            if phrase in content:
                found_suspense.append(phrase)
        
        # 检查章节结尾是否有空洞悬念（加重处罚）
        last_paragraph = content.split('\n\n')[-1] if '\n\n' in content else content[-200:]
        ending_suspense = []
        for phrase in EMPTY_SUSPENSE_PHRASES:
            if phrase in last_paragraph:
                ending_suspense.append(phrase)
        
        if ending_suspense:
            violations.append({
                "type": "空洞悬念",
                "description": f"章节结尾使用套路化悬念: {', '.join(ending_suspense[:2])}",
                "severity": "medium"
            })
        elif found_suspense:
            # 非结尾处使用空洞悬念（轻度警告）
            violations.append({
                "type": "空洞悬念",
                "description": f"文中使用套路化悬念表达: {', '.join(found_suspense[:2])}",
                "severity": "low"
            })
        
        return violations
    
    def _check_content_substance(self, content: str) -> List[Dict]:
        """检测内容实质性"""
        violations = []
        
        # 检查是否有足够的具体细节
        # 1. 对话内容
        dialogue_pattern = r'["""「『].*?["""」』]'
        dialogues = re.findall(dialogue_pattern, content)
        dialogue_ratio = sum(len(d) for d in dialogues) / len(content) if content else 0
        
        if dialogue_ratio < 0.03:  # 对话内容少于3%
            violations.append({
                "type": "内容空洞",
                "description": "缺乏人物对话，内容以叙述为主，缺少生动细节",
                "severity": "low"
            })
        
        # 2. 具体数字和时间
        numbers = re.findall(r'\d+年|\d+岁|\d+元|\d+月|\d+日', content)
        if len(numbers) < 3:
            violations.append({
                "type": "缺乏具体信息",
                "description": "内容中缺乏具体的时间、数字等可核实信息",
                "severity": "medium"
            })
        
        # 3. 检查空泛形容词堆砌
        vague_adjectives = ['非常', '特别', '很', '十分', '相当', '特别地']
        vague_count = sum(content.count(adj) for adj in vague_adjectives)
        if vague_count > len(content) / 100:  # 平均每100字有一个空泛形容词
            violations.append({
                "type": "语言空泛",
                "description": f"使用过多空泛形容词（{vague_count}处），建议用具体细节替代",
                "severity": "low"
            })
        
        return violations
    
    def _check_repetitive_imagery(self, content: str) -> List[Dict]:
        """检测重复意象"""
        violations = []
        
        repetitive_patterns = [
            (r'晨光|晨光熹微|晨光透过|清晨.*阳光|早晨.*阳光', "晨光/阳光"),
            (r'夕阳|夕阳西下|落日|黄昏|傍晚', "夕阳/黄昏"),
            (r'凉茶|茶水|茶杯|喝茶|饮茶', "喝茶"),
            (r'挂钟|钟表|时钟|滴答|咔嚓', "钟表"),
            (r'钢笔|笔尖|写字|书写|沙沙', "写字/钢笔"),
            (r'窗外|看着窗外|望向窗外|窗外.*树', "窗外"),
            (r'文件|桌上.*文件|摊开的.*纸', "文件/纸张"),
        ]
        
        for pattern, desc in repetitive_patterns:
            matches = re.findall(pattern, content)
            if len(matches) > 2:
                violations.append({
                    "type": "意象重复",
                    "description": f"'{desc}'意象重复出现{len(matches)}次，建议多样化描写",
                    "severity": "low"
                })
        
        return violations


class ContentRepetitionChecker:
    """内容重复检查器"""
    
    def check_repetition(self, section: GeneratedSection) -> List[Dict]:
        """检查内容内部重复"""
        violations = []
        content = section.content
        
        # 1. 段落级重复检测
        paragraphs = [p.strip() for p in content.split('\n\n') if len(p.strip()) > 30]
        
        for i, p1 in enumerate(paragraphs):
            for p2 in paragraphs[i+1:]:
                similarity = self._calculate_similarity(p1, p2)
                if similarity > 0.75:  # 75%相似度阈值
                    violations.append({
                        "type": "内容重复",
                        "description": f"发现高度相似的段落（相似度{similarity:.0%}）",
                        "severity": "medium"
                    })
                    break
        
        # 2. 句子级重复检测
        sentences = re.split(r'[。！？]', content)
        sentence_hashes = {}
        
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 10:
                continue
            
            # 简化的句子指纹
            fingerprint = sent[:20]
            if fingerprint in sentence_hashes:
                violations.append({
                    "type": "句子重复",
                    "description": f"发现重复或高度相似的句子: '{sent[:30]}...'",
                    "severity": "low"
                })
            else:
                sentence_hashes[fingerprint] = True
        
        return violations
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两段文本的相似度"""
        return difflib.SequenceMatcher(None, text1, text2).ratio()
    
    def check_cross_chapter_repetition(
        self,
        current_section: GeneratedSection,
        previous_sections: List[GeneratedSection]
    ) -> List[Dict]:
        """检查跨章节重复"""
        violations = []
        current_content = current_section.content
        
        # 只检查最近的3个章节
        for prev in previous_sections[-3:]:
            similarity = self._calculate_similarity(current_content, prev.content)
            if similarity > 0.6:  # 60%相似度阈值
                violations.append({
                    "type": "跨章节重复",
                    "description": f"与章节'{prev.title}'内容相似度达{similarity:.0%}，可能存在重复叙述",
                    "severity": "high"
                })
                break
        
        return violations


class CrossChapterConsistencyChecker:
    """跨章节一致性检查器 - 专门处理超长文本的一致性问题"""

    def __init__(self, llm: LLMClient):
        self.llm = llm
        # 跨章节记忆：人物状态、已发生事件、已建立的事实
        self._character_states: Dict[str, Dict] = {}
        self._established_facts: List[Dict] = []
        self._previous_chapters_summary: List[str] = []

    def update_from_chapter(self, chapter: GeneratedChapter):
        """从已完成的章节更新状态"""
        # 提取章节摘要
        chapter_summary = f"第{chapter.outline.order}章《{chapter.outline.title}》：{chapter.outline.summary}"
        self._previous_chapters_summary.append(chapter_summary)

        # 保持最近10章的摘要
        if len(self._previous_chapters_summary) > 10:
            self._previous_chapters_summary = self._previous_chapters_summary[-10:]

    async def check_cross_chapter_consistency(
        self,
        current_chapter: GeneratedChapter,
        previous_chapter: Optional[GeneratedChapter] = None
    ) -> List[Dict]:
        """
        检查跨章节一致性

        Returns:
            违规项列表
        """
        violations = []

        if not previous_chapter:
            return violations

        current_content = current_chapter.full_content
        previous_content = previous_chapter.full_content[-2000:]  # 前一章末尾2000字

        prompt = f"""请检查两章之间的 consistency（一致性）：

=== 前一章结尾（约2000字）===
{previous_content}

=== 当前章开头（约2000字）===
{current_content[:2000]}

=== 检查维度 ===
1. 【时间连续性】两章之间的时间间隔是否合理？是否有时间跳跃未说明？
2. 【人物状态一致性】人物在前一章的状态（情绪、位置、关系）是否与当前章一致？
3. 【情节连贯性】前一章的情节是否在当前章有合理延续？
4. 【称谓一致性】人物称谓是否保持一致？
5. 【背景信息一致性】时代背景、环境描写是否一致？

请以JSON格式返回发现的问题（如无问题返回空列表）：
[
  {{
    "type": "人物状态不一致/时间跳跃/情节断层/称谓不一致",
    "description": "具体问题描述",
    "severity": "high/medium/low"
  }}
]"""

        messages = [
            {"role": "system", "content": "你是一位严格的一致性审查编辑，专门检测跨章节的矛盾和断层。"},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self.llm.complete(messages, temperature=0.3)
            issues = self._parse_json_array(response)

            for issue in issues:
                violations.append({
                    "type": issue.get("type", "跨章节不一致"),
                    "description": issue.get("description", ""),
                    "severity": issue.get("severity", "medium")
                })

        except Exception as e:
            logger.warning(f"跨章节一致性检查失败: {e}")

        return violations

    async def generate_chapter_transition(
        self,
        previous_chapter: GeneratedChapter,
        current_chapter_outline: ChapterOutline
    ) -> str:
        """生成章节间过渡段落"""
        prompt = f"""请为两章之间生成一个过渡段落（100-200字）：

=== 前一章信息 ===
标题：{previous_chapter.outline.title}
摘要：{previous_chapter.outline.summary}
结尾摘要：{previous_chapter.sections[-1].content[-300:] if previous_chapter.sections else ""}

=== 当前章信息 ===
标题：{current_chapter_outline.title}
时间范围：{current_chapter_outline.time_period_start or '待定'} 至 {current_chapter_outline.time_period_end or '待定'}
摘要：{current_chapter_outline.summary}

=== 要求 ===
1. 自然衔接两章内容
2. 简要说明时间过渡
3. 为当前章的主题做铺垫
4. 不要制造虚假的悬念
"""

        messages = [
            {"role": "system", "content": "你是一位擅长过渡写作的编辑。"},
            {"role": "user", "content": prompt}
        ]

        try:
            transition = await self.llm.complete(messages, temperature=0.6)
            return transition.strip()
        except Exception as e:
            logger.error(f"生成过渡段落失败: {e}")
            return ""

    def _parse_json_array(self, text: str) -> List:
        """解析JSON数组"""
        try:
            return json.loads(text)
        except:
            pass

        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass

        return []


class ConsistencyChecker:
    """一致性校验Agent"""
    
    def __init__(self, llm: LLMClient, timeline: Timeline, vector_store: Optional[Any] = None):
        self.llm = llm
        self.timeline = timeline
        self.vector_store = vector_store
        self.subject_name = timeline.subject.name if timeline.subject else "传主"
        self.quality_checker = ContentQualityChecker()
        self.repetition_checker = ContentRepetitionChecker()
        self.runtime_monitor = get_runtime_monitor(project_root=Path(__file__).resolve().parents[2])
        self._fact_query_rewrite_mode: bool = False
        self._last_claim_reports: Dict[str, Dict[str, Any]] = {}
        self._timeline_score_floor = 0.30  # 降低门槛，允许更多证据通过

    def set_fact_check_mode(self, query_rewrite: bool = False) -> None:
        """设置事实核查模式（用于停滞时动态切换策略）。"""
        self._fact_query_rewrite_mode = query_rewrite

    def get_last_claim_report(self, section_id: str) -> Optional[Dict[str, Any]]:
        """获取最近一次claim核查报告。"""
        return self._last_claim_reports.get(section_id)
    
    async def check_section(
        self,
        section: GeneratedSection,
        chapter_context: Dict
    ) -> FactCheckResult:
        """
        检查单节内容的一致性
        """
        violations = []
        
        # 1. 内容质量检查（新增）
        quality_violations = self.quality_checker.check_content_quality(section)
        violations.extend(quality_violations)
        
        # 2. 内容重复检查（新增）
        repetition_violations = self.repetition_checker.check_repetition(section)
        violations.extend(repetition_violations)
        
        # 3. 基础事实核查
        fact_violations = await self._check_facts(section)
        violations.extend(fact_violations)
        
        # 4. 时间线核查
        time_violations = await self._check_timeline(section, chapter_context)
        violations.extend(time_violations)
        
        # 5. 人物关系核查
        char_violations = await self._check_characters(section)
        violations.extend(char_violations)
        
        # 6. 逻辑一致性核查
        logic_violations = await self._check_logic(section)
        violations.extend(logic_violations)
        
        is_consistent = len([v for v in violations if v.get("severity") == "high"]) == 0
        
        return FactCheckResult(
            section_id=section.id,
            is_consistent=is_consistent,
            violations=violations,
            suggestions=self._generate_suggestions(violations),
            confidence=max(0.0, min(1.0, 1.0 - (len(violations) * 0.05)))
        )
    
    async def _check_facts(self, section: GeneratedSection) -> List[Dict]:
        """Claim级事实核查：拆claim -> 检索证据 -> 逐claim判定。"""
        content = section.content
        violations: List[Dict[str, Any]] = []

        claims = await self._extract_checkable_claims(content)
        if not claims:
            return violations

        claim_payloads: List[Dict[str, Any]] = []
        for claim in claims[:12]:
            evidences = self._retrieve_claim_evidence(claim, top_k=3)
            claim_payloads.append(
                {
                    "claim_id": claim["claim_id"],
                    "claim_text": claim["claim_text"],
                    "sentence_fragment": claim.get("sentence_fragment", ""),
                    "evidence_candidates": evidences,
                }
            )

        verdicts = await self._verify_claims_batch(claim_payloads)
        verdict_map = {v["claim_id"]: v for v in verdicts}

        structured_results: List[Dict[str, Any]] = []
        for payload in claim_payloads:
            claim_id = payload["claim_id"]
            verdict = verdict_map.get(
                claim_id,
                {
                    "claim_id": claim_id,
                    "verdict": "insufficient",
                    "evidence_snippet": "证据不足",
                    "confidence": 0.0,
                    "failure_reason": "模型未返回该claim的核查结果",
                },
            )
            structured_results.append(verdict)

            claim_text = payload["claim_text"]
            sentence_fragment = payload.get("sentence_fragment", "")
            confidence = float(verdict.get("confidence", 0.0))
            verdict_type = verdict.get("verdict", "insufficient")
            failure_reason = verdict.get("failure_reason", "")
            evidence_snippet = verdict.get("evidence_snippet", "")

            # 降低阈值：confidence >= 0.45 即认为可接受
            if verdict_type == "supported" and confidence >= 0.45:
                continue

            issue_type = "事实冲突" if verdict_type == "contradicted" else "证据不足"
            severity = "high" if verdict_type == "contradicted" or confidence < 0.45 else "medium"
            violations.append(
                {
                    "type": "事实核查-Claim失败",
                    "description": f"[{claim_id}] {issue_type}：{failure_reason or '缺少可验证证据'}",
                    "severity": severity,
                    "claim_id": claim_id,
                    "claim_text": claim_text,
                    "sentence_fragment": sentence_fragment or claim_text[:80],
                    "evidence_snippet": evidence_snippet,
                    "confidence": confidence,
                    "failure_reason": failure_reason or "证据不足",
                    "verdict": verdict_type,
                    "check_scope": "claim",
                }
            )

        report = {
            "section_id": section.id,
            "query_rewrite_mode": self._fact_query_rewrite_mode,
            "claims": claim_payloads,
            "results": structured_results,
            "generated_at": datetime.now().isoformat(),
            "required_schema": [
                "claim_id",
                "evidence_snippet",
                "confidence",
                "failure_reason",
            ],
        }
        self._last_claim_reports[section.id] = report
        self.runtime_monitor.save_json_artifact(
            name=f"fact_claims_{sanitize_filename(section.id)}.json",
            data=report,
            stage="05_review",
        )

        return violations

    async def _extract_checkable_claims(self, content: str) -> List[Dict[str, str]]:
        """拆解文本中的可核查claim。"""
        prompt = f"""请从以下文本中提取“可核查事实claim”，只保留可被采访素材验证的陈述。

=== 文本 ===
{content[:2200]}

必须输出JSON对象（禁止输出解释）：
{{
  "claims": [
    {{
      "claim_id": "C1",
      "claim_text": "完整claim",
      "sentence_fragment": "claim所在原句片段"
    }}
  ]
}}

要求：
1. claim_id 必须连续编号 C1, C2, C3...
2. 每条claim必须是“可核查的事实”，不要主观感受
3. 最多返回12条
"""
        try:
            response = await self.llm.complete(
                [
                    {"role": "system", "content": "你是事实抽取器，只输出JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=16384,
            )
            payload = self._extract_json_object(response)
            raw_claims = payload.get("claims", []) if isinstance(payload, dict) else []
            claims = self._sanitize_claims(raw_claims)
            if claims:
                return claims[:12]
        except Exception as exc:
            logger.warning(f"claim提取失败，回退规则抽取: {exc}")

        return self._fallback_claim_extraction(content)

    def _sanitize_claims(self, raw_claims: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        claims: List[Dict[str, str]] = []
        for idx, item in enumerate(raw_claims, 1):
            if not isinstance(item, dict):
                continue
            claim_text = str(item.get("claim_text", "")).strip()
            if len(claim_text) < 8:
                continue
            sentence_fragment = str(item.get("sentence_fragment", "")).strip() or claim_text[:80]
            claims.append(
                {
                    "claim_id": f"C{idx}",
                    "claim_text": claim_text[:220],
                    "sentence_fragment": sentence_fragment[:120],
                }
            )
        return claims

    def _fallback_claim_extraction(self, content: str) -> List[Dict[str, str]]:
        """模型抽取失败时，规则兜底。"""
        fragments = re.split(r"[。！？\n]+", content)
        candidates: List[str] = []
        for fragment in fragments:
            sentence = fragment.strip()
            if len(sentence) < 10:
                continue
            is_fact_like = bool(
                re.search(r"\d{4}年|\d+岁|\d+月|\d+日|在[\u4e00-\u9fff]{2,8}(?:市|县|镇|村)", sentence)
            ) or len(re.findall(r"[\u4e00-\u9fff]{2,4}", sentence)) >= 3
            if is_fact_like:
                candidates.append(sentence)
            if len(candidates) >= 12:
                break

        if not candidates:
            candidates = [s.strip() for s in fragments if len(s.strip()) >= 12][:6]

        return [
            {
                "claim_id": f"C{i + 1}",
                "claim_text": c[:220],
                "sentence_fragment": c[:120],
            }
            for i, c in enumerate(candidates)
        ]

    def _retrieve_claim_evidence(self, claim: Dict[str, str], top_k: int = 3) -> List[Dict[str, Any]]:
        """双通道检索证据：timeline优先，弱召回时回退到向量库原始采访块。"""
        claim_text = claim.get("claim_text", "")
        if not claim_text:
            return []

        query_text = self._rewrite_claim_query(claim_text) if self._fact_query_rewrite_mode else claim_text
        timeline_scored: List[Tuple[float, Dict[str, Any]]] = []

        for event in self.timeline.events:
            evidence_text_parts = [
                event.title or "",
                event.description or "",
                event.scene_description or "",
                event.source_text or "",
                event.date or "",
                event.location or "",
                " ".join(event.characters_involved[:5]) if event.characters_involved else "",
            ]
            evidence_text = " ".join([p for p in evidence_text_parts if p]).strip()
            if not evidence_text:
                continue

            score = self._score_evidence_match(query_text, evidence_text)
            if score <= 0:
                continue

            snippet_source = event.source_text or event.description or event.title
            snippet = snippet_source[:220] if snippet_source else ""
            timeline_scored.append(
                (
                    score,
                    {
                        "event_id": event.id,
                        "title": event.title,
                        "date": event.date,
                        "source_material_id": event.source_material_id,
                        "snippet": snippet,
                        "score": round(score, 4),
                        "source_channel": "timeline",
                    },
                )
            )

        timeline_scored.sort(key=lambda x: x[0], reverse=True)
        timeline_evidence = [item for _, item in timeline_scored[:top_k]]
        max_timeline_score = max((self._safe_float(e.get("score", 0.0)) for e in timeline_evidence), default=0.0)

        need_fallback = (
            not timeline_evidence
            or len(timeline_evidence) < top_k
            or max_timeline_score < self._timeline_score_floor
        )

        combined = list(timeline_evidence)
        if need_fallback:
            fallback_evidence = self._retrieve_claim_evidence_from_vector_store(query_text, top_k=max(5, top_k))
            if fallback_evidence:
                combined.extend(fallback_evidence)
                self.runtime_monitor.log_event(
                    stage="review.fact_retrieval",
                    status="running",
                    message="timeline证据弱召回，已回退向量库检索",
                    metadata={
                        "claim_text": claim_text[:120],
                        "timeline_max_score": round(max_timeline_score, 4),
                        "fallback_count": len(fallback_evidence),
                    },
                )

        deduped = self._dedup_evidence_candidates(combined)
        deduped.sort(key=lambda item: self._safe_float(item.get("score", 0.0)), reverse=True)
        return deduped[:top_k]

    def _retrieve_claim_evidence_from_vector_store(self, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not self.vector_store:
            return []
        try:
            results = self.vector_store.search(query_text, n_results=max(top_k * 2, 6))
        except Exception as exc:
            logger.warning(f"向量库证据检索失败: {exc}")
            return []

        evidence: List[Dict[str, Any]] = []
        for material, score in results:
            try:
                score_value = float(score)
            except Exception:
                score_value = 0.0
            score_value = max(0.0, min(1.0, score_value))
            content = str(getattr(material, "content", "")).strip()
            if not content:
                continue
            snippet = self._extract_relevant_snippet(query_text, content, max_len=220)
            evidence.append(
                {
                    "event_id": None,
                    "title": f"采访素材#{getattr(material, 'chunk_index', 0)}",
                    "date": None,
                    "source_material_id": getattr(material, "id", ""),
                    "source_file": getattr(material, "source_file", ""),
                    "snippet": snippet,
                    "score": round(score_value, 4),
                    "source_channel": "vector_store",
                }
            )
            if len(evidence) >= top_k:
                break
        return evidence

    def _extract_relevant_snippet(self, query: str, content: str, max_len: int = 220) -> str:
        normalized = re.sub(r"\s+", " ", content).strip()
        if len(normalized) <= max_len:
            return normalized

        tokens = re.findall(r"\d{4}年|\d+岁|[\u4e00-\u9fff]{2,6}", query)
        first_hit = -1
        for token in tokens:
            if not token:
                continue
            idx = normalized.find(token)
            if idx >= 0 and (first_hit < 0 or idx < first_hit):
                first_hit = idx

        if first_hit < 0:
            return normalized[:max_len]

        start = max(0, first_hit - 45)
        end = min(len(normalized), start + max_len)
        return normalized[start:end]

    def _dedup_evidence_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for item in candidates:
            snippet = str(item.get("snippet", "")).strip()
            source_id = str(item.get("source_material_id", "") or item.get("event_id", ""))
            signature = f"{source_id}|{snippet[:120]}"
            if not snippet or signature in seen:
                continue
            seen.add(signature)
            deduped.append(item)
        return deduped

    def _rewrite_claim_query(self, claim_text: str) -> str:
        """停滞时改写检索查询，扩大召回。"""
        time_tokens = re.findall(r"\d{4}年|\d+岁|\d+月|\d+日", claim_text)
        zh_tokens = re.findall(r"[\u4e00-\u9fff]{2,6}", claim_text)
        dedup: List[str] = []
        for tok in time_tokens + zh_tokens:
            if tok not in dedup:
                dedup.append(tok)
        return " ".join(dedup[:10]) if dedup else claim_text

    def _score_evidence_match(self, query: str, evidence_text: str) -> float:
        """启发式证据相关度评分。"""
        if not query or not evidence_text:
            return 0.0
        query_tokens = set(re.findall(r"\d{4}年|\d+岁|[\u4e00-\u9fff]{2,6}", query))
        if not query_tokens:
            return 0.0

        overlap = sum(1 for token in query_tokens if token in evidence_text)
        coverage = overlap / max(1, len(query_tokens))
        sequence_ratio = difflib.SequenceMatcher(None, query[:180], evidence_text[:240]).ratio()

        year_bonus = 0.0
        for year in re.findall(r"\d{4}", query):
            if year in evidence_text:
                year_bonus = 0.12
                break

        return min(1.0, coverage * 0.62 + sequence_ratio * 0.38 + year_bonus)

    async def _verify_claims_batch(self, claim_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量判定claim是否被证据支持，输出强结构化JSON。"""
        if not claim_payloads:
            return []

        schema_hint = {
            "results": [
                {
                    "claim_id": "C1",
                    "verdict": "supported|contradicted|insufficient",
                    "evidence_snippet": "证据片段",
                    "confidence": 0.0,
                    "failure_reason": "",
                }
            ]
        }
        prompt = f"""你是事实核查器。请严格按JSON返回，不要输出任何解释。

输出JSON Schema（必须包含以下字段）：
{json.dumps(schema_hint, ensure_ascii=False, indent=2)}

判定规则：
1. 若证据支持claim，verdict= supported，failure_reason 置空字符串
2. 若证据与claim冲突，verdict= contradicted，并说明failure_reason
3. 若证据不足，verdict= insufficient，并说明failure_reason
4. confidence 必须是0~1的数字
5. 每条claim必须返回一条结果；claim_id 必须和输入一致
6. evidence_snippet 必须来自候选证据摘要，不能编造

待核查数据：
{json.dumps(claim_payloads, ensure_ascii=False)}
"""
        try:
            response = await self.llm.complete(
                [
                    {"role": "system", "content": "你是严谨的事实核查模型，输出必须是合法JSON对象。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=16384,
            )
            payload = self._extract_json_object(response)
            raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        except Exception as exc:
            logger.warning(f"claim批量核查失败: {exc}")
            raw_results = []

        raw_map: Dict[str, Dict[str, Any]] = {}
        for item in raw_results:
            if isinstance(item, dict):
                cid = str(item.get("claim_id", "")).strip()
                if cid:
                    raw_map[cid] = item

        sanitized: List[Dict[str, Any]] = []
        for payload in claim_payloads:
            claim_id = payload["claim_id"]
            candidate = raw_map.get(claim_id, {})
            sanitized.append(self._sanitize_claim_verdict(claim_id, candidate))
        return sanitized

    def _sanitize_claim_verdict(self, claim_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        verdict_raw = str(raw.get("verdict", "insufficient")).strip().lower()
        verdict = verdict_raw if verdict_raw in {"supported", "contradicted", "insufficient"} else "insufficient"

        confidence_raw = raw.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        evidence_snippet = str(raw.get("evidence_snippet", "")).strip()
        if not evidence_snippet:
            evidence_snippet = "证据不足"

        failure_reason = str(raw.get("failure_reason", "")).strip()
        if verdict != "supported" and not failure_reason:
            failure_reason = "证据不足或与素材冲突"
        if verdict == "supported":
            failure_reason = ""

        return {
            "claim_id": claim_id,
            "verdict": verdict,
            "evidence_snippet": evidence_snippet[:240],
            "confidence": confidence,
            "failure_reason": failure_reason[:180],
        }

    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"results": parsed}
        except Exception:
            pass

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return {}

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default
    
    async def _check_timeline(
        self,
        section: GeneratedSection,
        chapter_context: Dict
    ) -> List[Dict]:
        """检查时间线一致性"""
        violations = []
        content = section.content
        
        # 提取章节时间范围
        chapter_start = chapter_context.get("time_period_start")
        chapter_end = chapter_context.get("time_period_end")
        
        # 从内容中提取时间提及
        time_pattern = r'(\d{4})年'
        mentioned_years = set(re.findall(time_pattern, content))
        
        if chapter_start and chapter_end:
            chapter_start_year = chapter_start[:4] if len(chapter_start) >= 4 else chapter_start
            chapter_end_year = chapter_end[:4] if len(chapter_end) >= 4 else chapter_end
            
            for year in mentioned_years:
                if year < chapter_start_year or year > chapter_end_year:
                    violations.append({
                        "type": "时间线异常",
                        "description": f"内容提及了{year}年，超出本章时间范围({chapter_start_year}-{chapter_end_year})",
                        "severity": "medium"
                    })
        
        return violations
    
    async def _check_characters(self, section: GeneratedSection) -> List[Dict]:
        """检查人物一致性"""
        violations = []
        content = section.content
        
        # 获取已知人物列表
        known_characters = set()
        for event in self.timeline.events:
            known_characters.update(event.characters_involved)
        
        # 提取内容中的人物（简单规则）
        potential_characters = set(re.findall(r'[\u4e00-\u9fff]{2,4}(?=说|道|问|答|笑|哭)', content))
        
        # 检查是否有新人物首次出现但没有介绍
        new_characters = potential_characters - known_characters - {self.subject_name}
        
        if new_characters:
            # 过滤掉常见词汇
            common_words = {"之后", "当时", "后来", "然后", "因为", "所以", "虽然", "但是", "不过", "可是", "父亲", "母亲", "妻子", "丈夫", "儿子", "女儿"}
            new_characters = new_characters - common_words
            
            if new_characters:
                violations.append({
                    "type": "人物一致性",
                    "description": f"发现未记录的人物: {', '.join(list(new_characters)[:3])}",
                    "severity": "high"
                })
        
        return violations
    
    async def _check_logic(self, section: GeneratedSection) -> List[Dict]:
        """检查逻辑一致性"""
        violations = []
        content = section.content
        
        # 简单的逻辑检查
        # 1. 检查年龄计算
        age_pattern = r'(\d{2})岁'
        ages = re.findall(age_pattern, content)
        if len(ages) > 1:
            age_ints = [int(a) for a in ages]
            if max(age_ints) - min(age_ints) > 5:
                violations.append({
                    "type": "逻辑一致性",
                    "description": f"同一段落内年龄从{min(age_ints)}岁跳到{max(age_ints)}岁，可能存在时间混乱",
                    "severity": "medium"
                })
        
        return violations
    
    def _generate_suggestions(self, violations: List[Dict]) -> List[str]:
        """基于违规项生成修改建议"""
        suggestions = []
        
        for v in violations:
            vtype = v.get("type", "")
            if "占位符" in vtype or "模板" in vtype:
                suggestions.append("删除所有AI占位符和套路化表达，补充具体细节")
            elif "重复" in vtype:
                suggestions.append("删除重复内容，保持叙述简洁")
            elif "空洞" in vtype:
                suggestions.append("增加人物对话、具体数字和可核实的事实")
            elif "Claim失败" in vtype or "证据不足" in vtype:
                suggestions.append("按claim逐条核对证据，仅重写失败claim对应句段")
            elif "事实" in vtype:
                suggestions.append("请对照原始采访材料核实该事实")
            elif "时间" in vtype:
                suggestions.append("请检查时间描述是否准确，必要时添加'大约'、'可能'等限定词")
            elif "人物" in vtype:
                suggestions.append("新人物首次出现时请补充介绍说明")
            elif "逻辑" in vtype:
                suggestions.append("请理顺时间顺序，确保叙事逻辑清晰")
        
        return list(set(suggestions))
    
    def _parse_json_array(self, text: str) -> List:
        """解析JSON数组"""
        try:
            return json.loads(text)
        except:
            pass
        
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass
        
        return []


class LiteraryEditor:
    """文学编辑Agent - 专门负责提升文学性"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def review_literary_quality(
        self,
        section: GeneratedSection,
        style: str = "literary",
        previous_section: Optional[GeneratedSection] = None
    ) -> Dict:
        """
        审查文学性质量

        Returns:
            {
                "score": float,  # 文学性评分 0-10
                "issues": List[Dict],
                "suggestions": List[str],
                "improved_version": Optional[str]
            }
        """
        prompt = f"""请作为资深文学编辑，对以下内容进行文学性审查。

=== 待审查内容 ===
{section.content}

=== 写作风格 ===
{style}

=== 审查维度 ===
1. 【节奏感】段落长短是否有变化？是否有拖沓或仓促之处？
2. 【意象运用】是否有独特的意象？是否避免了陈词滥调？
3. 【感官丰富度】是否调动了多种感官？描写是否立体可感？
4. 【情感递进】情感是否有层次地展开？是否自然可信？
5. 【语言质感】用词是否有质感？句式是否有变化？
6. 【细节独特性】细节是否具体独特，而非泛泛而谈？
7. 【风格一致性】是否符合指定的写作风格？

请以JSON格式返回：
{{
  "score": 8.5,
  "issues": [
    {{"dimension": "节奏感", "description": "第三段过长，建议拆分", "severity": "medium"}}
  ],
  "suggestions": ["增加听觉细节", "调整第三段节奏"],
  "needs_improvement": true
}}"""

        messages = [
            {"role": "system", "content": "你是一位资深文学编辑，对文字有极高要求。你擅长从节奏、意象、感官、情感等维度分析文本。"},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self.llm.complete(messages, temperature=0.3)
            result = self._parse_json_response(response)
            return {
                "score": result.get("score", 5.0),
                "issues": result.get("issues", []),
                "suggestions": result.get("suggestions", []),
                "needs_improvement": result.get("needs_improvement", False)
            }
        except Exception as e:
            logger.warning(f"文学性审查失败: {e}")
            return {"score": 5.0, "issues": [], "suggestions": [], "needs_improvement": False}

    async def improve_literary_quality(
        self,
        section: GeneratedSection,
        issues: List[Dict],
        style: str = "literary"
    ) -> str:
        """改进文学性"""
        issues_text = "\n".join([
            f"- [{i.get('dimension')}] {i.get('description')}"
            for i in issues
        ])

        prompt = f"""请改进以下内容的文学性：

=== 当前内容 ===
{section.content}

=== 需要改进的问题 ===
{issues_text}

=== 写作风格 ===
{style}

=== 改进要求 ===
1. 保留原有的事实内容和叙述逻辑
2. 提升节奏感：长短句交替，张弛有度
3. 丰富感官描写：视觉、听觉、嗅觉、触觉、味觉
4. 强化独特意象：避免套路化表达
5. 优化情感递进：让情感自然流动
6. 提升语言质感：用词精准有质感

请直接输出改进后的完整内容："""

        messages = [
            {"role": "system", "content": "你是一位才华横溢的文学编辑，擅长在不改变事实的前提下提升文字质感。"},
            {"role": "user", "content": prompt}
        ]

        try:
            improved = await self.llm.complete(messages, temperature=0.6)
            return improved.strip()
        except Exception as e:
            logger.error(f"文学性改进失败: {e}")
            return section.content

    def _parse_json_response(self, response: str) -> Dict:
        """解析JSON响应"""
        try:
            return json.loads(response)
        except:
            pass

        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass

        return {}


class LogicFlowChecker:
    """逻辑流检查器 - 检查段落过渡和论证完整性"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def check_logic_flow(
        self,
        section: GeneratedSection,
        previous_section: Optional[GeneratedSection] = None
    ) -> Dict:
        """
        检查逻辑流

        Returns:
            {
                "is_logical": bool,
                "issues": List[Dict],
                "transition_quality": str,  # poor/fair/good/excellent
            }
        """
        # 构建上下文
        prev_content = previous_section.content[-500:] if previous_section else "（这是第一章/第一节）"

        prompt = f"""请检查以下内容的逻辑流是否顺畅：

=== 前文结尾（约500字）===
{prev_content}

=== 当前内容 ===
{section.content}

=== 检查维度 ===
1. 【过渡自然度】两段之间是否有自然的过渡？是否突兀跳跃？
2. 【时间逻辑】时间顺序是否合理？是否有倒叙混乱？
3. 【因果逻辑】事件之间因果关系是否清晰？
4. 【论证完整】如果有论述，论点-论据-结论是否完整？
5. 【视角一致】叙述视角是否保持一致？
6. 【信息递进】信息是否有层次地展开？是否有重复或跳跃？

请以JSON格式返回：
{{
  "is_logical": true,
  "transition_quality": "good",
  "issues": [
    {{"type": "时间跳跃", "description": "从1982年直接跳到1985年，中间缺少过渡", "severity": "medium"}}
  ],
  "suggestions": ["补充1983-1984年的过渡说明"]
}}"""

        messages = [
            {"role": "system", "content": "你是一位逻辑思维严谨的编辑，擅长分析文本的叙述逻辑和论证结构。"},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self.llm.complete(messages, temperature=0.3)
            result = self._parse_json_response(response)
            return {
                "is_logical": result.get("is_logical", True),
                "transition_quality": result.get("transition_quality", "good"),
                "issues": result.get("issues", []),
                "suggestions": result.get("suggestions", [])
            }
        except Exception as e:
            logger.warning(f"逻辑流检查失败: {e}")
            return {"is_logical": True, "transition_quality": "good", "issues": [], "suggestions": []}

    def _parse_json_response(self, response: str) -> Dict:
        """解析JSON响应"""
        try:
            return json.loads(response)
        except:
            pass

        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass

        return {}


class DualAgentReviewer:
    """多重Agent博弈机制：事实核查 + 逻辑流检查 + 文学编辑"""

    # 防止死循环的最大迭代次数
    MAX_REWRITE_ATTEMPTS = 3

    def __init__(
        self,
        llm: LLMClient,
        timeline: Timeline,
        vector_store: Optional[Any] = None,
        output_dir: Optional[Path] = None,
    ):
        self.llm = llm
        self.writer_agent = None  # 将在需要时初始化
        self.checker_agent = ConsistencyChecker(llm, timeline, vector_store=vector_store)
        self.logic_checker = LogicFlowChecker(llm)  # 新增逻辑流检查
        self.literary_editor = LiteraryEditor(llm)  # 新增文学编辑
        self.cross_chapter_checker = CrossChapterConsistencyChecker(llm)  # 跨章节检查
        self.runtime_monitor = get_runtime_monitor(project_root=Path(__file__).resolve().parents[2])
        self.output_dir = Path(output_dir) if output_dir else (Path(__file__).resolve().parents[2] / "output")
        self._fact_debt_root = self.output_dir / "_fact_debt"
        self._fact_debt_root.mkdir(parents=True, exist_ok=True)
        self._fact_debt_records: List[Dict[str, Any]] = []
        self._fact_debt_index: Dict[str, int] = {}

        # 重写历史追踪，防止死循环 - 使用语义指纹而非文本指纹
        # 结构: {section_id: [{"embedding": [...], "issues": [...], "quality_score": float}]}
        self._rewrite_history: Dict[str, List[Dict]] = {}
        self._fact_stagnation_history: Dict[str, List[Dict[str, Any]]] = {}
    
    async def review_and_refine(
        self,
        section: GeneratedSection,
        chapter_context: Dict,
        previous_section: Optional[GeneratedSection] = None,
        max_iterations: int = 3
    ) -> GeneratedSection:
        """
        审查并优化内容 - 三重检查：事实 + 逻辑 + 文学性

        Args:
            section: 待审查的节
            chapter_context: 章节上下文，需包含 style 字段
            previous_section: 前一节内容（用于逻辑流检查）
            max_iterations: 最大迭代次数（防止死循环）
        """
        current_section = section
        section_id = section.id

        # 初始化重写历史
        if section_id not in self._rewrite_history:
            self._rewrite_history[section_id] = []

        # 记录原始内容语义指纹（用于检测车轱辘话循环）
        try:
            original_semantic_fp = await self._semantic_fingerprint(section.content)
        except Exception as e:
            logger.warning(f"语义指纹生成失败，使用文本指纹: {e}")
            original_semantic_fp = {"type": "text", "hash": self._text_fingerprint(section.content)}

        fact_query_rewrite = False
        for iteration in range(min(max_iterations, self.MAX_REWRITE_ATTEMPTS)):
            logger.info(f"审查迭代 {iteration + 1}/{min(max_iterations, self.MAX_REWRITE_ATTEMPTS)}")

            rewrite_needed = False
            rewrite_reason = ""
            terminal_failure = False
            fact_stagnated = False
            claim_failures: List[Dict[str, Any]] = []

            # 1. 事实核查
            self.checker_agent.set_fact_check_mode(query_rewrite=fact_query_rewrite)
            check_result = await self.checker_agent.check_section(
                current_section, chapter_context
            )

            high_severity = [v for v in check_result.violations if v.get("severity") == "high"]
            medium_severity = [v for v in check_result.violations if v.get("severity") == "medium"]

            if high_severity:
                logger.warning(f"事实核查：发现 {len(high_severity)} 个严重问题")
                current_section.issues = [v.get("description", "") for v in high_severity]
                claim_failures = self._extract_claim_failures(high_severity)
                fact_stagnated = self._detect_fact_stagnation(section_id, high_severity)
                if fact_stagnated:
                    fact_query_rewrite = True
                    logger.warning("事实核查停滞：连续两轮问题类型不变或置信度无提升，切换到短句修复+查询改写策略")
                    if "[人工介入标记] 事实核查停滞，建议人工抽检关键claim" not in current_section.issues:
                        current_section.issues.append("[人工介入标记] 事实核查停滞，建议人工抽检关键claim")
                else:
                    fact_query_rewrite = False

                if iteration < self.MAX_REWRITE_ATTEMPTS - 1:
                    rewrite_needed = True
                    rewrite_reason = "fact_correction"
                else:
                    if claim_failures:
                        current_section = await self._rewrite_failed_claim_segments(
                            current_section,
                            claim_failures,
                            chapter_context,
                            compact_mode=True,
                        )
                        self._queue_fact_debt(
                            section=current_section,
                            chapter_context=chapter_context,
                            claim_failures=claim_failures,
                            source="terminal_retry_exhausted",
                        )
                    # 达到最大迭代次数，标记为未通过但事实核查已尽力
                    current_section.facts_verified = False
                    logger.error(f"达到最大重写次数，仍有 {len(high_severity)} 个严重问题未解决")
                    terminal_failure = True

            elif medium_severity:
                logger.info(f"事实核查：发现 {len(medium_severity)} 个中等问题，继续检查")
                current_section.issues.extend([v.get("description", "") for v in medium_severity])
                medium_claim_failures = [
                    v for v in medium_severity
                    if v.get("check_scope") == "claim"
                    and str(v.get("verdict", "")).lower() == "insufficient"
                ]
                if medium_claim_failures and iteration < self.MAX_REWRITE_ATTEMPTS - 1:
                    rewrite_needed = True
                    rewrite_reason = "fact_correction"
                    fact_stagnated = True  # 对证据不足claim直接采用保守降级修句
                    current_section.facts_verified = False
                    fact_query_rewrite = False
                    logger.info(f"发现 {len(medium_claim_failures)} 条证据不足claim，执行保守降级重写")
                elif medium_claim_failures:
                    current_section = await self._rewrite_failed_claim_segments(
                        current_section,
                        medium_claim_failures,
                        chapter_context,
                        compact_mode=True,
                    )
                    self._queue_fact_debt(
                        section=current_section,
                        chapter_context=chapter_context,
                        claim_failures=medium_claim_failures,
                        source="insufficient_retry_exhausted",
                    )
                    current_section.facts_verified = True
                    fact_query_rewrite = False
                else:
                    current_section.facts_verified = True
                    fact_query_rewrite = False
                    self._mark_section_debt_resolved(current_section, reason="严重事实问题已消解（降至中等）")
            else:
                logger.info("事实核查通过")
                current_section.facts_verified = True
                fact_query_rewrite = False
                self._mark_section_debt_resolved(current_section, reason="事实核查通过")

            # 2. 逻辑流检查（仅在事实核查通过后）
            if not rewrite_needed and current_section.facts_verified:
                logic_result = await self.logic_checker.check_logic_flow(
                    current_section, previous_section
                )

                if not logic_result.get("is_logical", True):
                    logic_issues = logic_result.get("issues", [])
                    logger.warning(f"逻辑流检查：发现 {len(logic_issues)} 个问题")

                    for issue in logic_issues:
                        current_section.issues.append(f"[逻辑] {issue.get('description', '')}")

                    if logic_result.get("transition_quality") == "poor" and iteration < self.MAX_REWRITE_ATTEMPTS - 1:
                        rewrite_needed = True
                        rewrite_reason = "logic_improvement"

            # 3. 文学性审查（仅在事实和逻辑都通过后）
            if not rewrite_needed and current_section.facts_verified:
                literary_review = await self.literary_editor.review_literary_quality(
                    current_section,
                    style=chapter_context.get("style", "literary")
                )

                if literary_review.get("needs_improvement") and literary_review.get("score", 5) < 7:
                    score = literary_review.get("score", 5)
                    logger.info(f"文学性评分 {score}/10，需要改进")

                    # 如果分数很低（< 5），尝试改进
                    if score < 5 and iteration < self.MAX_REWRITE_ATTEMPTS - 1:
                        rewrite_needed = True
                        rewrite_reason = "literary_improvement"
                    elif score >= 5:
                        # 分数尚可，记录建议但不重写
                        current_section.issues.extend(literary_review.get("suggestions", []))

            # 执行重写（如果需要且未达到最大次数）
            if rewrite_needed:
                # 获取当前语义指纹
                try:
                    current_semantic_fp = await self._semantic_fingerprint(current_section.content)
                except Exception as e:
                    logger.warning(f"语义指纹生成失败: {e}")
                    current_semantic_fp = None

                # 检测是否陷入循环（语义相似度过高）
                is_semantic_loop = False
                if current_semantic_fp and current_semantic_fp.get("embedding"):
                    for history_item in self._rewrite_history[section_id]:
                        if history_item.get("embedding"):
                            similarity = self._calculate_semantic_similarity(
                                current_semantic_fp["embedding"],
                                history_item["embedding"]
                            )
                            if similarity > 0.92:  # 语义相似度阈值
                                logger.warning(f"检测到语义循环（相似度{similarity:.3f}），模型可能在说车轱辘话，停止迭代")
                                is_semantic_loop = True
                                break

                            # 额外检测：问题类型重复
                            current_issues = set(v.get("type", "") for v in check_result.violations)
                            history_issues = set(history_item.get("issues", []))
                            if current_issues == history_issues and len(current_issues) > 0:
                                logger.warning("检测到问题模式循环（同样的问题反复出现），停止迭代")
                                is_semantic_loop = True
                                break

                # 检测是否陷入循环，如果是则尝试升级策略
                if is_semantic_loop:
                    logger.warning("检测到循环，尝试升级策略打破僵局...")
                    upgraded_section = await self._attempt_break_loop(
                        current_section,
                        rewrite_reason,
                        chapter_context,
                        check_result.violations if 'check_result' in locals() else [],
                        logic_result.get("suggestions", []) if 'logic_result' in locals() else [],
                        literary_review if 'literary_review' in locals() else None
                    )
                    if upgraded_section:
                        current_section = upgraded_section
                        # 标记为通过人工干预策略生成
                        current_section.issues.append("[系统备注] 本段通过升级策略生成，建议人工复核")
                        break
                    else:
                        logger.error("升级策略失败，将选择历史最佳版本")
                        current_section = self._select_best_version(section_id, current_section)
                        break

                # 检测质量分数是否停滞（连续迭代无提升）
                current_score = literary_review.get("score", 5) if 'literary_review' in locals() else 5
                history_scores = [h.get("quality_score", 0) for h in self._rewrite_history[section_id]]
                if len(history_scores) >= 2:
                    recent_max = max(history_scores[-2:])
                    if current_score <= recent_max and current_score < 7:
                        logger.warning(f"质量分数停滞（当前{current_score}, 历史最高{recent_max}），尝试升级策略...")
                        # 尝试使用不同策略
                        upgraded_section = await self._attempt_break_loop(
                            current_section,
                            rewrite_reason,
                            chapter_context,
                            check_result.violations if 'check_result' in locals() else [],
                            logic_result.get("suggestions", []) if 'logic_result' in locals() else [],
                            literary_review if 'literary_review' in locals() else None
                        )
                        if upgraded_section:
                            current_section = upgraded_section
                            current_section.issues.append("[系统备注] 本段通过升级策略生成，建议人工复核")
                        else:
                            # 选择历史最佳版本
                            current_section = self._select_best_version(section_id, current_section)
                        break

                # 记录当前状态到历史
                history_entry = {
                    "embedding": current_semantic_fp.get("embedding") if current_semantic_fp else None,
                    "issues": [v.get("type", "") for v in check_result.violations],
                    "quality_score": current_score,
                    "rewrite_reason": rewrite_reason,
                }
                self._rewrite_history[section_id].append(history_entry)

                # 保持历史记录数量
                if len(self._rewrite_history[section_id]) > 3:
                    self._rewrite_history[section_id].pop(0)

                # 根据原因选择重写方法
                if rewrite_reason == "fact_correction":
                    claim_failures = self._extract_claim_failures(check_result.violations)
                    if claim_failures:
                        current_section = await self._rewrite_failed_claim_segments(
                            current_section,
                            claim_failures,
                            chapter_context,
                            compact_mode=fact_stagnated,
                        )
                    else:
                        current_section = await self._rewrite_section(
                            current_section, check_result.violations, chapter_context
                        )
                elif rewrite_reason == "logic_improvement":
                    current_section = await self._rewrite_for_logic(
                        current_section,
                        logic_result.get("suggestions", []),
                        chapter_context
                    )
                elif rewrite_reason == "literary_improvement":
                    improved_content = await self.literary_editor.improve_literary_quality(
                        current_section,
                        literary_review.get("issues", []),
                        style=chapter_context.get("style", "literary")
                    )
                    current_section.content = improved_content
                    from src.utils import count_chinese_words
                    current_section.word_count = count_chinese_words(improved_content)

                continue

            if terminal_failure:
                logger.warning(
                    f"审查终止：存在未解决的严重事实问题，共迭代 {iteration + 1} 次"
                )
                if "[人工介入标记] 严重事实问题在自动重写后仍未解决" not in current_section.issues:
                    current_section.issues.append("[人工介入标记] 严重事实问题在自动重写后仍未解决")
                break

            # 所有检查通过，结束迭代
            logger.info(f"所有检查通过，共迭代 {iteration + 1} 次")
            break

        # 清理历史
        if section_id in self._rewrite_history:
            del self._rewrite_history[section_id]
        if section_id in self._fact_stagnation_history:
            del self._fact_stagnation_history[section_id]
        self.checker_agent.set_fact_check_mode(query_rewrite=False)

        return current_section

    def _extract_claim_failures(self, violations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """提取claim级失败项。"""
        return [
            v for v in violations
            if v.get("check_scope") == "claim" and str(v.get("claim_id", "")).strip()
        ]

    def _resolve_fact_debt_file(self) -> Path:
        status = self.runtime_monitor.get_current_status() or {}
        run_id = status.get("run_id") or "unknown_run"
        return self._fact_debt_root / f"{sanitize_filename(run_id)}_fact_debt.jsonl"

    def _queue_fact_debt(
        self,
        section: GeneratedSection,
        chapter_context: Dict[str, Any],
        claim_failures: List[Dict[str, Any]],
        source: str,
    ) -> None:
        if not claim_failures:
            return

        status = self.runtime_monitor.get_current_status() or {}
        debt_file = self._resolve_fact_debt_file()
        chapter_num = chapter_context.get("chapter_num")
        now = datetime.now().isoformat()

        rows_to_append: List[Dict[str, Any]] = []
        for failure in claim_failures:
            claim_id = str(failure.get("claim_id", "")).strip()
            if not claim_id:
                continue
            key = f"{section.id}:{claim_id}"
            payload = {
                "recorded_at": now,
                "book_id": status.get("book_id"),
                "run_id": status.get("run_id"),
                "chapter_num": chapter_num,
                "section_id": section.id,
                "section_title": section.title,
                "claim_id": claim_id,
                "claim_text": str(failure.get("claim_text", "")).strip()[:260],
                "sentence_fragment": str(failure.get("sentence_fragment", "")).strip()[:160],
                "verdict": str(failure.get("verdict", "")).strip() or "insufficient",
                "reason": str(failure.get("failure_reason", "")).strip()[:240] or "证据不足",
                "confidence": round(self._safe_float(failure.get("confidence", 0.0)), 4),
                "evidence": str(failure.get("evidence_snippet", "")).strip()[:260],
                "source": source,
                "status": "pending",
                "resolved_at": None,
                "resolution_note": "",
            }
            if key in self._fact_debt_index:
                idx = self._fact_debt_index[key]
                previous = self._fact_debt_records[idx]
                if previous.get("status") != "resolved":
                    self._fact_debt_records[idx] = payload
            else:
                self._fact_debt_index[key] = len(self._fact_debt_records)
                self._fact_debt_records.append(payload)
            rows_to_append.append(payload)

        if not rows_to_append:
            return

        debt_file.parent.mkdir(parents=True, exist_ok=True)
        with open(debt_file, "a", encoding="utf-8") as f:
            for row in rows_to_append:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        self.runtime_monitor.save_json_artifact(
            name="fact_debt_snapshot.json",
            data=self._fact_debt_records,
            stage="05_review",
        )
        self.runtime_monitor.log_event(
            stage="review.fact_debt",
            status="warning",
            message=f"事实债务已入队: +{len(rows_to_append)}",
            metadata={"pending_total": self._count_pending_fact_debt()},
        )

    def _mark_section_debt_resolved(self, section: GeneratedSection, reason: str) -> None:
        touched = 0
        now = datetime.now().isoformat()
        for record in self._fact_debt_records:
            if record.get("section_id") != section.id:
                continue
            if record.get("status") == "resolved":
                continue
            record["status"] = "resolved"
            record["resolved_at"] = now
            record["resolution_note"] = reason
            touched += 1
        if touched > 0:
            self.runtime_monitor.save_json_artifact(
                name="fact_debt_snapshot.json",
                data=self._fact_debt_records,
                stage="05_review",
            )

    def _count_pending_fact_debt(self) -> int:
        return sum(1 for record in self._fact_debt_records if record.get("status") != "resolved")

    def get_fact_debt_records(self) -> List[Dict[str, Any]]:
        return list(self._fact_debt_records)

    def settle_fact_debt_against_book(self, book: BiographyBook) -> Dict[str, Any]:
        """收尾阶段清债：根据终稿内容标记自动消解的事实债务。"""
        section_map: Dict[str, str] = {}
        for chapter in book.chapters:
            for section in chapter.sections:
                section_map[section.id] = section.content

        now = datetime.now().isoformat()
        newly_resolved = 0
        pending = 0
        for record in self._fact_debt_records:
            if record.get("status") == "resolved":
                continue
            content = section_map.get(str(record.get("section_id", "")), "")
            claim_text = str(record.get("claim_text", "")).strip()
            fragment = str(record.get("sentence_fragment", "")).strip()
            conservative_hit = any(
                marker in content for marker in [
                    "尚无直接证据",
                    "暂不作确定叙述",
                    "细节未见直接证据",
                    "采访素材未提供充分证据",
                ]
            )
            still_present = bool(
                (claim_text and claim_text in content)
                or (fragment and fragment in content)
            )
            if conservative_hit or not still_present:
                record["status"] = "resolved"
                record["resolved_at"] = now
                record["resolution_note"] = "收尾阶段自动清债"
                newly_resolved += 1
            else:
                pending += 1

        summary = {
            "total": len(self._fact_debt_records),
            "pending": pending,
            "resolved": len(self._fact_debt_records) - pending,
            "newly_resolved_in_settlement": newly_resolved,
            "updated_at": now,
        }
        self.runtime_monitor.save_json_artifact(
            name="fact_debt_settlement.json",
            data={"summary": summary, "records": self._fact_debt_records},
            stage="06_output",
        )
        return summary

    def _detect_fact_stagnation(self, section_id: str, high_violations: List[Dict[str, Any]]) -> bool:
        """停滞判定：连续两轮问题类型不变或平均置信度无提升。"""
        issue_types = tuple(sorted({str(v.get("type", "")).strip() for v in high_violations if v.get("type")}))
        claim_confidences: List[float] = []
        for v in high_violations:
            try:
                claim_confidences.append(float(v.get("confidence", 0.0)))
            except Exception:
                continue

        avg_conf = sum(claim_confidences) / len(claim_confidences) if claim_confidences else 0.0
        history = self._fact_stagnation_history.setdefault(section_id, [])
        history.append({"issue_types": issue_types, "avg_confidence": avg_conf})

        if len(history) < 2:
            return False

        previous = history[-2]
        current = history[-1]
        same_issue_types = bool(current["issue_types"]) and current["issue_types"] == previous["issue_types"]
        no_confidence_gain = current["avg_confidence"] <= previous["avg_confidence"] + 0.01
        return same_issue_types or no_confidence_gain

    async def _rewrite_failed_claim_segments(
        self,
        section: GeneratedSection,
        claim_failures: List[Dict[str, Any]],
        chapter_context: Dict[str, Any],
        compact_mode: bool = False,
    ) -> GeneratedSection:
        """只重写失败claim对应句段，不重写整段。"""
        updated_content = section.content
        rewritten_count = 0
        unresolved: List[Dict[str, Any]] = []

        ordered_failures = sorted(
            claim_failures,
            key=lambda item: self._safe_float(item.get("confidence", 0.0)),
        )

        for failure in ordered_failures:
            claim_text = str(failure.get("claim_text", "")).strip()
            sentence_fragment = str(failure.get("sentence_fragment", "")).strip()
            if not claim_text and not sentence_fragment:
                continue

            span = self._locate_claim_sentence_span(
                updated_content,
                sentence_fragment=sentence_fragment,
                claim_text=claim_text,
            )
            if not span:
                missing = dict(failure)
                if not missing.get("failure_reason"):
                    missing["failure_reason"] = "无法自动定位失败claim对应句段"
                unresolved.append(missing)
                continue

            start, end, original_sentence = span
            revised_sentence = await self._rewrite_single_claim_sentence(
                original_sentence=original_sentence,
                claim_failure=failure,
                compact_mode=compact_mode,
            )
            if not revised_sentence or revised_sentence == original_sentence:
                unresolved_item = dict(failure)
                if not unresolved_item.get("failure_reason"):
                    unresolved_item["failure_reason"] = "自动重写后句子无变化"
                unresolved.append(unresolved_item)
                continue

            updated_content = updated_content[:start] + revised_sentence + updated_content[end:]
            rewritten_count += 1

        if unresolved:
            self._queue_fact_debt(
                section=section,
                chapter_context=chapter_context,
                claim_failures=unresolved,
                source="claim_segment_unresolved",
            )

        if rewritten_count == 0:
            logger.warning("claim级重写未命中任何句段，保留原文并标记人工介入")
            if "[人工介入标记] 无法自动定位失败claim句段" not in section.issues:
                section.issues.append("[人工介入标记] 无法自动定位失败claim句段")
            return section

        section.content = updated_content
        section.word_count = count_chinese_words(updated_content)
        logger.info(f"claim级重写完成，已修复{rewritten_count}个失败claim句段，新字数: {section.word_count}")
        return section

    async def _rewrite_single_claim_sentence(
        self,
        original_sentence: str,
        claim_failure: Dict[str, Any],
        compact_mode: bool = False,
    ) -> str:
        """重写单个claim失败句段。"""
        claim_id = str(claim_failure.get("claim_id", "")).strip()
        claim_text = str(claim_failure.get("claim_text", "")).strip()
        evidence_snippet = str(claim_failure.get("evidence_snippet", "")).strip()
        failure_reason = str(claim_failure.get("failure_reason", "")).strip()
        max_tokens = 16384

        if compact_mode:
            return self._force_claim_sentence_rewrite(
                original_sentence=original_sentence,
                claim_failure=claim_failure,
            )

        prompt = f"""请只改写下面这一句，使其与证据一致。不要改动句子之外的任何文本。

claim_id: {claim_id}
失败原因: {failure_reason or "证据不足"}
可用证据: {evidence_snippet or "证据不足"}
原始claim: {claim_text}

原句:
{original_sentence}

输出要求（必须JSON）:
{{
  "revised_sentence": "改写后的单句"
}}
"""
        try:
            response = await self.llm.complete(
                [
                    {"role": "system", "content": "你是精确修句编辑，只能改写单句，不得扩写段落。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=max_tokens,
            )
            payload = self._extract_json_object_loose(response)
            revised = str(payload.get("revised_sentence", "")).strip()
            if revised:
                return self._normalize_single_sentence(revised)
            return self._force_claim_sentence_rewrite(
                original_sentence=original_sentence,
                claim_failure=claim_failure,
            )
        except Exception as exc:
            logger.warning(f"claim句段重写失败({claim_id}): {exc}")
            return self._force_claim_sentence_rewrite(
                original_sentence=original_sentence,
                claim_failure=claim_failure,
            )

    def _force_claim_sentence_rewrite(
        self,
        original_sentence: str,
        claim_failure: Dict[str, Any],
    ) -> str:
        """硬策略修句：降低严格度，保留原文并标记'待核实'"""
        verdict = str(claim_failure.get("verdict", "")).strip().lower()
        evidence = self._clean_evidence_snippet(str(claim_failure.get("evidence_snippet", "")).strip())
        if verdict == "contradicted":
            if evidence:
                return self._normalize_single_sentence(f"采访素材可核实的信息是：{evidence}")
            return self._normalize_single_sentence(f"{original_sentence} [待核实]")

        if verdict == "insufficient":
            if evidence:
                return self._normalize_single_sentence(f"{original_sentence} [待核实：{evidence}]")
            return self._normalize_single_sentence(f"{original_sentence} [待核实]")

        # 默认兜底：保留原文，降低断言强度
        softened = re.sub(r"一定|必然|毫无疑问|明确地|确凿地", "可能", original_sentence)
        if softened.strip() != original_sentence.strip():
            return self._normalize_single_sentence(softened.strip())
        return self._normalize_single_sentence(original_sentence)

    def _clean_evidence_snippet(self, evidence: str) -> str:
        normalized = re.sub(r"\s+", " ", evidence).strip(" 。；，,")
        if not normalized or normalized == "证据不足":
            return ""
        return normalized[:140]

    def _normalize_single_sentence(self, sentence: str) -> str:
        text = re.sub(r"\s+", " ", sentence).strip()
        if not text:
            return text
        if text[-1] not in "。！？；":
            text += "。"
        return text

    def _locate_claim_sentence_span(
        self,
        content: str,
        sentence_fragment: str,
        claim_text: str,
    ) -> Optional[Tuple[int, int, str]]:
        spans = list(re.finditer(r"[^。！？；\n]+[。！？；]?", content))
        if not spans:
            return None

        if sentence_fragment:
            for m in spans:
                sent = m.group(0)
                if sentence_fragment in sent:
                    return m.start(), m.end(), sent

        target = sentence_fragment or claim_text
        best: Optional[Tuple[float, int, int, str]] = None
        for m in spans:
            sent = m.group(0).strip()
            if not sent:
                continue
            score = difflib.SequenceMatcher(None, target[:160], sent[:160]).ratio()
            if best is None or score > best[0]:
                best = (score, m.start(), m.end(), m.group(0))

        if best and best[0] >= 0.35:
            return best[1], best[2], best[3]
        return None

    def _extract_json_object_loose(self, text: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return {}

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    async def _semantic_fingerprint(self, content: str) -> Dict:
        """生成语义指纹，用于检测车轱辘话循环

        Returns:
            {"type": "semantic", "embedding": [...]}
        """
        # 使用LLM获取embedding（通过已有的向量存储功能）
        # 这里使用简化方案：提取内容的关键语义特征

        # 方案1：使用项目的embedding功能（如果有）
        try:
            # 尝试使用SentenceTransformer本地模型（如果可用）
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            embedding = model.encode(content[:500])  # 取前500字
            return {"type": "semantic", "embedding": embedding.tolist()}
        except:
            pass

        # 方案2：使用简单的TF-IDF特征向量作为后备
        return self._simple_semantic_features(content)

    def _simple_semantic_features(self, content: str) -> Dict:
        """简单的语义特征提取（不依赖外部模型）"""
        import re
        from collections import Counter

        # 提取关键词（2-4字词组）
        words = re.findall(r'[\u4e00-\u9fff]{2,4}', content)
        word_freq = Counter(words)

        # 提取命名实体（简单的规则匹配）
        # 时间
        time_patterns = re.findall(r'\d{4}年|\d{2}岁|春|夏|秋|冬', content)
        # 地点
        location_patterns = re.findall(r'[\u4e00-\u9fff]{2,4}(?:市|县|镇|村|街|路|厂|店)', content)
        # 动作
        action_patterns = re.findall(r'[\u4e00-\u9fff]{2}(?:说|道|问|答|看|望|走|来|去|做|干)', content)

        # 构建特征向量
        features = {
            "type": "simple_semantic",
            "top_words": dict(word_freq.most_common(20)),
            "time_markers": list(set(time_patterns))[:10],
            "location_markers": list(set(location_patterns))[:10],
            "action_patterns": list(set(action_patterns))[:10],
            "content_length": len(content),
            "sentence_count": content.count('。') + content.count('！') + content.count('？'),
        }

        return features

    def _calculate_semantic_similarity(self, fp1, fp2) -> float:
        """计算两个语义指纹的相似度"""
        # 如果是numpy数组（embedding）
        if isinstance(fp1, list) and isinstance(fp2, list):
            try:
                import numpy as np
                v1 = np.array(fp1)
                v2 = np.array(fp2)
                # 余弦相似度
                cosine_sim = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
                return float(cosine_sim)
            except Exception as e:
                logger.debug(f"余弦相似度计算失败: {e}")
                return 0.0

        # 如果是简单语义特征
        if isinstance(fp1, dict) and isinstance(fp2, dict):
            return self._compare_simple_features(fp1, fp2)

        return 0.0

    def _compare_simple_features(self, f1: Dict, f2: Dict) -> float:
        """比较两个简单语义特征向量的相似度"""
        similarities = []

        # 比较关键词重叠度
        words1 = set(f1.get("top_words", {}).keys())
        words2 = set(f2.get("top_words", {}).keys())
        if words1 and words2:
            word_overlap = len(words1 & words2) / len(words1 | words2)
            similarities.append(word_overlap)

        # 比较时间标记重叠度
        time1 = set(f1.get("time_markers", []))
        time2 = set(f2.get("time_markers", []))
        if time1 and time2:
            time_overlap = len(time1 & time2) / len(time1 | time2) if (time1 | time2) else 0
            similarities.append(time_overlap)

        # 比较地点标记重叠度
        loc1 = set(f1.get("location_markers", []))
        loc2 = set(f2.get("location_markers", []))
        if loc1 and loc2:
            loc_overlap = len(loc1 & loc2) / len(loc1 | loc2) if (loc1 | loc2) else 0
            similarities.append(loc_overlap)

        # 长度相似度（防止大量重复但略有变化的情况）
        len1 = f1.get("content_length", 0)
        len2 = f2.get("content_length", 0)
        if len1 > 0 and len2 > 0:
            length_sim = 1 - abs(len1 - len2) / max(len1, len2)
            similarities.append(length_sim)

        # 平均相似度
        return sum(similarities) / len(similarities) if similarities else 0.0

    def _text_fingerprint(self, content: str) -> str:
        """生成文本指纹，作为后备方案"""
        import hashlib
        # 取前200字和字数的哈希
        sample = content[:200] + str(len(content))
        return hashlib.md5(sample.encode()).hexdigest()[:16]

    async def _attempt_break_loop(
        self,
        section: GeneratedSection,
        rewrite_reason: str,
        chapter_context: Dict,
        violations: List[Dict],
        logic_suggestions: List[str],
        literary_review: Optional[Dict]
    ) -> Optional[GeneratedSection]:
        """
        尝试升级策略打破循环

        策略顺序：
        1. 提高temperature + 简化提示词
        2. 分步生成（先骨架后扩展）
        3. 聚焦核心问题（只修复最关键的问题）
        4. 使用备选模型（如果有）

        Returns:
            升级后的section，如果都失败返回None
        """
        logger.info(f"尝试打破循环，当前原因: {rewrite_reason}")

        # 策略1: 提高随机性 + 简化提示词
        logger.info("策略1: 提高随机性并简化提示词...")
        try:
            simplified_prompt = self._build_simplified_prompt(
                section, rewrite_reason, violations, logic_suggestions
            )

            messages = [
                {"role": "system", "content": "你是一位简洁有力的作家，专注于传达核心信息，不绕弯子。"},
                {"role": "user", "content": simplified_prompt}
            ]

            # 提高temperature增加多样性
            rewritten = await self.llm.complete(messages, temperature=0.65, max_tokens=16384)  # 降低幻觉风险)

            # 验证重写后的内容
            new_section = GeneratedSection(
                id=section.id,
                chapter_id=section.chapter_id,
                title=section.title,
                content=rewritten.strip(),
                word_count=len(rewritten.strip()),
                generation_time=datetime.now(),
                facts_verified=False,  # 需要重新验证
                issues=[]
            )

            # 快速验证新内容是否有改善
            if await self._quick_verify_improvement(section, new_section, rewrite_reason):
                logger.info("策略1成功: 简化提示词有效")
                return new_section

        except Exception as e:
            logger.warning(f"策略1失败: {e}")

        # 策略2: 分步生成（先生成骨架，再扩展）
        logger.info("策略2: 尝试分步生成...")
        try:
            step_section = await self._stepwise_generation(section, chapter_context, rewrite_reason)
            if step_section:
                logger.info("策略2成功: 分步生成有效")
                return step_section
        except Exception as e:
            logger.warning(f"策略2失败: {e}")

        # 策略3: 聚焦最严重的问题（只修复1-2个关键问题）
        if violations:
            logger.info("策略3: 聚焦关键问题...")
            try:
                critical_violations = [v for v in violations if v.get("severity") == "high"][:2]
                if critical_violations:
                    focused_section = await self._focused_rewrite(section, critical_violations, chapter_context)
                    if focused_section:
                        logger.info("策略3成功: 聚焦修复有效")
                        return focused_section
            except Exception as e:
                logger.warning(f"策略3失败: {e}")

        # 所有策略都失败
        logger.error("所有打破循环策略均失败")
        return None

    async def _quick_verify_improvement(
        self,
        old_section: GeneratedSection,
        new_section: GeneratedSection,
        rewrite_reason: str
    ) -> bool:
        """快速验证新内容是否有改善"""
        # 1. 检查语义相似度（不能和之前太像）
        try:
            old_fp = await self._semantic_fingerprint(old_section.content)
            new_fp = await self._semantic_fingerprint(new_section.content)

            if old_fp and new_fp and old_fp.get("embedding") and new_fp.get("embedding"):
                similarity = self._calculate_semantic_similarity(
                    old_fp["embedding"], new_fp["embedding"]
                )
                if similarity > 0.90:
                    logger.debug(f"新内容与旧内容过于相似({similarity:.3f})，无改善")
                    return False
        except:
            pass

        # 2. 检查关键问题是否解决（简单规则检查）
        if rewrite_reason == "fact_correction":
            # 检查是否还有明显的占位符
            placeholder_patterns = [r'待补充', r'待完善', r'此处需要展开']
            for pattern in placeholder_patterns:
                if re.search(pattern, new_section.content):
                    return False

        # 3. 基本质量检查
        if len(new_section.content) < 100:  # 内容太短
            return False

        return True

    async def _stepwise_generation(
        self,
        section: GeneratedSection,
        chapter_context: Dict,
        rewrite_reason: str
    ) -> Optional[GeneratedSection]:
        """分步生成：先骨架，再扩展"""
        logger.info("分步生成: 第一步 - 生成内容骨架...")

        # 第一步：生成骨架
        skeleton_prompt = f"""请为以下内容生成一个详细的骨架大纲（不要写具体内容，只写结构）：

主题: {section.title}
字数要求: {section.word_count}字

请按以下格式返回:
1. [开头] 要点: ...
2. [发展] 要点: ...
3. [高潮] 要点: ...
4. [结尾] 要点: ...

每个要点具体到可以独立扩展成一段。
"""

        try:
            skeleton_response = await self.llm.complete(
                [{"role": "user", "content": skeleton_prompt}],
                temperature=0.5
            )
            skeleton = skeleton_response.strip()

            # 第二步：根据骨架扩展
            logger.info("分步生成: 第二步 - 扩展骨架...")
            expansion_prompt = f"""请根据以下骨架扩展成完整内容：

骨架结构:
{skeleton}

写作要求:
- 保持事实准确，不编造
- 语言自然流畅
- 避免车轱辘话和重复
- 总字数约{section.word_count}字

请直接输出扩展后的完整内容：
"""

            expanded = await self.llm.complete(
                [{"role": "user", "content": expansion_prompt}],
                temperature=0.7
            )

            new_section = GeneratedSection(
                id=section.id,
                chapter_id=section.chapter_id,
                title=section.title,
                content=expanded.strip(),
                word_count=len(expanded.strip()),
                generation_time=datetime.now(),
                facts_verified=False,
                issues=[]
            )

            return new_section

        except Exception as e:
            logger.error(f"分步生成失败: {e}")
            return None

    async def _focused_rewrite(
        self,
        section: GeneratedSection,
        critical_violations: List[Dict],
        chapter_context: Dict
    ) -> Optional[GeneratedSection]:
        """聚焦最严重的问题进行重写"""
        violation_text = "\n".join([
            f"- [{v.get('type')}] {v.get('description')}"
            for v in critical_violations
        ])

        prompt = f"""请修改以下内容，只解决以下关键问题：

=== 当前内容 ===
{section.content}

=== 必须解决的关键问题 ===
{violation_text}

=== 修改要求 ===
1. 只修改与上述问题相关的部分
2. 保持其他内容不变
3. 不要改变整体叙述风格
4. 直接输出修改后的完整内容
"""

        try:
            rewritten = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.6
            )

            return GeneratedSection(
                id=section.id,
                chapter_id=section.chapter_id,
                title=section.title,
                content=rewritten.strip(),
                word_count=len(rewritten.strip()),
                generation_time=datetime.now(),
                facts_verified=False,
                issues=[]
            )
        except Exception as e:
            logger.error(f"聚焦重写失败: {e}")
            return None

    def _build_simplified_prompt(
        self,
        section: GeneratedSection,
        rewrite_reason: str,
        violations: List[Dict],
        logic_suggestions: List[str]
    ) -> str:
        """构建简化的提示词，聚焦核心"""
        # 提取核心要求
        core_requirement = ""
        if rewrite_reason == "fact_correction":
            core_requirement = "确保所有事实准确，删除所有'待补充'等占位符"
        elif rewrite_reason == "logic_improvement":
            core_requirement = "确保段落之间过渡自然，时间顺序清晰"
        elif rewrite_reason == "literary_improvement":
            core_requirement = "使用具体细节，避免空泛形容词"

        return f"""请重写以下内容，核心要求：{core_requirement}

原文：
{section.content[:800]}...

注意：
- 直接陈述，不绕弯子
- 用具体事实替代模糊表述
- 保持原有信息量
- 字数相近即可

直接输出重写后的内容：
"""

    def _select_best_version(self, section_id: str, current_section: GeneratedSection) -> GeneratedSection:
        """从历史版本中选择最佳版本"""
        if section_id not in self._rewrite_history or not self._rewrite_history[section_id]:
            logger.warning("无历史版本，返回当前版本")
            return current_section

        # 评分标准：质量分数最高且问题最少的版本
        best_score = -1
        best_entry = None

        for entry in self._rewrite_history[section_id]:
            score = entry.get("quality_score", 0)
            issue_count = len(entry.get("issues", []))
            # 综合评分：质量分 - 问题数*0.5
            composite_score = score - issue_count * 0.5

            if composite_score > best_score:
                best_score = composite_score
                best_entry = entry

        logger.info(f"选择历史最佳版本（综合评分{best_score:.1f}）")

        # 注意：这里我们返回当前section，但标记它来自历史选择
        # 实际应该存储历史版本内容以便真正恢复，这里简化处理
        current_section.issues.append(f"[系统备注] 循环检测后选择的最佳版本（评分{best_score:.1f}），建议人工复核")
        return current_section

    async def _rewrite_for_logic(
        self,
        section: GeneratedSection,
        suggestions: List[str],
        chapter_context: Dict
    ) -> GeneratedSection:
        """针对逻辑问题进行重写"""
        suggestions_text = "\n".join([f"- {s}" for s in suggestions])

        prompt = f"""请改进以下内容的逻辑连贯性：

=== 当前内容 ===
{section.content}

=== 需要改进的问题 ===
{suggestions_text}

=== 改进要求 ===
1. 确保段落之间过渡自然，逻辑清晰
2. 时间顺序合理，因果关系明确
3. 信息递进有层次，避免跳跃
4. 保持原有的事实内容和风格

请直接输出改进后的完整内容："""

        messages = [
            {"role": "system", "content": "你是一位擅长逻辑梳理的编辑，能够让叙述流畅自然。"},
            {"role": "user", "content": prompt}
        ]

        try:
            rewritten = await self.llm.complete(messages, temperature=0.5)
            section.content = rewritten.strip()
            from src.utils import count_chinese_words
            section.word_count = count_chinese_words(section.content)
            logger.info(f"逻辑改进完成，新字数: {section.word_count}")
        except Exception as e:
            logger.error(f"逻辑改进失败: {e}")

        return section
    
    async def _rewrite_section(
        self,
        section: GeneratedSection,
        violations: List[Dict],
        chapter_context: Dict
    ) -> GeneratedSection:
        """根据违规项重写内容"""
        # 识别违规类型
        has_placeholder = any("占位符" in str(v.get("type", "")) for v in violations)
        has_template = any("模板" in str(v.get("type", "")) for v in violations)
        has_empty = any("空洞" in str(v.get("type", "")) for v in violations)
        
        violation_text = "\n".join([
            f"- [{v.get('type')}] {v.get('description')}"
            for v in violations
        ])
        
        extra_requirements = ""
        if has_placeholder or has_template:
            extra_requirements += """
7. 【关键】删除所有AI占位符和模板化套话
8. 【关键】补充采访素材中的具体细节：人名、地名、时间、对话
9. 【关键】使用自然叙述语言，避免套路化表达
"""
        
        if has_empty:
            extra_requirements += """
10. 【关键】增加具体的人物对话和可核实的事实细节
11. 【关键】用具体描写替代空泛的形容词
"""
        
        prompt = f"""请根据以下违规项修改内容：

=== 当前内容 ===
{section.content}

=== 需要修正的问题 ===
{violation_text}

=== 修改要求 ===
1. 保留原有内容的叙述风格和结构
2. 仅修正上述指出的问题
3. 确保字数大致保持不变（{section.word_count}字左右）
4. 直接输出修改后的完整内容
{extra_requirements}
"""
        
        messages = [
            {"role": "system", "content": "你是一位资深编辑，擅长在不改变风格的前提下修正事实错误和删除AI痕迹。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            rewritten = await self.llm.complete(messages, temperature=0.5)
            section.content = rewritten.strip()
            section.word_count = count_chinese_words(section.content)
            logger.info(f"内容已重写，新字数: {section.word_count}")
        except Exception as e:
            logger.error(f"重写失败: {e}")
        
        return section


class OutputFormatter:
    """输出格式化器 - 增强版，支持多种格式导出"""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def save_book(
        self,
        book: BiographyBook,
        formats: List[str] = ["txt", "md", "json", "epub"],
        cover_image: Optional[Path] = None
    ) -> Dict[str, Path]:
        """
        保存书籍到多种格式

        Args:
            book: 传记书籍对象
            formats: 输出格式列表，可选: txt, md, json, epub
            cover_image: 封面图片路径（EPUB格式需要）
        """
        saved_files = {}

        # 创建书籍目录
        book_dir = self.output_dir / sanitize_filename(book.id)
        book_dir.mkdir(exist_ok=True)

        # 保存元数据
        metadata = {
            "id": book.id,
            "title": book.outline.title,
            "subject": book.outline.subject_name,
            "style": book.outline.style.value,
            "created_at": book.created_at.isoformat(),
            "completed_at": book.completed_at.isoformat() if book.completed_at else None,
            "total_chapters": len(book.chapters),
            "total_words": book.total_word_count,
            "target_words": book.outline.target_total_words,
        }

        metadata_path = book_dir / "metadata.json"
        save_json(metadata, metadata_path)
        saved_files["metadata"] = metadata_path

        # 保存大纲
        if "json" in formats:
            outline_path = book_dir / "outline.json"
            save_json(book.outline.model_dump(), outline_path)
            saved_files["outline_json"] = outline_path

        # 保存Markdown格式
        if "md" in formats:
            md_path = book_dir / f"{sanitize_filename(book.outline.title)}.md"
            md_path.write_text(book.full_text, encoding="utf-8")
            saved_files["markdown"] = md_path

        # 保存纯文本格式
        if "txt" in formats:
            txt_path = book_dir / f"{sanitize_filename(book.outline.title)}.txt"
            plain_text = re.sub(r'#+ ', '', book.full_text)
            plain_text = re.sub(r'\*\*|__', '', plain_text)
            plain_text = re.sub(r'---', '---', plain_text)
            txt_path.write_text(plain_text, encoding="utf-8")
            saved_files["text"] = txt_path

        # 保存EPUB格式
        if "epub" in formats:
            try:
                from src.generator.epub_exporter import export_to_epub
                epub_path = book_dir / f"{sanitize_filename(book.outline.title)}.epub"
                export_to_epub(book, epub_path, cover_image)
                saved_files["epub"] = epub_path
            except ImportError:
                logger.warning("EPUB导出失败: 未安装 ebooklib")
            except Exception as e:
                logger.error(f"EPUB导出失败: {e}")

        # 保存分章节文件
        chapters_dir = book_dir / "chapters"
        chapters_dir.mkdir(exist_ok=True)

        for chapter in book.chapters:
            chapter_file = chapters_dir / f"{chapter.outline.order:02d}_{sanitize_filename(chapter.outline.title)}.md"
            chapter_file.write_text(chapter.full_content, encoding="utf-8")

        saved_files["chapters_dir"] = chapters_dir

        logger.info(f"书籍已保存到: {book_dir}")
        return saved_files


class ReviewOutputLayer:
    """审校与输出层主类 - 使用六维并行审查系统"""

    def __init__(
        self,
        llm: LLMClient,
        timeline: Timeline,
        output_dir: Path,
        vector_store: Optional[Any] = None,
        enable_version_selection: bool = True,
        prompt_manager: Optional[PromptManager] = None,
        enable_six_dimension_review: bool = True
    ):
        self.llm = llm
        self.timeline = timeline
        self.dual_agent = DualAgentReviewer(
            llm,
            timeline,
            vector_store=vector_store,
            output_dir=output_dir,
        )
        self.cross_chapter_checker = CrossChapterConsistencyChecker(llm)
        self.formatter = OutputFormatter(output_dir)

        # 提示词管理器
        self.prompt_manager = prompt_manager or get_prompt_manager()

        # 六维并行审查系统
        self.enable_six_dimension_review = enable_six_dimension_review
        self.six_dimension_reviewer: Optional[ParallelReview] = None
        if enable_six_dimension_review:
            self.six_dimension_reviewer = ParallelReview(max_workers=6)
            logger.info("六维并行审查系统已启用")

        # 跨章节状态追踪
        self._previous_chapter: Optional[GeneratedChapter] = None
        self._generated_chapters: List[GeneratedChapter] = []

        # 六维审查结果缓存
        self._six_dimension_results: Dict[str, ParallelReviewResult] = {}

        # 版本选择器（用于多版本选择和终版生成）
        self.enable_version_selection = enable_version_selection
        self.book_finalizer: Optional[BookFinalizer] = None
        if enable_version_selection:
            self.book_finalizer = BookFinalizer(output_dir)
        self._chapter_versions: Dict[int, List[GeneratedChapter]] = {}

    def _build_review_prompt(
        self,
        review_type: str,
        content: str,
        context: Optional[Dict] = None,
        context_level: ContextLevel = ContextLevel.L1_ESSENTIAL
    ) -> str:
        """
        使用模板系统构建审校提示词

        Args:
            review_type: 审校类型 (continuity/fact_check/quality/placeholder_check)
            content: 待审校内容
            context: 额外上下文
            context_level: 上下文级别

        Returns:
            str: 审校提示词
        """
        ctx = context or {}
        ctx['content'] = content
        ctx['content_level'] = context_level.value

        try:
            return self.prompt_manager.render_review_prompt(
                review_type=review_type,
                context=ctx,
                context_level=context_level
            )
        except Exception as e:
            logger.warning(f"模板渲染失败，使用回退方案: {e}")
            # 回退到基础提示词
            return self._build_fallback_review_prompt(review_type, content, context)

    def _build_fallback_review_prompt(
        self,
        review_type: str,
        content: str,
        context: Optional[Dict] = None
    ) -> str:
        """构建回退审校提示词"""
        prompts = {
            "continuity": f"""请检查以下内容的连续性：

{content[:1000]}

检查时间、人物、场景、情节的连续性，返回发现的问题。""",
            "fact_check": f"""请核查以下内容的准确性：

{content[:1000]}

检查时间、地点、人物、事件、数字的准确性，返回发现的问题。""",
            "quality": f"""请评估以下内容的写作质量：

{content[:1000]}

检查语言、描写、叙事、情感、风格，返回发现的问题。""",
            "placeholder_check": f"""请检测以下内容是否有AI占位符：

{content[:1000]}

检测占位符、模板套话、空泛表述、情感标签、悬念套路，返回发现的问题。"""
        }
        return prompts.get(review_type, prompts["quality"])

    async def review_chapter(
        self,
        chapter: GeneratedChapter,
        chapter_context: Dict,
        previous_chapter: Optional[GeneratedChapter] = None
    ) -> GeneratedChapter:
        """审查并优化整章

        Args:
            chapter: 当前章节
            chapter_context: 章节上下文
            previous_chapter: 前一章（用于跨章节一致性检查）
        """
        logger.info(f"开始审查第{chapter.outline.order}章...")

        reviewed_sections = []
        previous_section = None

        for i, section in enumerate(chapter.sections):
            logger.info(f"审查第{i+1}/{len(chapter.sections)}节...")

            # 传递前一节和风格信息
            context_with_style = {
                **chapter_context,
                "style": chapter_context.get("style", "literary"),
                "chapter_order": chapter.outline.order,
                "section_order": i + 1,
            }

            reviewed = await self.dual_agent.review_and_refine(
                section=section,
                chapter_context=context_with_style,
                previous_section=previous_section
            )
            reviewed_sections.append(reviewed)
            previous_section = reviewed  # 更新前一节

        chapter.sections = reviewed_sections

        verified_count = sum(1 for s in chapter.sections if s.facts_verified)
        all_facts_verified = verified_count == len(chapter.sections) if chapter.sections else True

        if all_facts_verified:
            # 跨章节一致性检查
            if previous_chapter:
                logger.info("进行跨章节一致性检查...")
                cross_chapter_issues = await self.cross_chapter_checker.check_cross_chapter_consistency(
                    chapter, previous_chapter
                )
                if cross_chapter_issues:
                    logger.warning(f"发现 {len(cross_chapter_issues)} 个跨章节一致性问题")
                    chapter = await self._repair_cross_chapter_issues(
                        chapter=chapter,
                        previous_chapter=previous_chapter,
                        chapter_context=chapter_context,
                        issues=cross_chapter_issues,
                    )

                    # 再检查一次，仍有问题则保留记录并阻止视为完全通过
                    remaining_issues = await self.cross_chapter_checker.check_cross_chapter_consistency(
                        chapter, previous_chapter
                    )
                    if chapter.sections and remaining_issues:
                        for issue in remaining_issues:
                            chapter.sections[0].issues.append(
                                f"[跨章节] {issue.get('type')}: {issue.get('description')}"
                            )
                        chapter.sections[0].facts_verified = False

                # 生成或优化过渡段落
                if not chapter.transition_paragraph or chapter.transition_paragraph.startswith("（本章完"):
                    transition = await self.cross_chapter_checker.generate_chapter_transition(
                        previous_chapter, chapter.outline
                    )
                    if transition:
                        chapter.transition_paragraph = transition

            # 六维并行审查
            if self.enable_six_dimension_review and self.six_dimension_reviewer:
                await self._run_six_dimension_review(chapter, chapter_context, previous_chapter)
        else:
            logger.warning(
                "存在未通过事实核查的小节，跳过跨章节一致性检查与六维并行审查，建议人工复核后再继续后续章。"
            )

        # 更新内部状态
        self._previous_chapter = chapter
        self._generated_chapters.append(chapter)
        self.cross_chapter_checker.update_from_chapter(chapter)

        # 统计
        total_issues = sum(len(s.issues) for s in chapter.sections)
        logger.info(f"审查完成: {verified_count}/{len(chapter.sections)} 节通过事实核查，发现 {total_issues} 个问题")

        # 如果启用版本选择，添加此版本到选择池
        if self.enable_version_selection and self.book_finalizer:
            self.add_chapter_version(chapter)

        return chapter

    async def _repair_cross_chapter_issues(
        self,
        chapter: GeneratedChapter,
        previous_chapter: GeneratedChapter,
        chapter_context: Dict[str, Any],
        issues: List[Dict[str, Any]],
    ) -> GeneratedChapter:
        """跨章节严重问题优先做章节内局部修复，不轻易全书重写。"""
        issue_lines = "\n".join(
            f"- [{item.get('severity', 'medium')}] {item.get('type', '一致性')}: {item.get('description', '')}"
            for item in issues
        )
        hard_facts = chapter_context.get("hard_facts", [])
        hard_fact_text = "\n".join(f"- {fact}" for fact in hard_facts[:12]) if hard_facts else "（无额外硬事实）"
        prompt = f"""请只修复当前章节中与前一章不一致的内容，保持文风、结构和大部分文字不变。

【前一章结尾】
{previous_chapter.full_content[-1800:]}

【当前章节全文】
{chapter.full_content}

【必须修复的问题】
{issue_lines}

【硬事实守卫】
{hard_fact_text}

【修复原则】
1. 只改动出现矛盾的句子或段落，能局部修就不要整章重写
2. 人名、关系、时间链必须与前文一致
3. 删除任何编辑批注、写作提示、提纲残留
4. 不新增没有依据的大事件
5. 直接输出修复后的整章正文，保留原有小节标题
"""
        try:
            rewritten = await self.llm.complete(
                [
                    {"role": "system", "content": "你是一位严谨但克制的传记编辑，擅长做最小必要改动。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.25,
                max_tokens=16384,
            )
            normalized = ContentCleaner.clean(rewritten)
            if not normalized:
                return chapter
            chapter = self._replace_chapter_sections_from_text(chapter, normalized)
        except Exception as exc:
            logger.warning(f"跨章节局部修复失败: {exc}")
        return chapter

    def _replace_chapter_sections_from_text(
        self,
        chapter: GeneratedChapter,
        rewritten_text: str,
    ) -> GeneratedChapter:
        """将整章修复文本按现有小节标题切回章节结构。"""
        text = rewritten_text.strip()
        for section in chapter.sections:
            marker = f"## {section.title}"
            if marker not in text:
                continue
        for index, section in enumerate(chapter.sections):
            current_marker = f"## {section.title}"
            start = text.find(current_marker)
            if start < 0:
                continue
            start += len(current_marker)
            next_start = len(text)
            for next_section in chapter.sections[index + 1:]:
                next_marker = f"## {next_section.title}"
                pos = text.find(next_marker, start)
                if pos >= 0:
                    next_start = pos
                    break
            new_content = text[start:next_start].strip()
            if new_content:
                section.content = ContentCleaner.clean(new_content)
                section.word_count = count_chinese_words(section.content)
        return chapter

    async def _run_six_dimension_review(
        self,
        chapter: GeneratedChapter,
        chapter_context: Dict,
        previous_chapter: Optional[GeneratedChapter] = None
    ):
        """执行六维并行审查"""
        logger.info("开始六维并行审查...")

        # 构建章节完整内容
        chapter_content = chapter.full_content
        chapter_id = f"chapter_{chapter.outline.order}"

        # 构建审查上下文
        review_context = {
            "chapter_id": chapter_id,
            "chapter_title": chapter.outline.title,
            "previous_chapters": [
                {"chapter_id": f"chapter_{c.outline.order}", "content": c.full_content}
                for c in self._generated_chapters[-3:]  # 最近3章
            ],
            "character_profiles": chapter_context.get("character_profiles", {}),
            "subject_profile": chapter_context.get("subject_profile", {}),
            "timeline": chapter_context.get("timeline", []),
            "book_outline": chapter_context.get("book_outline", {}),
            "established_facts": chapter_context.get("established_facts", []),
            "active_plot_threads": chapter_context.get("active_plot_threads", []),
        }

        try:
            # 执行六维并行审查
            result = self.six_dimension_reviewer.review(chapter_content, review_context)

            # 缓存结果
            self._six_dimension_results[chapter_id] = result

            # 记录审查结果
            logger.info(
                f"六维审查完成: 综合得分={result.overall_score}, "
                f"问题数={result.total_issues_count}, "
                f"耗时={result.review_duration_ms}ms"
            )

            # 将六维审查发现的问题合并到章节中
            self._merge_six_dimension_issues(chapter, result)

            # 生成六维审查报告
            report = self.six_dimension_reviewer.generate_review_summary(result)
            logger.info(f"\n{report}")

        except Exception as e:
            logger.error(f"六维并行审查失败: {e}")

    def _merge_six_dimension_issues(
        self,
        chapter: GeneratedChapter,
        result: ParallelReviewResult
    ):
        """将六维审查发现的问题合并到章节中"""
        if not result.aggregated_issues:
            return

        # 只将严重和高优先级问题合并到第一节
        if chapter.sections:
            first_section = chapter.sections[0]

            for issue in result.aggregated_issues:
                if issue.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH):
                    issue_text = f"[六维审查-{issue.dimension}] {issue.description}"
                    if issue.suggestion:
                        issue_text += f" (建议: {issue.suggestion})"
                    first_section.issues.append(issue_text)

        # 更新章节元数据
        if not chapter.metadata:
            chapter.metadata = {}

        chapter.metadata["six_dimension_review"] = {
            "overall_score": result.overall_score,
            "dimension_scores": {
                dim: report.dimension_scores.get(dim).score if report.dimension_scores.get(dim) else 0
                for dim, report in result.dimension_reports.items()
            },
            "critical_issues": result.critical_issues_count,
            "high_priority_issues": result.high_priority_issues_count,
            "total_issues": result.total_issues_count,
            "review_timestamp": result.timestamp.isoformat()
        }

    def get_six_dimension_report(self, chapter_order: int) -> Optional[str]:
        """获取指定章节的六维审查报告"""
        chapter_id = f"chapter_{chapter_order}"
        result = self._six_dimension_results.get(chapter_id)

        if result and self.six_dimension_reviewer:
            return self.six_dimension_reviewer.generate_review_summary(result)

        return None

    def get_all_six_dimension_results(self) -> Dict[str, Dict]:
        """获取所有六维审查结果"""
        return {
            chapter_id: result.to_dict()
            for chapter_id, result in self._six_dimension_results.items()
        }

    def add_chapter_version(self, chapter: GeneratedChapter, quality_score: Optional[float] = None):
        """
        添加一个章节版本到终版选择池

        Args:
            chapter: 已审查的章节
            quality_score: 质量评分（可选，自动计算）
        """
        if quality_score is None:
            # 计算质量评分：字数比例 + 验证状态
            target_words = chapter.outline.target_words
            word_ratio = min(chapter.word_count / max(target_words, 1), 1.0)
            verified_bonus = 1.0 if all(s.facts_verified for s in chapter.sections) else 0.0
            quality_score = word_ratio * 5 + verified_bonus * 5

        self.book_finalizer.add_chapter_version(chapter, quality_score)

        # 同时更新本地版本历史
        chapter_order = chapter.outline.order
        if chapter_order not in self._chapter_versions:
            self._chapter_versions[chapter_order] = []
        self._chapter_versions[chapter_order].append(chapter)

        logger.info(f"第{chapter.outline.order}章已添加到版本池，评分: {quality_score:.1f}, "
                   f"该章节历史版本数: {len(self._chapter_versions[chapter_order])}")

    def regenerate_chapter(self, chapter_order: int) -> Optional[GeneratedChapter]:
        """
        标记某个章节需要重新生成

        Args:
            chapter_order: 章节序号

        Returns:
            如果该章节已存在版本，返回最新版本供参考
        """
        if chapter_order in self._chapter_versions:
            versions = self._chapter_versions[chapter_order]
            logger.info(f"第{chapter_order}章将重新生成，历史版本数: {len(versions)}")
            return versions[-1] if versions else None
        return None

    def get_version_report(self) -> str:
        """获取版本选择报告"""
        if self.book_finalizer:
            return self.book_finalizer.version_selector.get_version_history_report()
        return "版本选择功能未启用"
    
    async def post_process_book(
        self,
        book: BiographyBook
    ) -> BiographyBook:
        """书籍后处理 - 全书籍级别的一致性检查和优化"""
        logger.info("开始全书籍后处理...")

        # 1. 检查全书人物称谓一致性
        await self._check_book_wide_character_consistency(book)

        # 2. 检查未回收的伏笔
        await self._check_unresolved_foreshadowing(book)

        # 3. 生成全书摘要
        book.metadata["generation_summary"] = {
            "total_chapters": len(book.chapters),
            "total_words": book.total_word_count,
            "verified_sections": sum(
                1 for c in book.chapters for s in c.sections if s.facts_verified
            ),
            "total_issues": sum(
                len(s.issues) for c in book.chapters for s in c.sections
            ),
        }

        fact_debt_summary = self.dual_agent.settle_fact_debt_against_book(book)
        book.metadata["fact_debt_summary"] = fact_debt_summary
        book.metadata["generation_summary"]["pending_fact_debt"] = fact_debt_summary.get("pending", 0)

        # 持久化事实债务（便于人工复核）
        book_dir = self.formatter.output_dir / sanitize_filename(book.id)
        book_dir.mkdir(parents=True, exist_ok=True)
        summary_path = book_dir / "fact_debt_summary.json"
        summary_path.write_text(
            json.dumps(
                {
                    "summary": fact_debt_summary,
                    "records": self.dual_agent.get_fact_debt_records(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        pending_path = book_dir / "fact_debt_pending.jsonl"
        with open(pending_path, "w", encoding="utf-8") as f:
            for record in self.dual_agent.get_fact_debt_records():
                if record.get("status") == "resolved":
                    continue
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        logger.info("全书籍后处理完成")
        return book

    async def _check_book_wide_character_consistency(self, book: BiographyBook):
        """检查全书人物称谓一致性"""
        logger.info("检查全书人物称谓一致性...")

        # 收集所有人物出现
        character_appearances: Dict[str, List[int]] = {}
        for chapter in book.chapters:
            for section in chapter.sections:
                # 简单规则：查找可能的人名
                import re
                potential_names = re.findall(r'[\u4e00-\u9fff]{2,4}(?=说|道|问|答)', section.content)
                for name in potential_names:
                    if name not in character_appearances:
                        character_appearances[name] = []
                    character_appearances[name].append(chapter.outline.order)

        # 检查是否有人物在不同章节有不同称谓
        for name, chapters in character_appearances.items():
            if len(chapters) > 3:  # 在多个章节出现
                logger.debug(f"人物 '{name}' 出现在章节: {chapters}")

    async def _check_unresolved_foreshadowing(self, book: BiographyBook):
        """检查未回收的伏笔"""
        logger.info("检查未回收的伏笔...")

        # 这里可以添加更复杂的伏笔追踪逻辑
        # 目前只是占位

    async def finalize_book(
        self,
        book: BiographyBook,
        formats: List[str] = ["txt", "md", "json", "epub"],
        cover_image: Optional[Path] = None,
        use_version_selection: bool = True
    ) -> Dict[str, Path]:
        """
        最终输出书籍

        Args:
            book: 传记书籍对象
            formats: 输出格式列表，可选: txt, md, json, epub
            cover_image: 封面图片路径（EPUB格式需要）
            use_version_selection: 是否使用版本选择（从多个版本中选最佳）

        Returns:
            导出的文件路径字典
        """
        book.completed_at = datetime.now()

        # 后处理
        book = await self.post_process_book(book)

        # 使用版本选择生成终版
        if use_version_selection and self.enable_version_selection and self.book_finalizer:
            logger.info("使用版本选择器生成终版书籍...")

            # 获取大纲
            outline = book.outline

            # 生成终版（自动选择最佳章节版本）
            final_book = self.book_finalizer.finalize_book(outline, book.id)

            # 导出所有格式
            saved_files = self.book_finalizer.export_all_formats(final_book, cover_image)

            # 同时保存元数据和章节文件到书籍目录
            book_dir = self.formatter.output_dir / sanitize_filename(book.id)
            book_dir.mkdir(exist_ok=True)

            # 保存版本选择报告
            report = self.book_finalizer.version_selector.get_version_history_report()
            report_path = book_dir / "version_report.md"
            report_path.write_text(report, encoding='utf-8')
            saved_files["version_report"] = report_path

            logger.info(f"终版书籍生成完成，共 {len(final_book.chapters)} 章，"
                       f"{final_book.total_word_count}字")

            return saved_files
        else:
            # 不使用版本选择，直接保存当前版本
            logger.info("直接保存当前版本（不使用版本选择）...")
            saved_files = await self.formatter.save_book(book, formats, cover_image)
            return saved_files
