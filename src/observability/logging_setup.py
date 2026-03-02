"""Centralized logging setup."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from src.config import settings

_LOGGING_CONFIGURED = False


def setup_application_logging(level: str = "INFO", log_file: Optional[Path] = None) -> None:
    """Configure loguru for both console and rotating file output.

    Safe to call multiple times.
    """
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    output_dir = Path(settings.paths.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_log = log_file or (output_dir / "biography_generation.log")

    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
        enqueue=True,
    )
    logger.add(
        str(target_log),
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
        rotation="20 MB",
        retention="14 days",
        encoding="utf-8",
        enqueue=True,
    )
    _LOGGING_CONFIGURED = True
    logger.info(f"Logging initialized. Log file: {target_log}")

