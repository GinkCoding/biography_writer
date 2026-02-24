#!/usr/bin/env python3
"""
测试硅基流动Embedding配置
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.embedding import SiliconFlowEmbedding, EmbeddingManager
from loguru import logger


def test_siliconflow_direct():
    """直接测试硅基流动API"""
    print("=" * 60)
    print("测试硅基流动Embedding API")
    print("=" * 60)
    
    # 尝试从环境变量或配置文件读取API密钥
    import os
    api_key = os.getenv("SILICONFLOW_API_KEY")
    
    if not api_key:
        # 尝试从配置文件读取
        from src.config import settings
        api_key = settings.embedding.siliconflow_api_key
    
    if not api_key:
        print("❌ 错误: 未找到硅基流动API密钥")
        print("请设置以下任一方式:")
        print("1. 环境变量: export SILICONFLOW_API_KEY='your-api-key'")
        print("2. 配置文件: config/settings.yaml 中设置 siliconflow_api_key")
        print("\n获取API密钥: https://siliconflow.cn")
        return False
    
    print(f"✓ API密钥已配置: {api_key[:8]}...{api_key[-4:]}")
    
    # 测试Embedding生成
    try:
        embedder = SiliconFlowEmbedding(
            api_key=api_key,
            model="BAAI/bge-large-zh-v1.5"
        )
        
        # 测试文本
        test_texts = [
            "陈国伟1965年出生在佛山陈家村",
            "1982年春天去藤编厂工作",
            "创业初期睡在原料袋子上刮毛边"
        ]
        
        print(f"\n测试文本: {test_texts}")
        print("正在生成向量嵌入...")
        
        embeddings = embedder.encode(test_texts)
        
        print(f"✓ 成功生成向量!")
        print(f"  - 向量维度: {embeddings.shape[1]}")
        print(f"  - 向量数量: {embeddings.shape[0]}")
        
        # 测试相似度计算
        print("\n测试语义相似度:")
        query = "创业初期艰辛"
        query_emb = embedder.encode_query(query)
        
        similarities = embedder.compute_similarity(query_emb, embeddings)
        
        for i, (text, sim) in enumerate(zip(test_texts, similarities)):
            print(f"  [{i+1}] 相似度 {sim:.4f}: {text[:30]}...")
        
        # 验证相似度合理性
        # "创业初期睡在原料袋子上刮毛边" 应该与 "创业初期艰辛" 相似度最高
        max_idx = similarities.argmax()
        if "创业" in test_texts[max_idx] or "刮毛边" in test_texts[max_idx]:
            print("\n✓ 语义相似度测试通过! 相关文本被正确召回")
        else:
            print("\n⚠ 语义相似度可能不够精确")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_embedding_manager():
    """测试Embedding管理器"""
    print("\n" + "=" * 60)
    print("测试Embedding管理器")
    print("=" * 60)
    
    try:
        from src.config import settings
        config = settings.embedding.get_embedding_manager_config()
        
        print(f"配置优先级: {config.get('priority', [])}")
        print(f"硅基流动模型: {config.get('siliconflow_model', 'N/A')}")
        
        manager = EmbeddingManager(config)
        
        # 测试编码
        test_text = "1965年，陈国伟出生在佛山"
        embedding = manager.encode([test_text])
        
        print(f"✓ Embedding管理器工作正常")
        print(f"  - 使用提供器: {type(manager.provider).__name__}")
        print(f"  - 向量维度: {embedding.shape[1]}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def list_siliconflow_models():
    """列出支持的模型"""
    print("\n" + "=" * 60)
    print("支持的硅基流动Embedding模型")
    print("=" * 60)
    
    models = SiliconFlowEmbedding.list_supported_models()
    for i, model in enumerate(models, 1):
        print(f"{i}. {model}")
    
    print("\n推荐使用:")
    print("- BAAI/bge-large-zh-v1.5: 中文效果优秀，性价比高")
    print("- BAAI/bge-m3: 支持长文本（8192token），多语言")


def main():
    """主函数"""
    print("\n🔧 硅基流动Embedding配置测试工具\n")
    
    # 列出模型
    list_siliconflow_models()
    
    # 测试直接API调用
    success1 = test_siliconflow_direct()
    
    # 测试Embedding管理器
    success2 = test_embedding_manager()
    
    # 总结
    print("\n" + "=" * 60)
    print("测试结果总结")
    print("=" * 60)
    
    if success1 and success2:
        print("✅ 所有测试通过！硅基流动Embedding配置正确")
        print("\n您现在可以:")
        print("1. 运行完整测试: pytest tests/ -v")
        print("2. 开始生成传记: python -m biography init")
        return 0
    else:
        print("❌ 部分测试失败，请检查配置")
        print("\n排查建议:")
        if not success1:
            print("1. 检查API密钥是否正确")
            print("2. 检查网络连接是否能访问 https://api.siliconflow.cn")
            print("3. 检查账户是否有足够的Token额度")
        if not success2:
            print("4. 检查 config/settings.yaml 配置格式")
        return 1


if __name__ == "__main__":
    sys.exit(main())
