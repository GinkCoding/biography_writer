#!/bin/bash
# 带向量维度测试的启动脚本

set -e

echo "=========================================="
echo "启动前向量维度验证"
echo "=========================================="

# 运行测试
python3 tests/test_embedding_dimension.py
TEST_RESULT=$?

if [ $TEST_RESULT -ne 0 ]; then
    echo ""
    echo "❌ 向量维度测试失败！拒绝启动"
    echo "请检查配置后重试"
    exit 1
fi

echo ""
echo "=========================================="
echo "✅ 测试通过，启动传记生成"
echo "=========================================="

# 启动生成
python3 run_biography.py
