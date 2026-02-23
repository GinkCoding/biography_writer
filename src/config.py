"""配置管理模块"""
import os
from pathlib import Path
from typing import Optional, Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelConfig(BaseSettings):
    """模型配置"""
    provider: str = "openai"
    api_key: str = ""
    base_url: Optional[str] = None
    model: str = "gpt-4-turbo-preview"
    max_tokens: int = 4000
    temperature: float = 0.7
    top_p: float = 0.9


class GenerationConfig(BaseSettings):
    """生成参数配置"""
    target_length: int = 100000
    total_chapters: int = 25
    sections_per_chapter: int = 4
    words_per_section: int = 1000
    style: str = "literary"


class PathConfig(BaseSettings):
    """路径配置"""
    interview_dir: str = "/Users/guoquan/work/Kimi/biography_writer/interviews"
    output_dir: str = "/Users/guoquan/work/Kimi/biography_writer/output"
    vector_db_dir: str = "/Users/guoquan/work/Kimi/biography_writer/.vector_db"
    cache_dir: str = "/Users/guoquan/work/Kimi/biography_writer/.cache"


class VectorDBConfig(BaseSettings):
    """向量数据库配置"""
    collection_name: str = "biography_materials"
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    chunk_size: int = 500
    chunk_overlap: int = 100


class RetryConfig(BaseSettings):
    """重试配置"""
    max_attempts: int = 3
    backoff_factor: int = 2


class ConcurrencyConfig(BaseSettings):
    """并发配置"""
    max_workers: int = 3


class Settings(BaseSettings):
    """全局配置"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    model: ModelConfig = Field(default_factory=ModelConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    paths: PathConfig = Field(default_factory=PathConfig)
    vector_db: VectorDBConfig = Field(default_factory=VectorDBConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    
    def ensure_dirs(self):
        """确保所有目录存在"""
        Path(self.paths.interview_dir).mkdir(parents=True, exist_ok=True)
        Path(self.paths.output_dir).mkdir(parents=True, exist_ok=True)
        Path(self.paths.vector_db_dir).mkdir(parents=True, exist_ok=True)
        Path(self.paths.cache_dir).mkdir(parents=True, exist_ok=True)


# 全局配置实例
settings = Settings()