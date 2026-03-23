"""传记生成流水线 - 使用 BiographyEngine 的封装"""
import asyncio
from pathlib import Path
from typing import Optional, Callable
from loguru import logger

from src.engine import BiographyEngine
from src.models import WritingStyle
from src.storage.project import Project, ProjectStorage


class BiographyPipeline:
    """传记生成流水线 - 基于 BiographyEngine"""
    
    def __init__(self, project: Project, storage: ProjectStorage):
        self.project = project
        self.storage = storage
        self.engine = BiographyEngine()
    
    async def run(self, progress_callback: Optional[Callable[[str], None]] = None):
        """运行流水线"""
        # 使用 engine 初始化项目
        interview_file = Path(self.project.material_path)
        if not interview_file.exists():
            raise ValueError(f"采访文件不存在: {interview_file}")
        
        logger.info(f"🚀 启动传记生成: {self.project.name}")
        
        # 从采访文件初始化
        book_id = await self.engine.initialize_from_interview(
            interview_file=interview_file,
            subject_hint=self.project.name.replace('传', ''),
            style=WritingStyle.LITERARY,
            target_words=100000,
            progress_callback=progress_callback
        )
        
        # 更新项目状态
        self.project.current_phase = "outline"
        self.project.total_chapters = self.engine.outline.total_chapters if self.engine.outline else 25
        self.storage.save_project(self.project)
        
        # 生成传记
        book = await self.engine.generate_book(progress_callback=progress_callback)
        
        # 保存结果
        await self.engine.save_book(book)
        
        # 更新项目状态
        self.project.current_phase = "completed"
        self.project.current_chapter = len(book.chapters)
        self.storage.save_project(self.project)
        
        logger.info(f"✅ 传记生成完成: {book.outline.title}")
        logger.info(f"   总章节: {len(book.chapters)}")
        logger.info(f"   总字数: {book.total_word_count}")
        
        return book
