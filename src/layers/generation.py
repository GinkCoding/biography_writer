"""第四层：迭代生成层 (Iterative Generation)"""
import asyncio
import re
from typing import List, Dict, Optional, AsyncIterator, Tuple
from pathlib import Path
from datetime import datetime
from loguru import logger

from src.llm_client import LLMClient
from src.models import (
    BookOutline, ChapterOutline, SectionOutline,
    GeneratedSection, GeneratedChapter, GlobalState,
    WritingStyle, InterviewMaterial
)
from src.layers.data_ingestion import VectorStore
from src.utils import count_chinese_words, truncate_text, generate_id


# AI占位符检测模式
PLACEHOLDER_PATTERNS = [
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


class ContextAssembler:
    """上下文组装器"""

    # 感官描述关键词库
    SENSORY_KEYWORDS = {
        "visual": ["看见", "看到", "望", "瞧", "颜色", "光线", "阳光", "影子", "模样", "穿着", "表情", "眼神"],
        "auditory": ["听见", "听到", "声音", "喊道", "说", "笑声", "哭声", "音乐", "歌声", "噪音", "寂静"],
        "olfactory": ["闻到", "气味", "香味", "臭味", "气息", "味道", "烟味", "花香", "饭菜香"],
        "tactile": ["感到", "摸", "触摸", "温度", "冷", "热", "疼痛", "粗糙", "光滑", "柔软", "坚硬"],
        "gustatory": ["尝到", "味道", "甜", "苦", "辣", "酸", "咸", "好吃", "难吃"],
    }

    def __init__(self, llm: LLMClient, vector_store: VectorStore):
        self.llm = llm
        self.vector_store = vector_store
    
    async def assemble_context(
        self,
        section: SectionOutline,
        chapter: ChapterOutline,
        outline: BookOutline,
        global_state: Dict,
        previous_section_summary: Optional[str] = None
    ) -> Dict[str, str]:
        """
        组装完整的生成上下文
        
        Returns:
            包含各部分内容的字典
        """
        # 1. 全局设定
        global_context = self._build_global_context(outline, global_state)
        
        # 2. 当前小节大纲
        section_context = self._build_section_context(section, chapter)
        
        # 3. 检索相关素材（增强版）- 返回文本和覆盖率信息
        material_context, coverage_info = await self._retrieve_materials_enhanced(section, chapter)
        
        # 4. 前文衔接
        continuity_context = self._build_continuity_context(
            previous_section_summary, global_state
        )
        
        # 5. 时代背景增强
        era_context = self._build_era_context_enhanced(chapter)

        # 6. 感官描写引导（新增）
        sensory_details = self._analyze_sensory_details(material_context)
        sensory_context = self._build_sensory_guidance(sensory_details, outline.style)

        # 7. 素材覆盖率警告
        if coverage_info.get("coverage_ratio", 0) < 0.3:
            logger.warning(f"素材覆盖率严重不足: {coverage_info['status']} ({coverage_info['total_materials']}条素材)")

        return {
            "global": global_context,
            "section": section_context,
            "materials": material_context,
            "continuity": continuity_context,
            "era": era_context,
            "sensory": sensory_context,  # 新增感官引导
            "coverage_info": coverage_info,
        }
    
    def _build_global_context(self, outline: BookOutline, global_state: Dict) -> str:
        """构建全局上下文"""
        subject = global_state.get("subject_name", "传主")
        age = global_state.get("subject_age", "未知")
        
        # 获取传记主题描述，避免为空
        theme_desc = ""
        if outline.chapters and outline.chapters[0].summary:
            theme_desc = outline.chapters[0].summary
        
        return f"""=== 全局设定 ===
传记标题: {outline.title}
传主姓名: {subject}
当前年龄: {age}岁
写作风格: {outline.style.value}
整体进度: {global_state.get('chapter_progress', '')}
传记主题: {theme_desc or '基于真实采访素材撰写的个人传记'}
"""
    
    def _build_section_context(self, section: SectionOutline, chapter: ChapterOutline) -> str:
        """构建小节上下文"""
        # 确保关联事件不为空
        events_str = ', '.join(section.key_events) if section.key_events else '基于采访素材展开'
        
        return f"""=== 当前小节大纲 ===
章节: {chapter.title} (第{chapter.order}章)
时间范围: {chapter.time_period_start or '待定'} 至 {chapter.time_period_end or '待定'}
小节: {section.title}
目标字数: {section.target_words}字
内容概要: {section.content_summary}
情感基调: {section.emotional_tone}
关联事件: {events_str}
"""
    
    async def _retrieve_materials_enhanced(
        self,
        section: SectionOutline,
        chapter: ChapterOutline
    ) -> Tuple[str, Dict]:
        """
        增强版素材检索 - 多路召回策略
        
        Returns:
            (materials_text, coverage_info)
        """
        # 构建多个检索查询
        queries = [
            f"{chapter.title} {section.title} {section.content_summary}",
            f"{chapter.time_period_start} {chapter.time_period_end} {section.key_events[0] if section.key_events else ''}",
            section.content_summary,
        ]
        
        all_results = []
        for query in queries:
            if query.strip():
                # search返回 [(material, score), ...]
                results = self.vector_store.search(query, n_results=8)
                all_results.extend(results)
        
        # 按相似度排序并去重
        all_results.sort(key=lambda x: x[1], reverse=True)
        
        seen_ids = set()
        unique_materials = []
        for m, score in all_results:
            if m.id not in seen_ids:
                seen_ids.add(m.id)
                unique_materials.append((m, score))
        
        # 限制数量但保留更多内容
        unique_materials = unique_materials[:10]
        
        # 计算素材覆盖率
        high_confidence = len([s for m, s in unique_materials if s > 0.7])
        medium_confidence = len([s for m, s in unique_materials if 0.5 <= s <= 0.7])
        coverage_info = {
            "total_materials": len(unique_materials),
            "high_confidence": high_confidence,
            "medium_confidence": medium_confidence,
            "coverage_ratio": min(len(unique_materials) / 5, 1.0),  # 5个素材视为满覆盖
        }
        
        if not unique_materials:
            coverage_info["status"] = "严重不足"
            return """=== 相关素材 ===
【⚠️ 严重警告】当前小节缺乏直接对应的采访素材。请基于已有章节上下文和时代背景进行合理推演，但必须：
1. 不虚构具体的人名、地名、机构名
2. 不编造具体的数字和数据
3. 如需补充细节，使用"据回忆"、"大约是"等模糊表述
4. 禁止使用"待补充"、"此处需要展开"等占位符
""", coverage_info
        
        if coverage_info["coverage_ratio"] < 0.4:
            coverage_info["status"] = "偏低"
        elif coverage_info["coverage_ratio"] < 0.7:
            coverage_info["status"] = "一般"
        else:
            coverage_info["status"] = "充足"
        
        material_texts = []
        for i, (m, score) in enumerate(unique_materials, 1):
            # 增加截断长度到400字，保留更多细节
            content = truncate_text(m.content, 400)
            material_texts.append(
                f"[素材{i}] 来源: {m.source_file} (相关度: {score:.2f})\n"
                f"内容: {content}\n"
            )
        
        # 添加覆盖率提示
        coverage_hint = f"""
【素材覆盖率】{coverage_info['status']}（共{len(unique_materials)}条素材，高相关度{high_confidence}条）
"""
        
        materials_text = "=== 相关素材（必须引用其中的具体细节）===\n" + "\n".join(material_texts) + coverage_hint
        
        return materials_text, coverage_info
    
    def _build_continuity_context(
        self,
        previous_summary: Optional[str],
        global_state: Dict
    ) -> str:
        """构建上下文衔接信息"""
        parts = ["=== 上下文衔接 ==="]
        
        # 上一节摘要
        if previous_summary:
            parts.append(f"上一节结尾:\n{truncate_text(previous_summary, 200)}")
        
        # 最近章节摘要
        summaries = global_state.get("previous_summaries", [])
        if summaries:
            parts.append(f"前几章脉络:\n" + " → ".join(summaries[-3:]))
        
        # 频繁出现的人物
        frequent_chars = global_state.get("frequent_characters", [])
        if frequent_chars:
            char_list = ", ".join([f"{name}({count}次)" for name, count in frequent_chars[:5]])
            parts.append(f"活跃人物: {char_list}")
        
        return "\n".join(parts)
    
    def _analyze_sensory_details(self, materials_text: str) -> Dict[str, List[str]]:
        """分析素材中的感官描述细节"""
        sensory_found = {k: [] for k in self.SENSORY_KEYWORDS.keys()}

        for material_line in materials_text.split('\n'):
            if material_line.startswith('内容:'):
                content = material_line[3:].strip()
                for sense_type, keywords in self.SENSORY_KEYWORDS.items():
                    for keyword in keywords:
                        if keyword in content and keyword not in sensory_found[sense_type]:
                            # 提取关键词周围的上下文
                            idx = content.find(keyword)
                            start = max(0, idx - 15)
                            end = min(len(content), idx + 20)
                            context = content[start:end]
                            sensory_found[sense_type].append(context)
                            break

        return sensory_found

    def _build_sensory_guidance(self, sensory_details: Dict[str, List[str]], style: WritingStyle) -> str:
        """构建感官描写引导"""
        # 读取风格配置
        import yaml
        from pathlib import Path

        style_file = Path(__file__).parent.parent.parent / "config" / "styles.yaml"
        try:
            with open(style_file, "r", encoding="utf-8") as f:
                styles_config = yaml.safe_load(f)
            style_config = styles_config.get("styles", {}).get(style.value, {})
            sensory_focus = style_config.get("sensory_focus", [])
        except:
            sensory_focus = []

        parts = ["=== 感官描写指引 ==="]

        # 从素材中提取的感官细节
        found_any = False
        for sense_type, contexts in sensory_details.items():
            if contexts:
                found_any = True
                type_name = {
                    "visual": "视觉", "auditory": "听觉", "olfactory": "嗅觉",
                    "tactile": "触觉", "gustatory": "味觉"
                }.get(sense_type, sense_type)
                parts.append(f"【{type_name}细节素材】")
                for ctx in contexts[:3]:  # 最多3个示例
                    parts.append(f"  - ...{ctx}...")

        if not found_any:
            parts.append("【提示】当前素材中感官描述较少，建议结合时代背景补充具体感官细节。")

        # 风格要求的感官重点
        if sensory_focus:
            parts.append(f"\n【本风格侧重的感官】{', '.join(sensory_focus)}")
            parts.append("请在写作中优先考虑以上感官类型的描写。")

        parts.append("\n【写作要求】")
        parts.append("1. 每300字至少包含1-2处感官细节描写")
        parts.append("2. 优先使用素材中已有的感官线索")
        parts.append("3. 结合时代背景补充合理的感官信息（如当时的流行歌曲、食物味道等）")
        parts.append("4. 避免套路化感官描写（如'茶香四溢'等），追求具体独特")

        return "\n".join(parts)

    def _build_era_context_enhanced(self, chapter: ChapterOutline) -> str:
        if not chapter.time_period_start:
            return """=== 时代背景 ===
【提示】本章未明确指定时间段，请根据上下文推断或保持模糊处理。
避免编造具体的历史事件年份。
"""
        
        year = chapter.time_period_start[:4] if len(chapter.time_period_start) >= 4 else ""
        
        # 详细的年代背景
        era_hints = {
            "1949": ("新中国成立", "土地改革，抗美援朝，社会主义改造"),
            "1950": ("建国初期", "百废待兴，三大改造，集体化运动"),
            "1960": ("困难时期", "三年自然灾害，物质极度匮乏，票证制度"),
            "1966": ("文革时期", "社会动荡，上山下乡，个人命运起伏"),
            "1976": ("转折之年", "文革结束，拨乱反正，恢复高考"),
            "1978": ("改革开放", "十一届三中全会，家庭联产承包，思想解放"),
            "1980": ("改革初期", "特区设立，价格双轨制，万元户涌现"),
            "1984": ("城市改革", "沿海开放城市，国企改革，商品经济"),
            "1992": ("南巡讲话", "市场经济确立，下海热潮，开发浦东"),
            "1997": ("香港回归", "国企改革攻坚，亚洲金融危机，互联网起步"),
            "2001": ("入世元年", "WTO，申奥成功，房地产起步"),
            "2008": ("金融危机", "奥运会，四万亿，房价飙升"),
            "2010": ("移动互联网", "微博兴起，创业热潮，O2O"),
        }
        
        era_desc = ""
        era_keywords = ""
        for decade, (era_name, keywords) in era_hints.items():
            if year.startswith(decade[:3]):
                era_desc = era_name
                era_keywords = keywords
                break
        
        if not era_desc:
            era_desc = f"{year}年代"
            era_keywords = "请参考历史资料"
        
        return f"""=== 时代背景（写作时必须融入）===
时间: {year}年代
时代特征: {era_desc}
关键元素: {era_keywords}

【写作要求】
1. 必须结合当时的社会大环境描述传主的经历
2. 可提及当时的物价水平、工资标准、流行文化等具体细节
3. 将个人命运与时代变迁相结合
4. 禁止使用"中国社会发展的重要时期"等空泛表述
"""


class ContentGenerationEngine:
    """内容扩写引擎"""
    
    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.max_retries = 3
    
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
        
        # 调用LLM生成
        logger.info(f"正在生成内容: {context.get('section_title', '小节')}...")
        
        content = await self.llm.complete(
            messages,
            temperature=0.7,
            max_tokens=min(4000, target_words * 2)
        )
        
        # 后处理：清理和验证
        content = self._post_process_content(content)
        
        # 检测占位符和模板化内容
        placeholder_issues = self._detect_placeholders(content)
        if placeholder_issues:
            logger.warning(f"检测到占位符问题: {placeholder_issues}")
        
        actual_words = count_chinese_words(content)
        
        # 如果字数不足，进行扩写
        if actual_words < target_words * 0.8:
            logger.warning(f"字数不足 ({actual_words}/{target_words})，进行扩写...")
            content = await self._expand_content(
                content, context, target_words - actual_words
            )
            content = self._post_process_content(content)
            actual_words = count_chinese_words(content)
        
        return GeneratedSection(
            id=generate_id("section_content"),
            chapter_id="",
            title=context.get("section_title", "小节"),
            content=content,
            word_count=actual_words,
            generation_time=datetime.now()
        )
    
    async def generate_section_stream(
        self,
        context: Dict[str, str],
        style: WritingStyle
    ) -> AsyncIterator[str]:
        """流式生成内容"""
        system_prompt = self._build_system_prompt(style)
        user_prompt = self._build_generation_prompt(context, 0)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        async for chunk in self.llm.complete_stream(messages, temperature=0.7):
            yield chunk
    
    def _build_system_prompt(self, style: WritingStyle) -> str:
        """构建系统提示词"""
        import yaml
        from pathlib import Path
        
        style_file = Path(__file__).parent.parent.parent / "config" / "styles.yaml"
        with open(style_file, "r", encoding="utf-8") as f:
            styles_config = yaml.safe_load(f)
        
        style_config = styles_config.get("styles", {}).get(style.value, {})
        base_prompt = style_config.get("system_prompt", "")
        
        # 添加通用要求和强制约束，包含Few-shot示例
        full_prompt = f"""{base_prompt}

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

=== 正反面示例（必须遵循） ===

【反面示例 ❌ 必须避免】

❌ 例1 - 套路化意象：
"晨光透过窗户洒进来，尘埃在光柱中飞舞。陈国伟端起茶杯，凉茶早已凉透，苦涩中带着回甘。"
→ 问题："尘埃光柱"、"凉茶苦甘"是AI常见套路，无具体来源

❌ 例2 - 情感标签：
"得知这个消息，陈国伟陷入了沉思，心中充满了复杂的情绪。"
→ 问题："陷入沉思"、"充满情绪"是空洞标签，没有具体言行支撑

❌ 例3 - 空泛表述：
"那是一个风云变幻、波澜壮阔的特殊年代，对陈国伟的人生产生了深刻影响。"
→ 问题：没有具体时间地点，全是空泛形容词

❌ 例4 - 占位符：
"（此处需要补充更多细节，待后续完善）"
→ 问题：明显的AI占位符，必须删除

【正面示例 ✅ 应该模仿】

✅ 例1 - 基于具体素材：
"1982年春天，陈国伟背着布包走进藤编厂（来源：素材3）。厂门口有棵老榕树，车间里是成捆的藤条和化学药剂的味道。门卫老头翻着登记簿说：'你就是那个手很巧的小子。'"
→ 优点：具体时间、地点、对话、气味细节，都有来源支撑

✅ 例2 - 有言行支撑的心理：
"陈国伟站在厂门口，深吸一口气——那是藤条被水泡发后的清香，混合着汗味和机油味（来源：素材3）。他没有立即进去，而是在榕树下站了几分钟，把布包的带子攥紧了又松开。"
→ 优点：通过动作（吸气、攥带子）表现紧张，而非直接说"他很紧张"

✅ 例3 - 时代背景具体化：
"1984年，陈国伟第一次离开佛山去广州。那时候广州火车站很乱，他在流花湖那边倒腾服装，从石狮进货。没有营业执照，看到戴红袖箍的来抓，卷起包袱就跑（来源：素材2）。"
→ 优点：具体年份、地点、行为细节，而非"改革开放初期"的空泛描述

=== 输出前自检清单 ===
生成内容后，请逐条检查，全部通过后再输出：
□ 没有出现"待补充"、"此处需要展开"等占位符
□ 没有出现"尘埃光柱"、"凉茶苦甘"、"命运齿轮"等套路化意象
□ 没有出现"陷入沉思"、"百感交集"等无支撑的情感标签
□ 每个场景描写都能在素材中找到对应或依据
□ 包含至少1个具体时间（年份）和1个具体地点
□ 包含至少1个具体数字（金额、数量、年龄等）或1段人物对话
□ 章节结尾自然收束，没有"更大的挑战在等待"等虚假悬念

=== 写作要求 ===
1. 基于提供的素材进行扩写，不要脱离素材随意发挥
2. 注重细节描写：场景、动作、对话、心理活动
3. 适当运用感官描写（视觉、听觉、嗅觉等）
4. 时间线和人物关系必须与上下文保持一致
5. 情感表达要符合指定的情感基调
6. 使用中文写作，语言流畅自然
7. 章节结尾应自然收束，不要强行制造悬念
"""
        return full_prompt
    
    def _build_generation_prompt(self, context: Dict[str, str], target_words: int) -> str:
        """构建生成提示词"""
        word_hint = f"\n=== 字数要求 ===\n本节目标字数：{target_words}字\n" if target_words else ""
        
        return f"""请根据以下信息撰写传记内容：

{context.get('global', '')}

{context.get('section', '')}

{context.get('materials', '')}

{context.get('continuity', '')}

{context.get('era', '')}

{context.get('sensory', '')}
{word_hint}

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
    """迭代生成层主类"""
    
    def __init__(self, llm: LLMClient, vector_store: VectorStore):
        self.llm = llm
        self.context_assembler = ContextAssembler(llm, vector_store)
        self.generation_engine = ContentGenerationEngine(llm)
    
    async def generate_chapter(
        self,
        chapter_outline: ChapterOutline,
        book_outline: BookOutline,
        global_state: Dict,
        progress_callback: Optional[callable] = None
    ) -> GeneratedChapter:
        """
        生成完整章节
        """
        logger.info(f"开始生成第{chapter_outline.order}章: {chapter_outline.title}")
        
        sections = []
        previous_summary = None
        
        for i, section_outline in enumerate(chapter_outline.sections):
            # 更新进度
            if progress_callback:
                progress_callback(f"第{chapter_outline.order}章 - {section_outline.title}")
            
            # 组装上下文
            context = await self.context_assembler.assemble_context(
                section=section_outline,
                chapter=chapter_outline,
                outline=book_outline,
                global_state=global_state,
                previous_section_summary=previous_summary
            )

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

            # 生成内容
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
        
        return GeneratedChapter(
            id=generate_id("chapter_gen", chapter_outline.order),
            outline=chapter_outline,
            sections=sections,
            transition_paragraph=transition
        )
    
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
