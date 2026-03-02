#!/usr/bin/env python3
"""
传记写作项目完整执行脚本
处理陈国伟采访文件，生成完整传记
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '.')

from src.engine import BiographyEngine
from src.models import WritingStyle
from loguru import logger
from src.observability.logging_setup import setup_application_logging

# 配置日志
setup_application_logging()


async def main():
    """主执行流程"""
    start_time = datetime.now()

    logger.info("=" * 60)
    logger.info("🚀 传记写作项目启动")
    logger.info("=" * 60)

    # 初始化引擎
    logger.info("📦 初始化传记生成引擎...")
    engine = BiographyEngine()

    # 采访文件路径
    interview_file = Path('interviews/采访 mock.txt')

    if not interview_file.exists():
        logger.error(f"❌ 采访文件不存在: {interview_file}")
        return

    logger.info(f"📄 采访文件: {interview_file}")
    logger.info(f"📊 文件大小: {interview_file.stat().st_size} 字节")

    try:
        # ========== 第1阶段：项目初始化 ==========
        logger.info("\n" + "=" * 60)
        logger.info("【阶段1/5】项目初始化")
        logger.info("=" * 60)

        book_id = await engine.initialize_from_interview(
            interview_file=interview_file,
            subject_hint='陈国伟',
            style=WritingStyle.LITERARY,
            target_words=10000  # 1万字测试
        )

        logger.info(f"✅ 项目初始化完成")
        logger.info(f"   项目ID: {book_id}")
        logger.info(f"   书名: {engine.outline.title}")
        logger.info(f"   章节数: {engine.outline.total_chapters}")
        logger.info(f"   目标字数: {engine.outline.target_total_words}")

        # ========== 第2阶段：生成传记 ==========
        logger.info("\n" + "=" * 60)
        logger.info("【阶段2/5】生成传记内容")
        logger.info("=" * 60)

        chapter_count = 0
        total_word_count = 0

        def on_progress(msg: str):
            nonlocal chapter_count, total_word_count
            logger.info(f"  📖 {msg}")

        book = await engine.generate_book(progress_callback=on_progress)

        # ========== 第3阶段：输出统计 ==========
        logger.info("\n" + "=" * 60)
        logger.info("【阶段3/5】生成统计报告")
        logger.info("=" * 60)

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        logger.info(f"✅ 传记生成完成!")
        logger.info(f"   书名: {book.outline.title}")
        logger.info(f"   总字数: {book.total_word_count}")
        logger.info(f"   总章节: {len(book.chapters)}")
        logger.info(f"   耗时: {duration:.1f}秒 ({duration/60:.1f}分钟)")

        # 章节详情
        logger.info("\n📚 章节详情:")
        for i, chapter in enumerate(book.chapters, 1):
            logger.info(f"   第{i}章: {chapter.title} - {chapter.word_count}字")

        # ========== 第4阶段：健康报告 ==========
        logger.info("\n" + "=" * 60)
        logger.info("【阶段4/5】生成健康报告")
        logger.info("=" * 60)

        try:
            report = engine.get_health_report()
            if report:
                logger.info(f"📊 健康评分: {report.health_score:.1f}/100")
                logger.info(f"📈 性能指标:")
                logger.info(f"   平均生成速度: {report.performance.get('avg_generation_speed', 0):.1f} 字/秒")
                logger.info(f"   API调用次数: {report.api_stats.get('total_calls', 0)}")
                logger.info(f"   Token使用量: {report.api_stats.get('total_tokens', 0)}")
        except Exception as e:
            logger.warning(f"生成健康报告失败: {e}")

        # ========== 第5阶段：导出文件 ==========
        logger.info("\n" + "=" * 60)
        logger.info("【阶段5/5】导出传记文件")
        logger.info("=" * 60)

        output_dir = Path('output') / book_id
        logger.info(f"📁 输出目录: {output_dir}")

        # 列出输出文件
        if output_dir.exists():
            files = list(output_dir.iterdir())
            logger.info(f"   生成文件数: {len(files)}")
            for f in files:
                size = f.stat().st_size
                logger.info(f"   - {f.name} ({size} 字节)")

        logger.info("\n" + "=" * 60)
        logger.info("🎉 传记写作项目执行完成!")
        logger.info("=" * 60)

        return book

    except Exception as e:
        logger.error(f"❌ 执行失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    asyncio.run(main())
