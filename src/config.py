"""配置管理模块"""
import os
from pathlib import Path
from typing import Optional, Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_project_path(name: str) -> str:
    return str(PROJECT_ROOT / name)


class ModelConfig(BaseSettings):
    """模型配置"""
    provider: str = "openai"
    api_key: str = ""
    base_url: Optional[str] = None
    model: str = "gpt-4-turbo-preview"
    max_tokens: int = 4000
    temperature: float = 0.7
    top_p: float = 0.9
    request_timeout_seconds: int = 300
    heartbeat_interval_seconds: int = 10


class GenerationConfig(BaseSettings):
    """生成参数配置"""
    target_length: int = 100000
    total_chapters: int = 25
    sections_per_chapter: int = 4
    words_per_section: int = 1000
    style: str = "literary"


class PathConfig(BaseSettings):
    """路径配置"""
    interview_dir: str = Field(
        default_factory=lambda: os.getenv("BIOGRAPHY_INTERVIEW_DIR", _default_project_path("interviews"))
    )
    output_dir: str = Field(
        default_factory=lambda: os.getenv("BIOGRAPHY_OUTPUT_DIR", _default_project_path("output"))
    )
    vector_db_dir: str = Field(
        default_factory=lambda: os.getenv("BIOGRAPHY_VECTOR_DB_DIR", _default_project_path(".vector_db"))
    )
    cache_dir: str = Field(
        default_factory=lambda: os.getenv("BIOGRAPHY_CACHE_DIR", _default_project_path(".cache"))
    )


class EmbeddingConfig(BaseSettings):
    """Embedding配置"""
    # 提供器优先级列表
    priority: list = Field(default_factory=lambda: [
        "siliconflow", "sentence_transformer", "openai", "tfidf"
    ])
    
    # 硅基流动配置
    siliconflow_api_key: str = ""
    siliconflow_model: str = "BAAI/bge-m3"
    
    # SentenceTransformer配置
    model: str = "BAAI/bge-m3"
    
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


class HybridRetrievalConfig(BaseSettings):
    """混合检索配置"""
    # RRF融合参数
    rrf_k: int = 60  # RRF公式中的k值，通常取60

    # 检索Top-K配置
    vector_top_k: int = 20  # 向量检索召回数量
    bm25_top_k: int = 20    # BM25检索召回数量
    rerank_top_n: int = 10  # 最终返回结果数量

    # BM25参数
    bm25_k1: float = 1.5    # BM25词频饱和度参数
    bm25_b: float = 0.75    # BM25文档长度归一化参数

    # Rerank配置
    enable_rerank: bool = True  # 是否启用重排序
    rerank_provider: str = "siliconflow"  # 重排序提供器: siliconflow/local
    rerank_model: str = "BAAI/bge-reranker-v2-m3"  # 重排序模型

    # 父子索引配置
    enable_parent_child: bool = True  # 是否启用父子索引
    parent_chunk_size: int = 2000     # 父块（摘要）大小
    child_chunk_size: int = 1000      # 子块（场景）大小


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
    hybrid_retrieval: HybridRetrievalConfig = Field(default_factory=HybridRetrievalConfig)
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
