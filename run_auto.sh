#!/bin/bash
# 自动运行脚本 - 使用 Kimi 和 SiliconFlow Embedding

cd /Users/guoquan/work/Kimi/biography_writer

# 设置 LLM 环境变量 (Kimi)
export LLM_PROVIDER="kimi"
export KIMI_API_KEY="sk-kimi-hRwTqAfwEJs3H1guXidMeQJY0nOifyfb00wtjYKg1rj8O8JF0QgGf29uLUfq8QYz"
export KIMI_BASE_URL="https://api.moonshot.cn/v1"
export KIMI_MODEL="kimi-k2-5-long-context"

# 设置 Embedding 环境变量
export EMBEDDING_PROVIDER="siliconflow"
export SILICONFLOW_API_KEY="sk-mykvsbepjdgheppmqccubburghlbnhoqoxvgfdjzikkufxcn"
export SILICONFLOW_MODEL="Qwen/Qwen3-Embedding-8B"

# 强制使用 arm64 架构的 Python
PYTHON_CMD="/usr/bin/arch -arm64 /usr/local/bin/python3"

echo "=== 使用 Apple Silicon (arm64) 模式运行 ==="
echo "Python 架构: $($PYTHON_CMD -c 'import platform; print(platform.machine())')"
echo "LLM Provider: $LLM_PROVIDER ($KIMI_MODEL)"
echo "Embedding Provider: $EMBEDDING_PROVIDER (Qwen/Qwen3-Embedding-8B)"
echo ""

# 运行主程序
$PYTHON_CMD run_biography.py
