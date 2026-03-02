"""
向量嵌入模块
支持多种Embedding方案，按优先级回退
"""
import numpy as np
from typing import List, Optional
from pathlib import Path
import pickle
import hashlib
from loguru import logger


class EmbeddingProvider:
    """Embedding提供器基类"""
    
    def encode(self, texts: List[str]) -> np.ndarray:
        """将文本编码为向量"""
        raise NotImplementedError
    
    def encode_query(self, text: str) -> np.ndarray:
        """编码查询文本"""
        return self.encode([text])[0]


class SentenceTransformerEmbedding(EmbeddingProvider):
    """基于SentenceTransformer的Embedding（首选）"""
    
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self.model_name = model_name
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """加载模型"""
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"正在加载Embedding模型: {self.model_name}")
            self.model = SentenceTransformer(self.model_name, device='cpu')
            logger.info("Embedding模型加载完成")
        except ImportError:
            logger.error("sentence-transformers未安装，请运行: pip install sentence-transformers")
            raise
        except Exception as e:
            logger.error(f"加载Embedding模型失败: {e}")
            raise
    
    def encode(self, texts: List[str]) -> np.ndarray:
        """编码文本"""
        if self.model is None:
            raise RuntimeError("模型未加载")
        
        # 清理文本
        cleaned_texts = [self._clean_text(t) for t in texts]
        
        # 编码
        embeddings = self.model.encode(
            cleaned_texts,
            normalize_embeddings=True,  # 归一化，便于余弦相似度计算
            batch_size=32,
            show_progress_bar=False
        )
        return np.asarray(embeddings, dtype=np.float32)
    
    def encode_query(self, text: str) -> np.ndarray:
        """编码查询（添加指令前缀以获得更好效果）"""
        # BGE模型推荐为查询添加指令前缀
        query_text = f"为这个句子生成表示以用于检索相关文章：{text}"
        return self.encode([query_text])[0]
    
    def _clean_text(self, text: str) -> str:
        """清理文本"""
        # 去除多余空白
        text = " ".join(text.split())
        # 截断超长文本
        if len(text) > 2000:
            text = text[:2000]
        return text


class SiliconFlowEmbedding(EmbeddingProvider):
    """
    基于硅基流动(SiliconFlow) API的Embedding
    国内访问稳定，支持多种中文Embedding模型
    """
    
    # 硅基流动API地址
    BASE_URL = "https://api.siliconflow.cn/v1"
    
    # 推荐的Embedding模型
    RECOMMENDED_MODELS = [
        "BAAI/bge-m3",          # 通义千问 8B 参数，中文效果优秀
        "BAAI/bge-m3",                       # 多语言，支持8192长度
        "netease-youdao/bce-embedding-base_v1",  # 有道开源
        "Pro/BAAI/bge-m3",                   # 专业版
    ]
    
    def __init__(self, api_key: Optional[str] = None, model: str = "BAAI/bge-m3"):
        self.api_key = api_key
        self.model = model
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """初始化客户端"""
        try:
            import openai
            
            if not self.api_key:
                # 尝试从环境变量读取
                import os
                self.api_key = os.getenv("SILICONFLOW_API_KEY")
                if not self.api_key:
                    raise ValueError("未提供硅基流动API密钥，请设置SILICONFLOW_API_KEY环境变量或在配置中指定")
            
            self.client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.BASE_URL
            )
            logger.info(f"硅基流动Embedding客户端初始化成功，模型: {self.model}")
        except ImportError:
            logger.error("openai未安装，请运行: pip install openai")
            raise
    
    def encode(self, texts: List[str]) -> np.ndarray:
        """编码文本"""
        if self.client is None:
            raise RuntimeError("客户端未初始化")
        
        # 清理文本
        cleaned_texts = [self._clean_text(t) for t in texts]
        
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=cleaned_texts,
                encoding_format="float"
            )
            
            embeddings = np.array([item.embedding for item in response.data])

            # 归一化
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            embeddings = embeddings / norms

            return np.asarray(embeddings, dtype=np.float32)
            
        except Exception as e:
            logger.error(f"调用硅基流动API失败: {e}")
            raise
    
    def encode_query(self, text: str) -> np.ndarray:
        """编码查询（添加指令前缀以获得更好效果）"""
        # BGE模型推荐为查询添加指令前缀
        query_text = f"为这个句子生成表示以用于检索相关文章：{text}"
        return self.encode([query_text])[0]
    
    def _clean_text(self, text: str) -> str:
        """清理文本"""
        # 去除多余空白
        text = " ".join(text.split())
        # 截断到 400 字符（约 512 tokens 安全范围）
        if len(text) > 400:
            text = text[:400]
        return text
    
    @classmethod
    def list_supported_models(cls) -> List[str]:
        """列出支持的模型"""
        return cls.RECOMMENDED_MODELS


class OpenAIEmbedding(EmbeddingProvider):
    """基于OpenAI API的Embedding（备选）"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "text-embedding-3-small"):
        self.api_key = api_key
        self.model = model
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """初始化客户端"""
        try:
            import openai
            if self.api_key:
                self.client = openai.OpenAI(api_key=self.api_key)
            else:
                self.client = openai.OpenAI()  # 从环境变量读取
        except ImportError:
            logger.error("openai未安装，请运行: pip install openai")
            raise
    
    def encode(self, texts: List[str]) -> np.ndarray:
        """编码文本"""
        if self.client is None:
            raise RuntimeError("客户端未初始化")
        
        response = self.client.embeddings.create(
            model=self.model,
            input=texts
        )
        
        embeddings = np.array([item.embedding for item in response.data])
        
        # 归一化
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / norms
        
        return np.asarray(embeddings, dtype=np.float32)


class TFIDFEmbedding(EmbeddingProvider):
    """
    基于TF-IDF的Embedding（轻量级备选）
    不需要下载模型，但效果较差
    """
    
    def __init__(self, max_features: int = 1000):
        self.max_features = max_features
        self.vectorizer = None
        self.fitted = False
    
    def fit(self, texts: List[str]):
        """拟合向量化器"""
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            import jieba
            
            # 使用jieba分词
            def tokenize(text):
                return " ".join(jieba.cut(text))
            
            tokenized_texts = [tokenize(t) for t in texts]
            
            self.vectorizer = TfidfVectorizer(
                max_features=self.max_features,
                tokenizer=lambda x: x.split(),
                preprocessor=None,
                token_pattern=None
            )
            self.vectorizer.fit(tokenized_texts)
            self.fitted = True
            logger.info(f"TF-IDF向量化器拟合完成，词汇表大小: {len(self.vectorizer.vocabulary_)}")
        except ImportError as e:
            logger.error(f"缺少依赖: {e}")
            raise
    
    def encode(self, texts: List[str]) -> np.ndarray:
        """编码文本"""
        if not self.fitted:
            # 如果未拟合，先用输入文本拟合
            self.fit(texts)
        
        import jieba
        tokenized_texts = [" ".join(jieba.cut(t)) for t in texts]
        embeddings = self.vectorizer.transform(tokenized_texts).toarray()
        
        # 归一化
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1  # 避免除零
        embeddings = embeddings / norms
        
        return np.asarray(embeddings, dtype=np.float32)


class EmbeddingManager:
    """
    Embedding管理器 - 自动选择最佳可用方案

    优先级（可配置）:
    1. 硅基流动SiliconFlow（国内API，中文效果优秀）
    2. SentenceTransformer（本地运行，无需网络）
    3. OpenAI（国际API）
    4. TF-IDF（轻量级备选）
    """

    def __init__(self, config: Optional[dict] = None, auto_prompt: bool = True):
        """
        初始化Embedding管理器

        Args:
            config: 配置字典，None则自动获取
            auto_prompt: 配置缺失时是否自动提示用户输入
        """
        self.config = config or {}
        self.auto_prompt = auto_prompt
        self.provider: Optional[EmbeddingProvider] = None
        self._init_provider()
    
    def _init_provider(self):
        """初始化Embedding提供器（按优先级）"""

        # 获取配置的优先级列表
        priority = self.config.get('priority', ['siliconflow', 'sentence_transformer', 'openai', 'tfidf'])

        # 如果启用了自动提示，使用配置管理器获取配置
        if self.auto_prompt and not self.config:
            from src.config_manager import ConfigManager
            manager = ConfigManager()
            provider_name, provider_config = manager.check_embedding_config()
            self.config = provider_config
            # 设置优先级为选中的提供商
            priority = [provider_name]

        for provider_type in priority:
            try:
                if provider_type == 'siliconflow':
                    self._init_siliconflow()
                    logger.info(f"Embedding 模型：{self.provider.model if self.provider else 'N/A'}")
                    return
                elif provider_type == 'sentence_transformer':
                    self._init_sentence_transformer()
                    return
                elif provider_type == 'openai':
                    self._init_openai()
                    return
                elif provider_type == 'tfidf':
                    self._init_tfidf()
                    return
            except Exception as e:
                logger.warning(f"{provider_type}初始化失败: {e}")
                continue

        raise RuntimeError("没有可用的Embedding提供器，请检查配置和网络连接")
    
    def _init_siliconflow(self):
        """初始化硅基流动"""
        import os, dotenv
        from pathlib import Path
        env_file = Path(__file__).parent.parent / '.env'
        if env_file.exists():
            dotenv.load_dotenv(env_file)
            logger.info(f'已加载.env 文件：{env_file}')
        api_key = self.config.get('siliconflow_api_key') or os.getenv('SILICONFLOW_API_KEY')
        model = 'BAAI/bge-m3'  # 强制使用
        logger.info(f"DEBUG: config_keys={list(self.config.keys())}, config.model={self.config.get('model', 'N/A')}, config.siliconflow_model={self.config.get('siliconflow_model', 'N/A')}, env={os.getenv('SILICONFLOW_MODEL', 'N/A')}, final={model}")
        self.provider = SiliconFlowEmbedding(api_key, model)
        logger.info(f"✅ 使用硅基流动 Embedding: {model}")

    def _init_sentence_transformer(self):
        """初始化本地SentenceTransformer"""
        model_name = self.config.get('model', 'BAAI/bge-m3')
        self.provider = SentenceTransformerEmbedding(model_name)
        logger.info(f"✅ 使用SentenceTransformer Embedding: {model_name}")

    def _init_openai(self):
        """初始化OpenAI"""
        api_key = self.config.get('openai_api_key')
        model = self.config.get('openai_model', 'text-embedding-3-small')
        self.provider = OpenAIEmbedding(api_key, model)
        logger.info(f"✅ 使用OpenAI Embedding: {model}")
    
    def _init_tfidf(self):
        """初始化TF-IDF"""
        self.provider = TFIDFEmbedding()
        logger.info("✅ 使用TF-IDF Embedding（备选方案）")
    
    def encode(self, texts: List[str]) -> np.ndarray:
        """编码文本列表"""
        if self.provider is None:
            raise RuntimeError("Embedding提供器未初始化")
        return self.provider.encode(texts)
    
    def encode_query(self, text: str) -> np.ndarray:
        """编码查询"""
        if self.provider is None:
            raise RuntimeError("Embedding提供器未初始化")
        return self.provider.encode_query(text)
    
    def compute_similarity(self, query_embedding: np.ndarray, doc_embeddings: np.ndarray) -> np.ndarray:
        """
        计算查询与文档的相似度（余弦相似度）
        
        Args:
            query_embedding: 查询向量 [dim]
            doc_embeddings: 文档向量 [n_docs, dim]
        
        Returns:
            相似度分数 [n_docs]
        """
        # 向量已归一化，点积即余弦相似度
        return np.dot(doc_embeddings, query_embedding)


# 全局Embedding管理器实例
_embedding_manager: Optional[EmbeddingManager] = None


def get_embedding_manager(config: Optional[dict] = None) -> EmbeddingManager:
    """获取全局Embedding管理器（单例）"""
    global _embedding_manager
    if _embedding_manager is None:
        _embedding_manager = EmbeddingManager(config)
    return _embedding_manager


def reset_embedding_manager():
    """重置Embedding管理器（用于测试）"""
    global _embedding_manager
    _embedding_manager = None
