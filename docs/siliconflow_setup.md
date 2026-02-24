# 硅基流动 (SiliconFlow) Embedding 配置指南

## 简介

硅基流动 (SiliconFlow) 是国内优秀的 AI 模型服务平台，提供稳定的中文 Embedding 模型 API。相比本地模型，使用硅基流动的优势：

- ✅ **无需下载模型文件**（本地 BGE-large 模型约 1GB）
- ✅ **国内访问稳定快速**
- ✅ **中文 Embedding 效果优秀**
- ✅ **新用户有免费额度**

## 快速配置

### 1. 获取 API 密钥

1. 访问 [硅基流动官网](https://siliconflow.cn)
2. 注册账号并登录
3. 进入"API 密钥"页面，创建新密钥
4. 复制密钥备用

### 2. 配置方式（三选一）

#### 方式一：环境变量（推荐）

```bash
export SILICONFLOW_API_KEY="your-api-key-here"
```

添加到 `~/.bashrc` 或 `~/.zshrc` 使其永久生效：

```bash
echo 'export SILICONFLOW_API_KEY="your-api-key-here"' >> ~/.bashrc
source ~/.bashrc
```

#### 方式二：配置文件

编辑 `config/settings.yaml`：

```yaml
embedding:
  priority:
    - siliconflow      # 优先使用硅基流动
    - sentence_transformer
  
  siliconflow_api_key: "your-api-key-here"
  siliconflow_model: "BAAI/bge-large-zh-v1.5"
```

#### 方式三：.env 文件

编辑 `.env` 文件（从 `.env.example` 复制）：

```bash
cp .env.example .env
# 编辑 .env 文件，填入密钥
```

```
SILICONFLOW_API_KEY=your-api-key-here
```

### 3. 验证配置

运行测试脚本：

```bash
python scripts/test_siliconflow.py
```

成功输出示例：

```
✓ API密钥已配置: sk-xxxxxxxx...xxxx
测试文本: ['陈国伟1965年出生在佛山陈家村', ...]
正在生成向量嵌入...
✓ 成功生成向量!
  - 向量维度: 1024
  - 向量数量: 3

测试语义相似度:
  [1] 相似度 0.3125: 陈国伟1965年出生在佛山陈家村...
  [2] 相似度 0.2891: 1982年春天去藤编厂工作...
  [3] 相似度 0.8923: 创业初期睡在原料袋子上刮毛边...

✓ 语义相似度测试通过! 相关文本被正确召回
```

## 模型选择

硅基流动支持多种 Embedding 模型：

| 模型 | 维度 | 最大长度 | 特点 | 推荐场景 |
|------|------|----------|------|----------|
| `BAAI/bge-large-zh-v1.5` | 1024 | 512 | 中文效果优秀 | **默认推荐** |
| `BAAI/bge-m3` | 1024 | 8192 | 支持长文本 | 长采访记录 |
| `netease-youdao/bce-embedding-base_v1` | 768 | 512 | 有道开源 | 通用场景 |

修改模型：

```yaml
# config/settings.yaml
embedding:
  siliconflow_model: "BAAI/bge-m3"  # 改为支持长文本的模型
```

## 优先级配置

你可以调整 Embedding 提供器的优先级：

```yaml
# config/settings.yaml
embedding:
  # 优先级顺序：按顺序尝试，第一个成功的会被使用
  priority:
    - siliconflow           # 优先使用硅基流动
    # - sentence_transformer  # 本地模型（无需API）
    # - openai               # OpenAI（备选）
    # - tfidf                # 关键词匹配（最后的备选）
```

## 常见问题

### Q: 如何查看剩余额度？

A: 登录 [硅基流动控制台](https://siliconflow.cn) 查看 API 使用统计。

### Q: 免费额度用完了怎么办？

A: 系统会自动回退到本地 SentenceTransformer 模型（无需额外费用，但需要下载模型文件）。

### Q: 网络连接失败？

A: 检查以下几点：
1. API 密钥是否正确（以 `sk-` 开头）
2. 网络是否能访问 `https://api.siliconflow.cn`
3. 防火墙/代理设置

### Q: 向量维度是多少？

A: 不同模型维度不同：
- BGE-large: 1024 维
- BCE: 768 维

### Q: 可以本地和云端混合使用吗？

A: 不可以同时混合，但可以配置优先级。如果云端失败，会自动回退到本地模型。

## 费用参考

硅基流动 Embedding 模型价格（2024年）：

- BAAI/bge-large-zh-v1.5: 约 ¥0.5 / 100万 tokens
- 一本 10 万字传记约需 100-200万 tokens
- **预估成本: ¥0.5 - ¥1.0**

新用户通常有 ¥10-¥50 的免费额度，足够生成多本传记。

## 技术支持

- 硅基流动官网: https://siliconflow.cn
- 文档中心: https://docs.siliconflow.cn
