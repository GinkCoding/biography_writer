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


class EmbeddingConfig(BaseSettings):
    """Embedding配置"""
    # 提供器优先级列表
    priority: list = Field(default_factory=lambda: [
        "siliconflow", "sentence_transformer", "openai", "tfidf"
    ])
    
    # 硅基流动配置
    siliconflow_api_key: str = ""
    siliconflow_model: str = "BAAI/bge-large-zh-v1.5"
    
    # SentenceTransformer配置
    model: str = "BAAI/bge-small-zh-v1.5"
    
    # OpenAI配置
    openai_api_key: str = ""
    openai_model: str = "text-embedding-3-small"
    
    def get_embedding_manager_config(self) -> dict:
        """获取Embedding管理器配置"""
        return {
            "priority": self.priority,
            "siliconflow_api_key": self.siliconflow_api_key or os.getenv("SILICONFLOW_API_KEY"),
            "siliconflow_model": self.siliconflow_model,
            "model": self.model,
            "openai_api_key": self.openai_api_key or os.getenv("OPENAI_API_KEY"),
            "openai_model": self.openai_model,
        }


class VectorDBConfig(BaseSettings):
    """向量数据库配置"""
    collection_name: str = "biography_materials"
    chunk_size: int = 1000
    chunk_overlap: int = 200


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
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
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