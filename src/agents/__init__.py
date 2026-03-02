"""双Agent架构模块

提供Context Agent（创作任务书工程师）和Data Agent（数据链工程师）的实现。
"""

from .context_assembler import ContextAgent, ContextContract
from .data_extractor import DataAgent, ExtractionResult

__all__ = [
    "ContextAgent",
    "ContextContract",
    "DataAgent",
    "ExtractionResult",
]