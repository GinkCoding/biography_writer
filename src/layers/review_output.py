"""第五层：审校与输出层 (Review & Output)"""
import json
import re
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


class ConsistencyChecker:
    """一致性校验Agent"""
    
    def __init__(self, llm: LLMClient, timeline: Timeline):
        self.llm = llm
        self.timeline = timeline
        self.subject_name = timeline.subject.name if timeline.subject else "传主"
    
    async def check_section(
        self,
        section: GeneratedSection,
        chapter_context: Dict
    ) -> FactCheckResult:
        """
        检查单节内容的一致性
        """
        violations = []
        
        # 1. 基础事实核查
        fact_violations = await self._check_facts(section)
        violations.extend(fact_violations)
        
        # 2. 时间线核查
        time_violations = await self._check_timeline(section, chapter_context)
        violations.extend(time_violations)
        
        # 3. 人物关系核查
        char_violations = await self._check_characters(section)
        violations.extend(char_violations)
        
        # 4. 逻辑一致性核查
        logic_violations = await self._check_logic(section)
        violations.extend(logic_violations)
        
        is_consistent = len(violations) == 0
        
        return FactCheckResult(
            section_id=section.id,
            is_consistent=is_consistent,
            violations=violations,
            suggestions=self._generate_suggestions(violations),
            confidence=1.0 - (len(violations) * 0.1)  # 简单的置信度计算
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
        prompt = f"""请检查以下内容是否与已知事实存在冲突：

=== 已知事实（来自原始采访）===
{chr(10).join(timeline_facts[:10])}

=== 待检查内容 ===
{content[:1000]}

=== 检查要求 ===
1. 如果内容提及了上述事实，检查描述是否一致
2. 识别是否存在"无中生有"的人物或事件
3. 检查时间顺序是否合理

请以JSON格式返回发现的问题（如果没有问题返回空列表）：
[
  {{
    "type": "事实冲突/无中生有/时间错误",
    "description": "具体问题描述",
    "location": "问题出现在文中的位置"
  }}
]
"""
        
        messages = [
            {"role": "system", "content": "你是一位严格的事实核查编辑。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await self.llm.complete(messages, temperature=0.2)
            issues = self._parse_json_array(response)
            
            for issue in issues:
                violations.append({
                    "type": issue.get("type", "未知"),
                    "description": issue.get("description", ""),
                    "severity": "high" if "冲突" in str(issue.get("type", "")) else "medium"
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
        # 这里可以接入NER模型
        potential_characters = set(re.findall(r'[\u4e00-\u9fff]{2,4}(?=说|道|问|答|笑|哭)', content))
        
        # 检查是否有新人物首次出现但没有介绍
        new_characters = potential_characters - known_characters - {self.subject_name}
        
        if new_characters:
            # 过滤掉常见词汇
            common_words = {"之后", "当时", "后来", "然后", "因为", "所以", "虽然", "但是", "不过", "可是"}
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
        # 1. 检查是否有矛盾的时间描述
        if "前一天" in content and "后一天" in content:
            # 检查上下文是否合理
            pass
        
        # 2. 检查年龄计算
        age_pattern = r'(\d{2})岁'
        ages = re.findall(age_pattern, content)
        if len(ages) > 1:
            # 同一段落内年龄不应该跳变太大
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
            if "事实" in vtype:
                suggestions.append("请对照原始采访材料核实该事实")
            elif "时间" in vtype:
                suggestions.append("请检查时间描述是否准确，必要时添加'大约'、'可能'等限定词")
            elif "人物" in vtype:
                suggestions.append("新人物首次出现时请补充介绍说明")
            elif "逻辑" in vtype:
                suggestions.append("请理顺时间顺序，确保叙事逻辑清晰")
        
        return list(set(suggestions))  # 去重
    
    def _parse_json_array(self, text: str) -> List:
        """解析JSON数组"""
        try:
            # 尝试直接解析
            return json.loads(text)
        except:
            pass
        
        # 提取方括号内容
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
        self.writer_agent = ContentGenerationEngine(llm)
        self.checker_agent = ConsistencyChecker(llm, timeline)
    
    async def review_and_refine(
        self,
        section: GeneratedSection,
        chapter_context: Dict,
        max_iterations: int = 2
    ) -> GeneratedSection:
        """
        审查并优化内容
        
        Args:
            section: 待审查的内容
            chapter_context: 章节上下文
            max_iterations: 最大迭代次数
        """
        current_section = section
        
        for iteration in range(max_iterations):
            # 1. 检查当前内容
            check_result = await self.checker_agent.check_section(
                current_section, chapter_context
            )
            
            if check_result.is_consistent:
                logger.info(f"内容通过审查，无违规项")
                current_section.facts_verified = True
                break
            
            logger.warning(f"发现 {len(check_result.violations)} 个违规项，进行优化...")
            
            # 2. 如果有严重违规，重写
            high_severity = [v for v in check_result.violations if v.get("severity") == "high"]
            
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
        violation_text = "\n".join([
            f"- [{v.get('type')}] {v.get('description')}"
            for v in violations
        ])
        
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
"""
        
        messages = [
            {"role": "system", "content": "你是一位资深编辑，擅长在不改变风格的前提下修正事实错误。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            rewritten = await self.llm.complete(messages, temperature=0.6)
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
        
        Returns:
            格式到文件路径的映射
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
            # 移除Markdown标记
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
        logger.info(f"审查完成: {verified_count}/{len(chapter.sections)} 节通过事实核查")
        
        return chapter
    
    async def finalize_book(
        self,
        book: BiographyBook
    ) -> Dict[str, Path]:
        """最终输出书籍"""
        book.completed_at = datetime.now()
        
        saved_files = await self.formatter.save_book(book)
        
        return saved_files