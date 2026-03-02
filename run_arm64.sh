#!/bin/bash
# Apple Silicon (arm64) 模式运行脚本
# 使用方法: ./run_arm64.sh [命令]
# 示例: ./run_arm64.sh python run_biography.py

# 强制使用 arm64 架构的 Python
PYTHON_CMD="/usr/bin/arch -arm64 /usr/local/bin/python3"

echo "=== 使用 Apple Silicon (arm64) 模式运行 ==="
echo "Python 架构: $($PYTHON_CMD -c 'import platform; print(platform.machine())')"
echo ""

if [ $# -eq 0 ]; then
    # 默认运行主程序
    $PYTHON_CMD run_biography.py
else
    # 运行传入的命令
    $PYTHON_CMD "$@"
fi
