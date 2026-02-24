"""第五层：审校与输出层 (Review & Output)"""
import json
import re
import difflib
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime
from loguru import logger

from src.llm_client import LLMClient
from src.models import (
    GeneratedSection, GeneratedChapter, BookOutline,
    Timeline, FactCheckResult, BiographyBook, CharacterProfile
)
from src.utils import save_json, count_chinese_words, sanitize_filename


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


class ConsistencyChecker:
    """一致性校验Agent"""
    
    def __init__(self, llm: LLMClient, timeline: Timeline):
        self.llm = llm
        self.timeline = timeline
        self.subject_name = timeline.subject.name if timeline.subject else "传主"
        self.quality_checker = ContentQualityChecker()
        self.repetition_checker = ContentRepetitionChecker()
    
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
            confidence=1.0 - (len(violations) * 0.05)
        )
    
    async def _check_facts(self, section: GeneratedSection) -> List[Dict]:
        """检查基础事实"""
        violations = []
        content = section.content
        
        # 从时间线中提取关键事实
        timeline_facts = []
        for event in self.timeline.events:
            if event.title and len(event.title) > 2:
                timeline_facts.append(event.title)
        
        # 使用LLM检查事实冲突
        prompt = f"""请检查以下内容是否与已知事实存在冲突，并检测AI生成痕迹：

=== 已知事实（来自原始采访）===
{chr(10).join(timeline_facts[:10])}

=== 待检查内容 ===
{content[:1000]}

=== 检查要求 ===
1. 如果内容提及了上述事实，检查描述是否一致
2. 识别是否存在"无中生有"的人物或事件
3. 检查时间顺序是否合理
4. 【新增】检查是否包含AI占位符（如"待补充"、"模板内容"等）
5. 【新增】检查是否有明显的模板化、套话式表达
6. 【新增】检查内容是否有实质性信息，而非空洞填充

请以JSON格式返回发现的问题（如果没有问题返回空列表）：
[
  {{
    "type": "事实冲突/无中生有/时间错误/AI占位符/模板化内容/内容空洞",
    "description": "具体问题描述",
    "location": "问题出现在文中的位置"
  }}
]
"""
        
        messages = [
            {"role": "system", "content": "你是一位严格的事实核查编辑，专门检测AI生成内容的痕迹。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await self.llm.complete(messages, temperature=0.2)
            issues = self._parse_json_array(response)
            
            for issue in issues:
                issue_type = issue.get("type", "未知")
                severity = "high" if any(kw in issue_type for kw in ["冲突", "占位符"]) else "medium"
                violations.append({
                    "type": issue_type,
                    "description": issue.get("description", ""),
                    "severity": severity
                })
        except Exception as e:
            logger.warning(f"事实核查失败: {e}")
        
        return violations
    
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
                    "severity": "low"
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


class DualAgentReviewer:
    """双重Agent博弈机制"""
    
    def __init__(self, llm: LLMClient, timeline: Timeline):
        self.llm = llm
        self.writer_agent = None  # 将在需要时初始化
        self.checker_agent = ConsistencyChecker(llm, timeline)
    
    async def review_and_refine(
        self,
        section: GeneratedSection,
        chapter_context: Dict,
        max_iterations: int = 2
    ) -> GeneratedSection:
        """
        审查并优化内容
        """
        current_section = section
        
        for iteration in range(max_iterations):
            # 1. 检查当前内容
            check_result = await self.checker_agent.check_section(
                current_section, chapter_context
            )
            
            # 统计各类问题
            high_severity = [v for v in check_result.violations if v.get("severity") == "high"]
            medium_severity = [v for v in check_result.violations if v.get("severity") == "medium"]
            
            if not high_severity and not medium_severity:
                logger.info(f"内容通过审查，无违规项")
                current_section.facts_verified = True
                break
            
            logger.warning(f"发现 {len(high_severity)} 个严重问题，{len(medium_severity)} 个中等问题")
            
            # 2. 如果有严重违规，重写
            if high_severity and iteration < max_iterations - 1:
                current_section = await self._rewrite_section(
                    current_section,
                    check_result.violations,
                    chapter_context
                )
            else:
                # 标记问题但保留内容
                current_section.issues = [v.get("description", "") for v in check_result.violations]
                current_section.facts_verified = len(high_severity) == 0
                break
        
        return current_section
    
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
    """输出格式化器"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def save_book(
        self,
        book: BiographyBook,
        formats: List[str] = ["txt", "md", "json"]
    ) -> Dict[str, Path]:
        """
        保存书籍到多种格式
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
    """审校与输出层主类"""
    
    def __init__(
        self,
        llm: LLMClient,
        timeline: Timeline,
        output_dir: Path
    ):
        self.llm = llm
        self.timeline = timeline
        self.dual_agent = DualAgentReviewer(llm, timeline)
        self.formatter = OutputFormatter(output_dir)
    
    async def review_chapter(
        self,
        chapter: GeneratedChapter,
        chapter_context: Dict
    ) -> GeneratedChapter:
        """审查并优化整章"""
        logger.info(f"开始审查第{chapter.outline.order}章...")
        
        reviewed_sections = []
        for section in chapter.sections:
            reviewed = await self.dual_agent.review_and_refine(
                section, chapter_context
            )
            reviewed_sections.append(reviewed)
        
        chapter.sections = reviewed_sections
        
        # 统计
        verified_count = sum(1 for s in chapter.sections if s.facts_verified)
        total_issues = sum(len(s.issues) for s in chapter.sections)
        logger.info(f"审查完成: {verified_count}/{len(chapter.sections)} 节通过事实核查，发现 {total_issues} 个问题")
        
        return chapter
    
    async def finalize_book(
        self,
        book: BiographyBook
    ) -> Dict[str, Path]:
        """最终输出书籍"""
        book.completed_at = datetime.now()
        
        saved_files = await self.formatter.save_book(book)
        
        return saved_files
