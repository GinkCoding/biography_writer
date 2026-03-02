#!/bin/bash
# 自动运行脚本 - 使用 GLM-5 和 SiliconFlow Embedding

cd /Users/guoquan/work/Kimi/biography_writer

# 设置 LLM 环境变量 (使用 OpenAI 兼容模式调用 GLM-5)
export LLM_PROVIDER="openai"
export OPENAI_API_KEY="sk-sp-53b88c7e79b6406794174741b2b72729"
export OPENAI_BASE_URL="https://coding.dashscope.aliyuncs.com/v1"
export OPENAI_MODEL="GLM-5"

# 设置 Embedding 环境变量
export EMBEDDING_PROVIDER="siliconflow"
export SILICONFLOW_API_KEY="sk-mykvsbepjdgheppmqccubburghlbnhoqoxvgfdjzikkufxcn"
export SILICONFLOW_MODEL="Qwen/Qwen3-Embedding-8B"

# 强制使用 arm64 架构的 Python
PYTHON_CMD="/usr/bin/arch -arm64 /usr/local/bin/python3"

echo "=== 使用 Apple Silicon (arm64) 模式运行 ==="
echo "Python 架构: $($PYTHON_CMD -c 'import platform; print(platform.machine())')"
echo "LLM Provider: $LLM_PROVIDER (GLM-5)"
echo "Embedding Provider: $EMBEDDING_PROVIDER (Qwen/Qwen3-Embedding-8B)"
echo ""

# 运行主程序
$PYTHON_CMD run_biography.py
