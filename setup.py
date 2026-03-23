#!/usr/bin/env python3
"""
传记写作系统 - 安装配置脚本

功能：
1. 自动检测并安装依赖
2. 交互式配置向导
3. 验证配置有效性
"""
import sys
import subprocess
from pathlib import Path

def check_python_version():
    """检查Python版本"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print(f"❌ 需要Python 3.10+，当前版本: {version.major}.{version.minor}")
        return False
    print(f"✓ Python版本: {version.major}.{version.minor}.{version.micro}")
    return True

def install_dependencies():
    """安装依赖"""
    print("\n📦 安装依赖...")
    requirements = Path(__file__).parent / "requirements.txt"
    if not requirements.exists():
        print("❌ 未找到requirements.txt")
        return False

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )
        print("✓ 依赖安装完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 依赖安装失败: {e}")
        return False

def run_setup_wizard():
    """运行配置向导"""
    print("\n🔧 启动配置向导...")
    sys.path.insert(0, str(Path(__file__).parent))

    try:
        from src.setup_wizard import SetupWizard
        wizard = SetupWizard()
        return wizard.run()
    except Exception as e:
        print(f"❌ 配置向导失败: {e}")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print("📚 传记写作系统 - 安装配置")
    print("=" * 60)

    # 检查Python版本
    if not check_python_version():
        return 1

    # 询问是否安装依赖
    print("\n是否自动安装依赖？")
    choice = input("[Y/n]: ").strip().lower()
    if choice in ['', 'y', 'yes']:
        if not install_dependencies():
            return 1

    # 运行配置向导
    print("\n是否运行配置向导？")
    choice = input("[Y/n]: ").strip().lower()
    if choice in ['', 'y', 'yes']:
        if not run_setup_wizard():
            return 1

    print("\n" + "=" * 60)
    print("✅ 安装配置完成！")
    print("=" * 60)
    print("\n您现在可以先查看可用命令：")
    print("  python3 -m src --help")
    print("\n开始初始化项目：")
    print("  python3 -m src init")

    return 0

if __name__ == "__main__":
    sys.exit(main())
