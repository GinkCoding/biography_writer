"""
改进版传记生成流水线 V2

工程化改进：
1. 状态机管理流程
2. 严格的输入验证
3. 自动元数据清理
4. 事件追踪防重复
5. 自动修订闭环
6. 最终文档自动构建
7. 完善的错误处理和日志
"""
import asyncio
import json
from pathlib import Path
from typing import Optional
from loguru import logger

from .storage.project import Project, ProjectStorage
from .llm.client import LLMClient
from .core.state_machine import (
    GenerationStateMachine, GenerationContext, GenerationState
)
from .core.validators import (
    OutlineValidator, ContentValidator, ReviewReportParser, EventTracker
)
from .core.auto_reviser import AutoReviser, ContentCleaner, FinalDocumentBuilder


class BiographyPipelineV2:
    """改进版传记生成流水线"""
    
    def __init__(self, project: Project, storage: ProjectStorage):
        self.project = project
        self.storage = storage
        self.llm = LLMClient()
        
        # 初始化验证器
        self.outline_validator = OutlineValidator()
        self.content_validator = ContentValidator()
        
        # 初始化事件追踪
        self.event_tracker = EventTracker(storage.base_dir)
        
        # 初始化自动修订器
        self.auto_reviser = AutoReviser(self.llm, storage.base_dir)
        
        # 初始化状态机
        self.context = GenerationContext(
            project_id=project.project_id,
            current_chapter=project.current_chapter,
            total_chapters=project.total_chapters,
            completed_chapters=project.completed_chapters.copy()
        )
        self.state_machine = GenerationStateMachine(
            self.context, storage.base_dir
        )
        
        # 注册状态处理器
        self._register_handlers()
        
        # 加载素材
        self.material = self._load_material()
        self.outline = None
        self.characters = None
    
    def _register_handlers(self):
        """注册状态处理器"""
        self.state_machine.register_handler(
            GenerationState.INIT, self._handle_init)
        self.state_machine.register_handler(
            GenerationState.OUTLINE_GENERATING, self._handle_outline_generating)
        self.state_machine.register_handler(
            GenerationState.OUTLINE_REVIEWING, self._handle_outline_reviewing)
        self.state_machine.register_handler(
            GenerationState.CHAPTER_GENERATING, self._handle_chapter_generating)
        self.state_machine.register_handler(
            GenerationState.CHAPTER_REVIEWING, self._handle_chapter_reviewing)
        self.state_machine.register_handler(
            GenerationState.FINAL_REVIEWING, self._handle_final_reviewing)
        self.state_machine.register_handler(
            GenerationState.FINAL_REVISION, self._handle_final_revision)
    
    def _load_material(self) -> str:
        """加载采访素材"""
        material_path = Path(self.project.material_path)
        if material_path.exists():
            return material_path.read_text(encoding='utf-8')
        return ""
    
    async def run(self):
        """运行流水线"""
        logger.info(f"🚀 启动传记生成流水线 V2: {self.project.project_id}")
        
        try:
            # 从INIT开始
            if self.context.current_state == GenerationState.INIT:
                self.state_machine.transition(
                    GenerationState.OUTLINE_GENERATING, "开始生成大纲")
            
            # 运行状态机
            await self.state_machine.run()
            
            # 完成
            if self.context.current_state == GenerationState.COMPLETED:
                logger.info("✅ 传记生成完成！")
                self._generate_final_report()
            
        except Exception as e:
            logger.error(f"❌ 生成失败: {e}")
            raise
    
    async def _handle_init(self, ctx: GenerationContext) -> dict:
        """处理INIT状态"""
        return {"success": True, "next_state": GenerationState.OUTLINE_GENERATING}
    
    async def _handle_outline_generating(self, ctx: GenerationContext) -> dict:
        """处理大纲生成"""
        logger.info("📝 生成大纲...")
        
        # 生成大纲（调用原有逻辑，但添加验证）
        outline = await self._generate_outline()
        
        # 严格验证
        is_valid, errors = self.outline_validator.validate(outline)
        
        if not is_valid:
            for error in errors:
                logger.error(f"  大纲验证失败: {error.field} - {error.message}")
            return {"success": False, "reason": "大纲验证失败"}
        
        self.outline = outline
        
        # 保存大纲
        outline_file = self.storage.base_dir / "outline.json"
        outline_file.write_text(json.dumps(outline, ensure_ascii=False, indent=2))
        
        # 注册事件
        for ch in outline.get("chapters", []):
            for event in ch.get("key_events", []):
                self.event_tracker.register_event(
                    event, ch["order"], f"第{ch['order']}章关键事件"
                )
        
        logger.info(f"  ✅ 大纲生成完成: {len(outline.get('chapters', []))}章")
        
        return {"success": True, "next_state": GenerationState.CHAPTER_GENERATING}
    
    async def _handle_outline_reviewing(self, ctx: GenerationContext) -> dict:
        """处理大纲审核"""
        # 简化：直接通过
        return {"success": True, "next_state": GenerationState.CHAPTER_GENERATING}
    
    async def _handle_chapter_generating(self, ctx: GenerationContext) -> dict:
        """处理章节生成"""
        current = ctx.current_chapter + 1
        
        if current > ctx.total_chapters:
            # 所有章节完成
            return {"success": True, "next_state": GenerationState.FINAL_REVIEWING}
        
        logger.info(f"\n📖 第 {current}/{ctx.total_chapters} 章")
        
        # 获取章节大纲
        chapter_outline = self._get_chapter_outline(current)
        if not chapter_outline:
            logger.error(f"  第{current}章大纲不存在")
            return {"success": False, "reason": "章节大纲缺失"}
        
        # 检查是否有已写事件
        written_events = self.event_tracker.get_written_events()
        
        # 生成章节
        content = await self._generate_chapter(current, chapter_outline, written_events)
        
        # 清理元数据
        content = ContentCleaner.clean(content)
        
        # 验证内容
        is_valid, errors = self.content_validator.validate(content)
        if not is_valid:
            for error in errors:
                logger.warning(f"  内容问题: {error.field} - {error.message}")
            # 尝试自动修复
            content = self._auto_fix_content(content, errors)
        
        # 保存
        self.storage.save_chapter(current, content)
        
        # 生成结构化摘要
        await self._generate_and_save_summary(current, content, chapter_outline)
        
        # 标记事件已写入
        for event in chapter_outline.get("key_events", []):
            self.event_tracker.mark_event_written(event, current)
        
        # 更新进度
        ctx.current_chapter = current
        ctx.completed_chapters.append(current)
        self.project.current_chapter = current
        self.project.completed_chapters = ctx.completed_chapters
        self.storage.save_project(self.project)
        
        logger.info(f"  ✅ 第{current}章完成")
        
        # 继续下一章
        return {"success": True, "next_state": GenerationState.CHAPTER_GENERATING}
    
    async def _handle_chapter_reviewing(self, ctx: GenerationContext) -> dict:
        """处理章节审核"""
        # 简化：生成时已完成基础审核
        return {"success": True, "next_state": GenerationState.CHAPTER_GENERATING}
    
    async def _handle_final_reviewing(self, ctx: GenerationContext) -> dict:
        """处理终审"""
        logger.info("\n📚 全文终审...")
        
        # 执行全文审核
        review_report = await self._perform_final_review()
        
        # 保存报告
        review_file = self.storage.base_dir / "final" / "whole_book_review.txt"
        review_file.parent.mkdir(exist_ok=True)
        review_file.write_text(review_report, encoding='utf-8')
        
        # 解析报告
        parser = ReviewReportParser()
        parsed = parser.parse(review_report)
        
        if parsed.get("passed"):
            logger.info("  ✅ 终审通过")
            return {"success": True, "next_state": GenerationState.FINAL_APPROVED}
        
        # 有严重问题，需要修订
        serious_count = len(parsed.get("serious_issues", []))
        if serious_count > 0:
            logger.warning(f"  ⚠️ 发现{serious_count}个严重问题，需要修订")
            return {"success": True, "next_state": GenerationState.FINAL_REVISION}
        
        logger.info("  ✅ 无严重问题，终审通过")
        return {"success": True, "next_state": GenerationState.FINAL_APPROVED}
    
    async def _handle_final_revision(self, ctx: GenerationContext) -> dict:
        """处理最终修订"""
        logger.info("\n🔧 根据终审意见自动修订...")
        
        # 加载终审报告
        review_file = self.storage.base_dir / "final" / "whole_book_review.txt"
        if not review_file.exists():
            logger.warning("  终审报告不存在，跳过修订")
            return {"success": True, "next_state": GenerationState.FINAL_APPROVED}
        
        review_report = review_file.read_text(encoding='utf-8')
        
        # 先修复元数据（常见且简单）
        fixed_count = await self.auto_reviser.fix_metadata()
        if fixed_count > 0:
            logger.info(f"  清理了{fixed_count}章的元数据")
        
        # 根据报告进行内容修订
        results = await self.auto_reviser.revise_by_final_review(review_report)
        
        logger.info(f"  修订完成: {results['fixed_issues']}/{results['total_issues']}个问题已修复")
        
        # 修订后重新审核
        return {"success": True, "next_state": GenerationState.FINAL_REVIEWING}
    
    async def _generate_outline(self) -> dict:
        """生成大纲（简化版）"""
        from . import prompts
        
        style_prompt = prompts.get_style_prompt("ordinary")
        
        prompt = prompts.OUTLINE_PROMPT.format(
            subject_info="陈国伟，1965年生，广东佛山人",
            material=self.material[:50000],
            style_prompt=style_prompt,
            total_chapters=self.project.total_chapters,
            words_per_chapter=4000,
            start_year=1965,
            end_year=2025
        )
        
        _, response = await self.llm.complete_with_thinking([
            {"role": "user", "content": prompt}
        ])
        
        # 提取JSON
        import re
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            return json.loads(json_match.group())
        
        raise ValueError("无法解析大纲")
    
    async def _generate_chapter(self, order: int, outline: dict, written_events: list) -> str:
        """生成章节（带防重复）"""
        from . import prompts
        
        # 构建提示词（带事件去重）
        written_events_text = "\n".join([f"- {e}" for e in written_events]) if written_events else "无"
        
        prompt = f"""请生成传记第{order}章。

【章节大纲】
{json.dumps(outline, ensure_ascii=False, indent=2)}

【⚠️ 禁止重复事件】
以下事件已在之前章节写过，本章绝对禁止再写：
{written_events_text}

【采访素材】
{self.material[:20000]}

要求：
1. 严格遵循大纲
2. 绝对禁止写已在上文列出的事件
3. 只输出正文，不要任何元数据"""
        
        _, content = await self.llm.complete_with_thinking(
            [{"role": "user", "content": prompt}],
            max_tokens=8000
        )
        
        return content
    
    async def _generate_and_save_summary(self, chapter: int, content: str, outline: dict):
        """生成并保存结构化摘要"""
        prompt = f"""请总结以下章节的关键信息（不超过500字）：

标题: {outline.get('title', '')}
内容: {content[:6000]}

格式：
1. 核心事件: ...
2. 关键人物: ...
3. 时间节点: ...
4. 地点: ...
5. 情节进展: ..."""
        
        try:
            summary = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000
            )
            self.storage.save_chapter_summary(chapter, summary)
        except Exception as e:
            logger.warning(f"  摘要生成失败: {e}")
            # 降级处理：使用截取
            fallback = content[:500] + "..."
            self.storage.save_chapter_summary(chapter, fallback)
    
    async def _perform_final_review(self) -> str:
        """执行全文审核"""
        # 收集所有章节
        chapters = []
        for i in self.context.completed_chapters:
            content = self.storage.load_chapter(i)
            if content:
                chapters.append(f"=== 第{i}章 ===\n{content[:2000]}...")
        
        full_book = "\n\n".join(chapters)
        
        prompt = f"""请对以下传记进行终审：

【采访素材】
{self.material[:10000]}

【传记全文】
{full_book[:15000]}...

请检查：
1. 跨章节事件重复
2. 与素材不符的内容
3. 元数据残留
4. 人物设定一致性

输出格式：
===终审结果===
passed: true/false
总体评价: ...

===严重问题===
1. ...

===建议优化===
1. ..."""
        
        return await self.llm.complete(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4000
        )
    
    def _get_chapter_outline(self, order: int) -> Optional[dict]:
        """获取章节大纲"""
        if not self.outline:
            outline_file = self.storage.base_dir / "outline.json"
            if outline_file.exists():
                self.outline = json.loads(outline_file.read_text())
        
        for ch in self.outline.get("chapters", []):
            if ch.get("order") == order:
                return ch
        return None
    
    def _auto_fix_content(self, content: str, errors: list) -> str:
        """自动修复内容问题"""
        fixed = content
        
        for error in errors:
            if error.field == "metadata":
                fixed = self.content_validator.clean_metadata(fixed)
            elif error.field == "placeholder":
                # 删除占位符段落
                fixed = re.sub(r'.*待补充.*\n?', '', fixed)
        
        return fixed
    
    def _generate_final_report(self):
        """生成最终报告"""
        # 构建最终文档
        builder = FinalDocumentBuilder(self.storage.base_dir)
        final_path = builder.build()
        
        logger.info(f"\n📄 最终文档: {final_path}")
        
        # 生成统计报告
        report = f"""
# 传记生成报告

## 基本信息
- 项目ID: {self.project.project_id}
- 总章节: {len(self.context.completed_chapters)}
- 当前章节: {self.context.current_chapter}
- 最终状态: {self.context.current_state.value}

## 生成统计
- 已完成章节: {len(self.context.completed_chapters)}
- 失败章节: {len(self.context.failed_chapters)}
- 错误次数: {self.context.error_count}

## 文件位置
- 章节文件: chapters/chapter_XX.md
- 最终文档: {final_path.name}
- 审核记录: final/whole_book_review.txt
"""
        
        report_file = self.storage.base_dir / "final" / "生成报告.md"
        report_file.write_text(report, encoding='utf-8')


# 便捷函数
def create_pipeline_v2(project_id: str) -> BiographyPipelineV2:
    """创建Pipeline V2实例"""
    storage = ProjectStorage(project_id)
    project = storage.load_project()
    
    if not project:
        raise ValueError(f"项目不存在: {project_id}")
    
    return BiographyPipelineV2(project, storage)
