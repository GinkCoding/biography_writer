"""传记生成引擎主控"""
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Callable
from datetime import datetime
from loguru import logger

from src.config import settings
from src.llm_client import LLMClient
from src.models import (
    WritingStyle, BookOutline, BiographyBook, 
    GeneratedChapter, GlobalState
)
from src.layers.data_ingestion import DataIngestionLayer, VectorStore
from src.layers.knowledge_memory import KnowledgeMemoryLayer, GlobalStateManager
from src.layers.planning import PlanningOrchestrationLayer
from src.layers.generation import IterativeGenerationLayer
from src.layers.review_output import ReviewOutputLayer
from src.utils import generate_id, save_json


class BiographyEngine:
    """传记生成引擎"""
    
    def __init__(self):
        self.llm = LLMClient()
        self.vector_store = VectorStore()
        
        # 初始化各层
        self.data_layer = DataIngestionLayer()
        self.knowledge_layer = KnowledgeMemoryLayer(self.llm)
        self.planning_layer = PlanningOrchestrationLayer(self.llm)
        self.generation_layer = IterativeGenerationLayer(self.llm, self.vector_store)
        
        self.book_id: Optional[str] = None
        self.outline: Optional[BookOutline] = None
        self.timeline = None
        self.state_manager: Optional[GlobalStateManager] = None
        self.review_layer: Optional[ReviewOutputLayer] = None
        
        # 确保目录存在
        settings.ensure_dirs()
    
    async def initialize_from_interview(
        self,
        interview_file: Path,
        subject_hint: Optional[str] = None,
        style: WritingStyle = WritingStyle.LITERARY,
        target_words: Optional[int] = None
    ) -> str:
        """
        从采访文件初始化项目
        
        Returns:
            book_id: 项目ID
        """
        logger.info(f"开始初始化项目，采访文件: {interview_file}")
        
        # 生成项目ID
        self.book_id = generate_id(
            interview_file.stem,
            datetime.now().isoformat()
        )
        
        # 1. 数据接入与解析
        logger.info("【第1层】数据接入与解析...")
        materials = await self.data_layer.process_interview(
            file_path=interview_file,
            subject_hint=subject_hint
        )
        
        if not materials:
            raise ValueError("未能从采访文件中提取有效素材")
        
        logger.info(f"素材处理完成，共 {len(materials)} 个文本块")
        
        # 2. 知识构建与全局记忆
        logger.info("【第2层】知识构建与全局记忆...")
        self.timeline, knowledge_graph, self.state_manager = \
            await self.knowledge_layer.build_knowledge_base(
                materials=materials,
                book_id=self.book_id,
                subject_hint=subject_hint
            )
        
        # 保存知识图谱
        kg_path = Path(settings.paths.cache_dir) / f"{self.book_id}_kg.json"
        save_json(knowledge_graph.to_dict(), kg_path)
        
        # 3. 规划与编排
        logger.info("【第3层】规划与编排...")
        self.outline = await self.planning_layer.create_book_plan(
            timeline=self.timeline,
            style=style,
            target_words=target_words
        )
        
        # 保存大纲
        outline_path = Path(settings.paths.cache_dir) / f"{self.book_id}_outline.json"
        save_json(self.outline.model_dump(), outline_path)
        
        logger.info(f"大纲生成完成: {self.outline.title}")
        logger.info(f"  - 章节数: {self.outline.total_chapters}")
        logger.info(f"  - 目标字数: {self.outline.target_total_words}")
        
        # 初始化审校层
        self.review_layer = ReviewOutputLayer(
            llm=self.llm,
            timeline=self.timeline,
            output_dir=Path(settings.paths.output_dir)
        )
        
        return self.book_id
    
    async def generate_book(
        self,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> BiographyBook:
        """
        生成完整传记
        """
        if not self.outline or not self.state_manager:
            raise RuntimeError("请先调用 initialize_from_interview 初始化项目")
        
        logger.info(f"开始生成传记: {self.outline.title}")
        
        chapters = []
        total_chapters = len(self.outline.chapters)
        
        for i, chapter_outline in enumerate(self.outline.chapters):
            chapter_num = i + 1
            
            # 更新状态
            self.state_manager.update_for_chapter(
                chapter_idx=chapter_num,
                section_idx=0
            )
            self.state_manager.save()
            
            # 获取生成上下文
            global_state = self.state_manager.get_context_for_generation()
            
            # 4. 迭代生成
            logger.info(f"【第4层】生成第{chapter_num}/{total_chapters}章...")
            
            def on_progress(msg: str):
                if progress_callback:
                    progress_callback(f"[{chapter_num}/{total_chapters}] {msg}")
            
            chapter = await self.generation_layer.generate_chapter(
                chapter_outline=chapter_outline,
                book_outline=self.outline,
                global_state=global_state,
                progress_callback=on_progress
            )
            
            # 5. 审校
            logger.info(f"【第5层】审查第{chapter_num}章...")
            chapter_context = {
                "time_period_start": chapter_outline.time_period_start,
                "time_period_end": chapter_outline.time_period_end,
            }
            chapter = await self.review_layer.review_chapter(chapter, chapter_context)
            
            chapters.append(chapter)
            
            # 更新状态
            chapter_summary = f"{chapter_outline.title}({chapter.word_count}字)"
            self.state_manager.add_chapter_summary(chapter_summary)
            self.state_manager.save()
            
            logger.info(f"第{chapter_num}章完成，字数: {chapter.word_count}")
        
        # 构建完整书籍
        book = BiographyBook(
            id=self.book_id,
            outline=self.outline,
            chapters=chapters
        )
        
        logger.info(f"传记生成完成！")
        logger.info(f"  - 总章节: {len(chapters)}")
        logger.info(f"  - 总字数: {book.total_word_count}")
        
        return book
    
    async def generate_single_chapter(
        self,
        chapter_number: int
    ) -> GeneratedChapter:
        """
        生成单章（用于测试或增量更新）
        """
        if not self.outline:
            raise RuntimeError("项目未初始化")
        
        chapter_outline = None
        for c in self.outline.chapters:
            if c.order == chapter_number:
                chapter_outline = c
                break
        
        if not chapter_outline:
            raise ValueError(f"未找到第{chapter_number}章")
        
        # 更新状态
        self.state_manager.update_for_chapter(chapter_idx=chapter_number)
        global_state = self.state_manager.get_context_for_generation()
        
        # 生成
        chapter = await self.generation_layer.generate_chapter(
            chapter_outline=chapter_outline,
            book_outline=self.outline,
            global_state=global_state
        )
        
        # 审校
        chapter_context = {
            "time_period_start": chapter_outline.time_period_start,
            "time_period_end": chapter_outline.time_period_end,
        }
        chapter = await self.review_layer.review_chapter(chapter, chapter_context)
        
        return chapter
    
    async def save_book(self, book: BiographyBook) -> Dict[str, Path]:
        """保存生成的书籍"""
        return await self.review_layer.finalize_book(book)
    
    def load_project(self, book_id: str) -> bool:
        """
        加载已有项目（断点续传）
        """
        self.book_id = book_id
        
        # 加载大纲
        outline_path = Path(settings.paths.cache_dir) / f"{book_id}_outline.json"
        if not outline_path.exists():
            return False
        
        import json
        with open(outline_path, "r", encoding="utf-8") as f:
            self.outline = BookOutline(**json.load(f))
        
        # 加载状态
        self.state_manager = GlobalStateManager(
            book_id=book_id,
            cache_dir=Path(settings.paths.cache_dir)
        )
        self.state_manager.load()
        
        # 重建审校层（需要重新加载timeline，简化处理）
        # 实际应用中应该从缓存加载
        
        return True
    
    def get_progress(self) -> Dict:
        """获取当前进度"""
        if not self.state_manager:
            return {"status": "未初始化"}
        
        state = self.state_manager.state
        total_chapters = self.outline.total_chapters if self.outline else 0
        
        return {
            "book_id": self.book_id,
            "current_chapter": state.current_chapter_idx,
            "total_chapters": total_chapters,
            "progress_percent": (state.current_chapter_idx / total_chapters * 100) if total_chapters else 0,
            "status": "进行中" if state.current_chapter_idx < total_chapters else "已完成"
        }