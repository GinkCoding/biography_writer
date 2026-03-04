"""
LLM-Driven 传记生成核心模块
"""
from .pipeline import BiographyPipeline, PipelineState
from .models import (
    BookOutline, ChapterOutline, SectionOutline,
    MaterialEvaluation, ReviewReport, GenerationConfig
)
from .agents import (
    FactChecker, ContinuityChecker, RepetitionChecker, LiteraryChecker,
    QualitySelector
)

__all__ = [
    'BiographyPipeline', 'PipelineState',
    'BookOutline', 'ChapterOutline', 'SectionOutline',
    'MaterialEvaluation', 'ReviewReport', 'GenerationConfig',
    'FactChecker', 'ContinuityChecker', 'RepetitionChecker', 'LiteraryChecker',
    'QualitySelector'
]
