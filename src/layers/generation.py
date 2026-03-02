"""第四层：迭代生成层 (Iterative Generation)

双Agent架构集成版本：
- Context Agent: 在Generation层之前，组装创作任务书
- Data Agent: 在Generation层之后，提取数据并同步到存储层

提示词模板系统版本：
- 使用Jinja2模板引擎管理提示词
- 支持分层引用披露（L0-L3）
- 支持风格模板切换
"""
import asyncio
import re
from typing import List, Dict, Optional, AsyncIterator, Tuple
from pathlib import Path
from datetime import datetime
from loguru import logger

from src.llm_client import LLMClient
from src.models import (
    BookOutline, ChapterOutline, SectionOutline,
    GeneratedSection, GeneratedChapter, GlobalState, EnhancedGlobalState,
    WritingStyle, InterviewMaterial
)
from src.layers.data_ingestion import VectorStore
from src.utils import count_chinese_words, truncate_text, generate_id, sanitize_filename
from src.context_assembler import (
    ProgressiveContextAssembler, ContextLevel, ContextLevelSelector,
    ContextPriority,
    TokenBudget, LoadedContext
)
from src.prompt_manager import PromptManager, get_prompt_manager

# 双Agent架构导入
from src.agents import ContextAgent, ContextContract, DataAgent, ExtractionResult
from src.observability.runtime_monitor import get_runtime_monitor


# AI占位符检测模式
PLACEHOLDER_PATTERNS = [
    r'鉴于.*尚待补充',
    r'此处为通用型.*模板',
    r'此处需要补充.*',
    r'.*待补充.*',
    r'.*待完善.*',
    r'.*待后续完善.*',
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
]

# 模板化套话检测
TEMPLATE_PHRASES = [
    '尘埃在光柱中飞舞',
    '尘埃在光柱中起舞',
    '苦涩中带着回甘',
    '滴答，滴答',
    '咔嚓，咔嚓',
    '春蚕噬叶',
    '细雨敲窗',
    '时光的流逝',
    '命运的齿轮',
    '暴风雨前的宁静',
    '真相正伺机而动',
    '桌上摊开的文件',
    '端起一只搪瓷杯',
    '端起一只瓷杯',
    '凉茶早已凉透',
    '墙上的挂钟',
    '窗外的老槐树',
    '窗外的梧桐树',
]


# 注意：ContextAssembler 类已被 ProgressiveContextAssembler 替代
# 旧实现保留在 src/context_assembler.py 中用于向后兼容
# 新的渐进式上下文加载请使用 ProgressiveContextAssembler


class ContextAssembler:
    """向后兼容包装器.

    兼容旧调用方行为：
    1. `assemble_context` 返回 prompt-ready dict（而不是 LoadedContext）。
    2. `_retrieve_materials_enhanced` 只返回素材文本（忽略 coverage_info）。
    """

    def __init__(
        self,
        llm: LLMClient,
        vector_store: VectorStore,
        budget: Optional[TokenBudget] = None,
    ):
        self._delegate = ProgressiveContextAssembler(
            llm=llm,
            vector_store=vector_store,
            budget=budget or TokenBudget(),
        )

    async def assemble_context(
        self,
        section: SectionOutline,
        chapter: ChapterOutline,
        outline: BookOutline,
        global_state: Dict,
        previous_section_summary: Optional[str] = None,
        generated_sections: Optional[List[GeneratedSection]] = None,
    ) -> Dict[str, str]:
        loaded = await self._delegate.assemble_context(
            section=section,
            chapter=chapter,
            outline=outline,
            global_state=global_state,
            level=ContextLevel.L1_ESSENTIAL,
            previous_section_summary=previous_section_summary,
            generated_sections=generated_sections,
        )
        return self._delegate.to_prompt_context(loaded)

    async def _retrieve_materials_enhanced(
        self,
        section: SectionOutline,
        chapter: ChapterOutline,
        budget: Optional[int] = None,
    ) -> str:
        materials_text, _ = await self._delegate._retrieve_materials_enhanced(
            section=section,
            chapter=chapter,
            budget=budget or (self._delegate.budget.context // 3),
        )
        return materials_text


class ContentGenerationEngine:
    """内容扩写引擎 - 使用提示词模板系统"""

    def __init__(self, llm: LLMClient, prompt_manager: Optional[PromptManager] = None):
        self.llm = llm
        self.max_retries = 3
        # 初始化提示词管理器
        self.prompt_manager = prompt_manager or get_prompt_manager()
        self.runtime_monitor = get_runtime_monitor(project_root=Path(__file__).resolve().parents[2])
    
    async def generate_section(
        self,
        context: Dict[str, str],
        style: WritingStyle,
        target_words: int
    ) -> GeneratedSection:
        """
        生成单节内容
        """
        # 构建完整提示词
        system_prompt = self._build_system_prompt(style)
        user_prompt = self._build_generation_prompt(context, target_words)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        section_title = context.get("section_title", "小节")
        logger.info(f"正在生成内容: {section_title}...")
        self.runtime_monitor.log_event(
            stage="generation.section",
            status="started",
            message=f"开始生成小节: {section_title}",
            metadata={"target_words": target_words},
        )

        content, placeholder_issues = await self._generate_with_quality_gate(
            messages=messages,
            context=context,
            target_words=target_words,
            section_title=section_title,
        )

        actual_words = count_chinese_words(content)
        
        # 如果字数不足，进行扩写
        if actual_words < target_words * 0.8:
            logger.warning(f"字数不足 ({actual_words}/{target_words})，进行扩写...")
            content = await self._expand_content(
                content, context, target_words - actual_words
            )
            content = self._post_process_content(content)
            actual_words = count_chinese_words(content)

        self.runtime_monitor.save_json_artifact(
            name=f"section_{sanitize_filename(section_title)}.json",
            data={
                "section_title": section_title,
                "target_words": target_words,
                "actual_words": actual_words,
                "placeholder_issues": placeholder_issues,
                "content_preview": truncate_text(content, 800),
            },
            stage="04_generation",
        )
        self.runtime_monitor.log_event(
            stage="generation.section",
            status="completed",
            message=f"小节生成完成: {section_title}",
            metadata={
                "target_words": target_words,
                "actual_words": actual_words,
                "issues": len(placeholder_issues),
            },
        )
        
        return GeneratedSection(
            id=generate_id("section_content"),
            chapter_id="",
            title=context.get("section_title", "小节"),
            content=content,
            word_count=actual_words,
            generation_time=datetime.now()
        )

    async def _generate_with_quality_gate(
        self,
        messages: List[Dict[str, str]],
        context: Dict[str, str],
        target_words: int,
        section_title: str,
    ) -> Tuple[str, List[str]]:
        """质量门控生成：检测占位符/模板化内容并自动重写。"""
        best_content = ""
        best_issues: List[str] = []
        best_issue_count = float("inf")

        for attempt in range(1, self.max_retries + 1):
            if attempt == 1:
                candidate = await self.llm.complete(
                    messages,
                    temperature=0.7,
                    max_tokens=min(4000, max(1200, target_words * 2)),
                )
            else:
                candidate = await self._rewrite_problematic_content(
                    original_content=best_content,
                    issues=best_issues,
                    context=context,
                    target_words=target_words,
                )

            candidate = self._post_process_content(candidate)
            issues = self._detect_placeholders(candidate)

            self.runtime_monitor.log_event(
                stage="generation.quality_gate",
                status="running" if issues else "completed",
                message=f"小节质量检测: {section_title} (attempt {attempt}/{self.max_retries})",
                metadata={"issues": issues[:8], "issue_count": len(issues)},
            )

            if len(issues) < best_issue_count:
                best_content = candidate
                best_issues = issues
                best_issue_count = len(issues)

            if not issues:
                return candidate, []

            logger.warning(
                f"小节[{section_title}] 检测到占位符/模板化问题(第{attempt}次): {issues[:4]}"
            )

        return best_content, best_issues

    async def _rewrite_problematic_content(
        self,
        original_content: str,
        issues: List[str],
        context: Dict[str, str],
        target_words: int,
    ) -> str:
        """对已生成但质量不达标的内容做定向重写。"""
        issue_text = "\n".join(f"- {item}" for item in issues[:8]) if issues else "- 存在模板化表达"
        rewrite_prompt = f"""请重写以下传记内容，彻底消除占位符和模板化表达，并保持事实不变。

【检测到的问题】
{issue_text}

【原文】
{original_content}

【必须使用的素材】
{context.get('materials', '')}

【重写要求】
1. 删除所有“待补充/待完善/此处需要展开”类占位符
2. 删除套路化句式，改为素材驱动的具体叙述
3. 明确时间、人物、地点线索，避免空泛结论
4. 不得引入素材中不存在的新事实
5. 目标长度约 {target_words} 字
6. 直接输出正文，不要解释
"""
        messages = [
            {"role": "system", "content": "你是一位严格的非虚构传记编辑，负责把模板化文本改为可验证细节文本。"},
            {"role": "user", "content": rewrite_prompt},
        ]
        rewritten = await self.llm.complete(
            messages,
            temperature=0.45,
            max_tokens=min(4000, max(1200, target_words * 2)),
        )
        return rewritten.strip()
    
    async def generate_section_stream(
        self,
        context: Dict[str, str],
        style: WritingStyle,
        context_level: ContextLevel = ContextLevel.L1_ESSENTIAL
    ) -> AsyncIterator[str]:
        """流式生成内容"""
        system_prompt = self._build_system_prompt(style, context_level)
        user_prompt = self._build_generation_prompt(context, 0)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        async for chunk in self.llm.complete_stream(messages, temperature=0.7):
            yield chunk
    
    def _build_system_prompt(self, style: WritingStyle, context_level: ContextLevel = ContextLevel.L1_ESSENTIAL) -> str:
        """构建系统提示词 - 使用模板系统"""
        try:
            # 使用提示词管理器渲染风格化系统提示词
            from src.prompt_manager import WritingStyle as PMWritingStyle

            pm_style = PMWritingStyle(style.value)
            return self.prompt_manager.render_style_prompt(
                style=pm_style,
                context={"context_level": context_level.value}
            )
        except Exception as e:
            logger.warning(f"模板渲染失败，使用回退方案: {e}")
            # 回退到基础提示词
            return self._build_fallback_system_prompt(style)

    def _build_fallback_system_prompt(self, style: WritingStyle) -> str:
        """构建回退系统提示词（当模板系统不可用时）"""
        style_descriptions = {
            "documentary": "纪实风格：客观、真实、详尽的记录风格",
            "literary": "文学风格：注重文学性和艺术性",
            "investigative": "调查风格：类似深度报道，注重挖掘和揭示",
            "memoir": "回忆录风格：第一人称回忆式叙述"
        }

        style_desc = style_descriptions.get(style.value, "纪实风格")

        return f"""你是一位专业的传记作家。{style_desc}

=== 角色锚定 ===
你是一位对事实极度苛求的非虚构传记作家。你的每一句描写都必须能指向采访素材中的具体来源。
你憎恨空洞的文学修饰，认为那是对传主经历的不尊重。

=== 强制要求（违反将导致内容被废弃） ===
1. 【素材引用】必须使用提供的采访素材中的具体细节：人名、地名、时间、对话、数字
2. 【来源标注】引用采访内容时，在括号中标注来源，如（来源：素材1）
3. 【禁止虚构】不得编造未在素材中出现的具体人物、事件、地点
4. 【时代锚定】必须明确时间点，结合当时的社会背景
5. 【具体信息密度】每300字必须包含至少1个具体时间、地点、数字或人物对话

=== 禁止事项（绝对禁止出现） ===
1. 【占位符】"待补充"、"待完善"、"此处需要展开"、"鉴于...尚待补充"等
2. 【模板套话】"尘埃在光柱中飞舞"、"苦涩中带着回甘"、"命运的齿轮"等
3. 【空泛表述】"中国社会发展的重要时期"、"那是一个特殊的年代"等
4. 【AI声明】"我为您撰写"、"这是一个通用模板"等AI身份暴露语句
5. 【悬念套路】"暴风雨前的宁静"、"真相伺机而动"、"更大的挑战在等待"等
6. 【心理标签】"陷入了沉思"、"百感交集"、"心中充满"、"倍感欣慰"等无具体言行支撑的情感标签
7. 【时间套路】"时光荏苒"、"转眼间"、"岁月如梭"、"白驹过隙"等
8. 【场景套路】"月光如水"、"微风轻拂"、"阳光正好"、"点了一根烟"、"望着远方"等

=== 写作要求 ===
1. 基于提供的素材进行扩写，不要脱离素材随意发挥
2. 注重细节描写：场景、动作、对话、心理活动
3. 适当运用感官描写（视觉、听觉、嗅觉等）
4. 时间线和人物关系必须与上下文保持一致
5. 情感表达要符合指定的情感基调
6. 使用中文写作，语言流畅自然
7. 章节结尾应自然收束，不要强行制造悬念
"""
    
    def _build_generation_prompt(self, context: Dict[str, str], target_words: int) -> str:
        """构建生成提示词"""
        word_hint = f"\n=== 字数要求 ===\n本节目标字数：{target_words}字\n" if target_words else ""

        # 检查是否为推断内容
        is_inferred = context.get('is_inferred', False)
        inference_hint = ""
        if is_inferred:
            inference_basis = context.get('inference_basis', [])
            basis_text = '\n'.join([f"  - {b}" for b in inference_basis]) if inference_basis else "  - 基于时代背景和社会规律推断"
            inference_hint = f"""
=== ⚠️ 重要提示：本节为推断内容 ===
本节内容基于人物的出生年份、地域背景、时代特征等信息进行合理推断，用于补足采访信息的空白。

推断依据：
{basis_text}

写作要求：
1. 内容必须符合时代背景和社会规律，力求合理但不编造具体事件
2. 描述应为"类别性"而非"具体性"——例如可以说"从事个体经营"而非"开了一家服装店"
3. 避免虚构具体人名、地名、数字，使用概括性表述
4. 在文中不需要标注"这是推断内容"，但要确保语气是描述性的而非确定性的
5. 可以描述典型的环境氛围、社会风气、常见的生活状态
6. 如果素材中有任何相关线索，优先使用素材中的信息

===
"""

        return f"""请根据以下信息撰写传记内容：

{context.get('global', '')}

{context.get('section', '')}

{context.get('materials', '')}

{context.get('continuity', '')}

{context.get('era', '')}

{context.get('sensory', '')}
{word_hint}
{inference_hint}

=== 段落级写作指引（如适用）===
{self._build_paragraph_guidance(context.get('paragraph_outlines', []), context.get('pacing', 'moderate'))}

【输出要求】
1. 直接输出正文内容，不要包含章节标题
2. 确保内容紧扣大纲，事实准确，细节丰富
3. 必须使用素材中的具体细节，禁止泛泛而谈
4. 注重感官描写，让场景可感可知
5. 段落之间过渡自然，逻辑清晰
6. 结尾自然收束，不要强行制造悬念
"""

    def _build_paragraph_guidance(self, paragraph_outlines: list, pacing: str) -> str:
        """构建段落级写作指引"""
        if not paragraph_outlines:
            return "（本节无段落级规划，请按常规方式展开）"

        pacing_guide = {
            "slow": "节奏舒缓，适合描写和反思",
            "moderate": "节奏适中，叙述与描写平衡",
            "fast": "节奏紧凑，以行动和对话为主",
            "mixed": "节奏起伏，张弛有度"
        }.get(pacing, "节奏适中")

        parts = [f"本节整体节奏：{pacing_guide}", "段落安排："]

        for para in paragraph_outlines:
            para_type_name = {
                "narrative": "叙述",
                "dialogue": "对话",
                "description": "描写",
                "reflection": "思考"
            }.get(para.get('type', 'narrative'), para.get('type', '叙述'))

            detail_hint = f"必须包含：{', '.join(para.get('key_details', [])[:2])}" if para.get('key_details') else ""
            sensory_hint = f"侧重感官：{', '.join(para.get('sensory_focus', []))}" if para.get('sensory_focus') else ""

            parts.append(
                f"  第{para.get('order')}段（{para_type_name}）：{para.get('purpose', '推进叙事')} "
                f"{detail_hint} {sensory_hint}（约{para.get('target_words', 150)}字）"
            )

        return "\n".join(parts)
    
    def _post_process_content(self, content: str) -> str:
        """后处理生成的内容"""
        # 移除可能的格式标记
        content = content.strip()
        
        # 移除开头的标题标记
        if content.startswith("#"):
            content = content.lstrip("#").strip()
        
        # 规范化段落
        content = content.replace("\n\n\n", "\n\n")
        
        # 移除常见的AI前缀
        ai_prefixes = [
            "以下是", "以下是根据", "根据您提供的信息",
            "这是", "这是一段", "以下是撰写的内容",
        ]
        for prefix in ai_prefixes:
            if content.startswith(prefix):
                # 找到第一个句号或换行
                for i, char in enumerate(content):
                    if char in "。.\n" and i > len(prefix):
                        content = content[i+1:].strip()
                        break
        
        return content
    
    def _detect_placeholders(self, content: str) -> List[str]:
        """检测内容中的占位符和模板化问题"""
        issues = []
        
        # 检测占位符模式
        for pattern in PLACEHOLDER_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                issues.append(f"占位符: {matches[0]}")
        
        # 检测模板套话
        template_count = 0
        for phrase in TEMPLATE_PHRASES:
            if phrase in content:
                template_count += 1
        
        if template_count >= 3:
            issues.append(f"模板套话过多: 发现{template_count}个套路化表达")
        
        # 检测重复意象
        repetitive_patterns = [
            (r'晨光|晨光熹微|晨光透过', "晨光重复"),
            (r'夕阳|夕阳西下|落日', "夕阳重复"),
            (r'凉茶|茶水|茶杯', "喝茶重复"),
            (r'挂钟|钟表|滴答', "钟表重复"),
            (r'钢笔|笔尖|沙沙', "写字重复"),
            (r'窗外|看着窗外|望向窗外', "窗外重复"),
        ]
        
        for pattern, desc in repetitive_patterns:
            matches = re.findall(pattern, content)
            if len(matches) > 2:
                issues.append(f"意象重复: {desc}出现{len(matches)}次")
        
        return issues
    
    async def _expand_content(
        self,
        existing_content: str,
        context: Dict[str, str],
        additional_words: int
    ) -> str:
        """扩写内容以达到目标字数"""
        materials = context.get('materials', '')
        
        prompt = f"""请对以下内容进行扩写，增加约{additional_words}字的内容。

当前内容:
{existing_content}

可用素材（必须使用其中的细节）:
{materials}

扩写要求:
1. 在现有内容基础上增加具体细节描写
2. 补充：环境描写、心理活动、对话内容、他人反应等
3. 保持原有风格和叙事逻辑
4. 不要重复已有内容
5. 不要改变原有的事实陈述
6. 禁止添加"待补充"、"此处需要展开"等占位符

请输出完整的扩写后内容（包含原文）。
"""
        
        messages = [
            {"role": "system", "content": "你是一位擅长细节描写作家。你痛恨模板化表达和空洞的辞藻。"},
            {"role": "user", "content": prompt}
        ]
        
        expanded = await self.llm.complete(messages, temperature=0.65)
        return expanded.strip()


class IterativeGenerationLayer:
    """迭代生成层主类 - 双Agent架构

    架构流程:
    1. Context Agent (创作任务书工程师) - 生成前
       - 输入: 大纲、素材、前文、人物状态
       - 输出: ContextContract (7板块创作任务书)

    2. Generation Engine (内容扩写引擎) - 生成中
       - 输入: ContextContract 转换的提示词上下文
       - 输出: GeneratedChapter

    3. Data Agent (数据链工程师) - 生成后
       - 输入: GeneratedChapter
       - 输出: ExtractionResult (实体、状态、向量嵌入)
    """

    def __init__(
        self,
        llm: LLMClient,
        vector_store: VectorStore,
        token_budget: Optional[TokenBudget] = None,
        default_context_level: ContextLevel = ContextLevel.L1_ESSENTIAL,
        use_dual_agent: bool = True  # 是否启用双Agent架构
    ):
        self.llm = llm
        self.vector_store = vector_store
        self.default_context_level = default_context_level
        self.use_dual_agent = use_dual_agent

        # 渐进式上下文组装器（向后兼容）
        self.context_assembler = ProgressiveContextAssembler(
            llm=llm,
            vector_store=vector_store,
            budget=token_budget or TokenBudget()
        )

        # 双Agent架构组件
        if use_dual_agent:
            self.context_agent = ContextAgent(llm, vector_store)
            self.data_agent = DataAgent(llm, vector_store)
            logger.info("双Agent架构已启用: ContextAgent + DataAgent")
        else:
            self.context_agent = None
            self.data_agent = None

        # 初始化提示词管理器
        self.prompt_manager = get_prompt_manager()

        self.generation_engine = ContentGenerationEngine(llm, self.prompt_manager)

        # 章节元数据缓存（用于Data Agent）
        self._chapter_meta_cache: Dict[int, Dict] = {}
    
    async def generate_chapter(
        self,
        chapter_outline: ChapterOutline,
        book_outline: BookOutline,
        global_state: Dict,
        progress_callback: Optional[callable] = None,
        context_level: Optional[ContextLevel] = None
    ) -> GeneratedChapter:
        """
        生成完整章节 - 双Agent架构版本

        Args:
            chapter_outline: 章节大纲
            book_outline: 书籍大纲
            global_state: 全局状态
            progress_callback: 进度回调函数
            context_level: 上下文加载级别，默认使用L1_ESSENTIAL

        Returns:
            GeneratedChapter: 生成的章节
        """
        level = context_level or self.default_context_level
        logger.info(f"开始生成第{chapter_outline.order}章: {chapter_outline.title} [上下文级别: {level.value}]")

        sections = []
        previous_summary = None

        # 获取上一章的元数据（用于Context Agent）
        previous_chapter_meta = self._get_previous_chapter_meta(chapter_outline.order)

        for i, section_outline in enumerate(chapter_outline.sections):
            # 更新进度
            if progress_callback:
                progress_callback(f"第{chapter_outline.order}章 - {section_outline.title}")

            # 根据场景动态调整上下文级别
            effective_level = self._determine_section_context_level(
                level, chapter_outline.order, i, len(chapter_outline.sections)
            )

            # ========== Step 1: Context Agent 组装创作任务书 ==========
            if self.use_dual_agent and isinstance(global_state, EnhancedGlobalState):
                logger.info(f"  ContextAgent: 组装创作任务书...")
                context_contract = await self.context_agent.assemble_contract(
                    section=section_outline,
                    chapter=chapter_outline,
                    outline=book_outline,
                    global_state=global_state,
                    previous_section_summary=previous_summary,
                    previous_chapter_meta=previous_chapter_meta
                )

                # 检索素材并更新合同
                materials_text, coverage_info = await self.context_agent.retrieve_materials(
                    section=section_outline,
                    chapter=chapter_outline
                )

                # 将素材嵌入到合同中
                context_contract.materials = materials_text  # 动态添加属性
                context_contract.coverage_info = coverage_info

                # 转换为生成器需要的格式
                context = context_contract.to_prompt_context()
                logger.info(f"  ContextAgent: 创作任务书完成 [素材覆盖率: {coverage_info.get('status', '未知')}]")
            else:
                # 向后兼容：使用渐进式上下文组装器
                loaded_context = await self.context_assembler.assemble_context(
                    section=section_outline,
                    chapter=chapter_outline,
                    outline=book_outline,
                    global_state=global_state,
                    level=effective_level,
                    previous_section_summary=previous_summary,
                    generated_sections=sections
                )
                context = self.context_assembler.to_prompt_context(loaded_context)

            # 提取小节标题和段落级大纲
            context["section_title"] = section_outline.title
            if section_outline.paragraphs:
                context["paragraph_outlines"] = [
                    {
                        "order": p.order,
                        "type": p.paragraph_type,
                        "purpose": p.content_purpose,
                        "key_details": p.key_details,
                        "sensory_focus": p.sensory_focus,
                        "target_words": p.target_words,
                    }
                    for p in section_outline.paragraphs
                ]
            context["pacing"] = section_outline.pacing

            # 传递推断信息
            if section_outline.is_inferred:
                context["is_inferred"] = True
                context["inference_basis"] = section_outline.inference_basis
                logger.info(f"  生成推断内容: {section_outline.title}")

            # ========== Step 2: Generation Engine 生成内容 ==========
            section = await self.generation_engine.generate_section(
                context=context,
                style=book_outline.style,
                target_words=section_outline.target_words
            )
            section.chapter_id = chapter_outline.id

            sections.append(section)

            # 更新摘要供下一节使用
            previous_summary = truncate_text(section.content, 200)

            logger.info(f"  完成小节 {i+1}/{len(chapter_outline.sections)}: {section.word_count}字")

        # 生成过渡段落（简化版，不再强行制造悬念）
        transition = await self._generate_transition_simple(chapter_outline, book_outline)

        generated_chapter = GeneratedChapter(
            id=generate_id("chapter_gen", chapter_outline.order),
            outline=chapter_outline,
            sections=sections,
            transition_paragraph=transition
        )

        # ========== Step 3: Data Agent 处理数据链 ==========
        if self.use_dual_agent and isinstance(global_state, EnhancedGlobalState):
            logger.info(f"DataAgent: 开始处理章节数据...")

            extraction_result = await self.data_agent.process_chapter(
                generated_chapter=generated_chapter,
                outline=book_outline,
                global_state=global_state
            )

            # 更新全局状态
            global_state = await self.data_agent.update_global_state(
                result=extraction_result,
                global_state=global_state,
                generated_chapter=generated_chapter
            )

            # 生成向量嵌入
            await self.data_agent.generate_embeddings(
                result=extraction_result,
                generated_chapter=generated_chapter,
                project_root=global_state.book_id  # 假设book_id包含项目路径
            )

            # 缓存章节元数据供下一章使用
            if extraction_result.chapter_meta:
                self._chapter_meta_cache[chapter_outline.order] = {
                    "hook": {
                        "type": extraction_result.chapter_meta.hook_type,
                        "content": extraction_result.chapter_meta.hook_content,
                        "strength": extraction_result.chapter_meta.hook_strength
                    },
                    "ending": {
                        "time": extraction_result.chapter_meta.ending_time,
                        "location": extraction_result.chapter_meta.ending_location,
                        "emotion": extraction_result.chapter_meta.ending_emotion
                    },
                    "pattern": {
                        "opening": extraction_result.chapter_meta.pattern_opening,
                        "hook": extraction_result.chapter_meta.pattern_hook,
                        "emotion_rhythm": extraction_result.chapter_meta.emotion_rhythm,
                        "info_density": extraction_result.chapter_meta.info_density
                    }
                }

            logger.info(f"DataAgent: 章节数据处理完成 - "
                       f"实体{len(extraction_result.entities_appeared)}个, "
                       f"场景{len(extraction_result.scenes_chunked)}个")

        return generated_chapter

    def _get_previous_chapter_meta(self, current_chapter_order: int) -> Optional[Dict]:
        """获取上一章的元数据

        Args:
            current_chapter_order: 当前章节序号

        Returns:
            上一章的元数据，如果是第一章则返回None
        """
        if current_chapter_order <= 1:
            return None
        return self._chapter_meta_cache.get(current_chapter_order - 1)

    def _determine_section_context_level(
        self,
        base_level: ContextLevel,
        chapter_order: int,
        section_index: int,
        total_sections: int
    ) -> ContextLevel:
        """根据小节位置动态确定上下文级别

        策略：
        - 章节开头的小节可能需要更多上下文
        - 章节结尾的小节可能需要检查连贯性
        """
        # 如果是第一章第一节，提升一级以获取更多背景
        if chapter_order == 1 and section_index == 0:
            if base_level == ContextLevel.L0_MINIMAL:
                return ContextLevel.L1_ESSENTIAL
            elif base_level == ContextLevel.L1_ESSENTIAL:
                return ContextLevel.L2_EXTENDED

        # 如果是章节最后一个小节，可能需要检查连贯性
        if section_index == total_sections - 1 and base_level.value < ContextLevel.L2_EXTENDED.value:
            # 仅在L0/L1时提升到L2
            if base_level == ContextLevel.L0_MINIMAL:
                return ContextLevel.L1_ESSENTIAL

        return base_level
    
    async def _generate_transition_simple(
        self,
        chapter: ChapterOutline,
        outline: BookOutline
    ) -> Optional[str]:
        """生成简化的过渡段落 - 不再强行制造悬念"""
        # 如果是最后一章，不需要过渡
        if chapter.order >= outline.total_chapters:
            return None
        
        # 获取下一章标题
        next_chapter = None
        for c in outline.chapters:
            if c.order == chapter.order + 1:
                next_chapter = c
                break
        
        if not next_chapter:
            return None
        
        # 简化过渡，仅做内容预告，不制造虚假悬念
        return f"（本章完，下一章《{next_chapter.title}》将继续讲述{outline.subject_name or '传主'}的故事）"


# =============================================================================
# 便捷工厂函数
# =============================================================================

def create_generation_layer(
    llm: LLMClient,
    vector_store: VectorStore,
    context_level: ContextLevel = ContextLevel.L1_ESSENTIAL,
    token_budget: Optional[TokenBudget] = None,
    use_dual_agent: bool = True
) -> IterativeGenerationLayer:
    """创建配置好的生成层实例

    Args:
        llm: LLM客户端
        vector_store: 向量存储
        context_level: 默认上下文加载级别
        token_budget: Token预算配置
        use_dual_agent: 是否启用双Agent架构，默认为True

    Returns:
        IterativeGenerationLayer: 配置好的生成层实例

    Example:
        >>> from src.layers.generation import create_generation_layer, ContextLevel
        >>> layer = create_generation_layer(
        ...     llm=llm_client,
        ...     vector_store=vector_store,
        ...     context_level=ContextLevel.L2_EXTENDED,
        ...     use_dual_agent=True  # 启用双Agent架构
        ... )
    """
    return IterativeGenerationLayer(
        llm=llm,
        vector_store=vector_store,
        token_budget=token_budget,
        default_context_level=context_level,
        use_dual_agent=use_dual_agent
    )


async def generate_with_context_level(
    layer: IterativeGenerationLayer,
    chapter_outline: ChapterOutline,
    book_outline: BookOutline,
    global_state: Dict,
    context_level: ContextLevel,
    progress_callback: Optional[callable] = None
) -> GeneratedChapter:
    """使用指定上下文级别生成章节

    这是一个便捷的包装函数，用于临时切换上下文级别进行生成。

    Args:
        layer: 生成层实例
        chapter_outline: 章节大纲
        book_outline: 书籍大纲
        global_state: 全局状态
        context_level: 指定的上下文级别
        progress_callback: 进度回调

    Returns:
        GeneratedChapter: 生成的章节

    Example:
        >>> from src.layers.generation import generate_with_context_level, ContextLevel
        >>> chapter = await generate_with_context_level(
        ...     layer=generation_layer,
        ...     chapter_outline=chapter_outline,
        ...     book_outline=book_outline,
        ...     global_state=global_state,
        ...     context_level=ContextLevel.L3_COMPLETE  # 使用完整上下文审校
        ... )
    """
    return await layer.generate_chapter(
        chapter_outline=chapter_outline,
        book_outline=book_outline,
        global_state=global_state,
        progress_callback=progress_callback,
        context_level=context_level
    )


# 导出主要类供外部使用
__all__ = [
    # 核心类
    'ContextAssembler',
    'IterativeGenerationLayer',
    'ContentGenerationEngine',
    'ProgressiveContextAssembler',
    # 双Agent架构
    'ContextAgent',
    'ContextContract',
    'DataAgent',
    'ExtractionResult',
    # 配置类
    'ContextLevel',
    'TokenBudget',
    'ContextPriority',
    'LoadedContext',
    'ContextLevelSelector',
    # 便捷函数
    'create_generation_layer',
    'generate_with_context_level',
]
