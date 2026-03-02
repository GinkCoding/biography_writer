#!/usr/bin/env python3
"""
Apple Silicon (arm64) 环境安装脚本
在 arm64 模式下运行: /usr/bin/arch -arm64 python3 setup_arm64.py
"""

import subprocess
import sys

def run_pip_install(package):
    """运行 pip 安装命令"""
    print(f"安装 {package}...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", package],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print(f"  ✓ {package} 安装成功")
        return True
    else:
        print(f"  ✗ {package} 安装失败: {result.stderr}")
        return False

def main():
    print("=" * 60)
    print("Apple Silicon (arm64) 环境配置")
    print("=" * 60)

    # 检查架构
    import platform
    if platform.machine() != 'arm64':
        print("\n⚠️ 警告: 当前不是 arm64 模式!")
        print("请使用以下命令运行此脚本:")
        print("  /usr/bin/arch -arm64 python3 setup_arm64.py")
        print("")
        response = input("是否继续? (y/N): ")
        if response.lower() != 'y':
            return

    print(f"\nPython: {sys.version}")
    print(f"架构: {platform.machine()}")
    print("")

    # 核心依赖列表
    dependencies = [
        "torch",
        "sentence-transformers>=2.2.0",
        "zhipuai>=2.0.0",
        "openai>=1.0.0",
        "pydantic>=2.0.0",
        "chromadb>=0.4.0",
        "jieba>=0.42.1",
        "langchain>=0.1.0",
        "langchain-openai>=0.0.5",
        "typer>=0.9.0",
        "rich>=13.0.0",
        "loguru>=0.7.0",
        "ebooklib>=0.18",
        "python-dotenv>=1.0.0",
        "aiohttp>=3.9.0",
        "networkx>=3.0",
        "jsonschema>=4.17.0",
        "rank-bm25>=0.2.2",
        "pytest>=8.0.0",
        "pytest-asyncio>=0.23.0",
        "jinja2>=3.1.0",
    ]

    print(f"将安装 {len(dependencies)} 个依赖包...\n")

    failed = []
    for dep in dependencies:
        if not run_pip_install(dep):
            failed.append(dep)

    print("\n" + "=" * 60)
    if not failed:
        print("✓ 所有依赖安装成功!")
        print("\n现在可以运行项目:")
        print("  /usr/bin/arch -arm64 python3 run_biography.py")
    else:
        print(f"✗ {len(failed)} 个包安装失败:")
        for f in failed:
            print(f"  - {f}")
    print("=" * 60)

if __name__ == "__main__":
    main()
