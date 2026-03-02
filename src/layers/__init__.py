"""五层架构模块

- DataIngestionLayer: 数据摄入层
- KnowledgeMemoryLayer: 知识记忆层
- PlanningLayer: 规划层
- GenerationLayer: 生成层
- ReviewOutputLayer: 审校输出层
"""
from .data_ingestion import DataIngestionLayer
from .knowledge_memory import KnowledgeMemoryLayer
from .planning import PlanningOrchestrationLayer as PlanningLayer
from .generation import ContentGenerationEngine, IterativeGenerationLayer
from .review_output import ReviewOutputLayer, DualAgentReviewer, OutputFormatter

__all__ = [
    'DataIngestionLayer',
    'KnowledgeMemoryLayer',
    'PlanningLayer',
    'ContextAssembler',
    'ContentGenerationEngine',
    'IterativeGenerationLayer',
    'ReviewOutputLayer',
    'DualAgentReviewer',
    'OutputFormatter',
]
