"""
LLM-Driven 传记生成流水线 - 命令行入口

用法:
    python -m src.llm_pipeline_cli --material interviews/采访.txt --output output/ --target-words 100000
"""
import argparse
import asyncio
import sys
from pathlib import Path

from loguru import logger

from src.core.pipeline import BiographyPipeline
from src.core.models import GenerationConfig


def setup_logging():
    """配置日志"""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO"
    )
    logger.add(
        "logs/llm_pipeline_{time}.log",
        rotation="100 MB",
        level="DEBUG"
    )


async def main():
    parser = argparse.ArgumentParser(description="LLM-Driven 传记生成")
    parser.add_argument(
        "--material",
        "-m",
        type=Path,
        required=True,
        help="采访素材文件路径"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="输出目录"
    )
    parser.add_argument(
        "--target-words",
        "-t",
        type=int,
        default=100000,
        help="目标字数（默认：100000）"
    )
    parser.add_argument(
        "--max-revision-rounds",
        "-r",
        type=int,
        default=5,
        help="单章节最大修订轮次（默认：5）"
    )

    args = parser.parse_args()

    # 验证输入
    if not args.material.exists():
        logger.error(f"素材文件不存在: {args.material}")
        sys.exit(1)

    # 创建输出目录
    args.output.mkdir(parents=True, exist_ok=True)

    setup_logging()
    logger.info("=" * 60)
    logger.info("LLM-Driven 传记生成流水线")
    logger.info("=" * 60)
    logger.info(f"素材: {args.material}")
    logger.info(f"输出: {args.output}")
    logger.info(f"目标字数: {args.target_words}")
    logger.info("=" * 60)

    # 创建配置
    config = GenerationConfig(
        max_revision_rounds=args.max_revision_rounds
    )

    # 运行流水线
    pipeline = BiographyPipeline(config)

    try:
        final_path = await pipeline.run(
            material_path=args.material,
            output_dir=args.output,
            target_words=args.target_words
        )

        logger.info("=" * 60)
        logger.info(f"✅ 传记生成完成: {final_path}")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ 生成失败: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
