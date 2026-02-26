#!/usr/bin/env python3
"""
配置引导向导 - 交互式配置管理

功能：
1. 自动检测缺失的依赖并安装
2. 交互式询问服务配置（API密钥、模型选择等）
3. 验证配置有效性
4. 保存配置到 .env 文件
"""
import os
import sys
import subprocess
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

# 确保可以导入项目模块
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm, IntPrompt
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.markdown import Markdown
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from src.utils import save_json


console = Console() if RICH_AVAILABLE else None


class ServiceType(Enum):
    """服务类型"""
    LLM = "llm"
    EMBEDDING = "embedding"
    VECTOR_DB = "vector_db"


@dataclass
class ServiceConfig:
    """服务配置定义"""
    name: str
    type: ServiceType
    description: str
    required_packages: List[str] = field(default_factory=list)
    config_fields: List[Dict[str, Any]] = field(default_factory=list)
    env_prefix: str = ""
    doc_url: str = ""
    priority: int = 0


# 预定义的服务配置
SERVICES = {
    "kimi": ServiceConfig(
        name="Kimi (Moonshot)",
        type=ServiceType.LLM,
        description="月之暗面Kimi大模型 - 推荐，中文效果好",
        required_packages=["openai"],
        config_fields=[
            {"name": "api_key", "prompt": "请输入 Kimi API Key", "secret": True, "env": "KIMI_API_KEY"},
            {"name": "base_url", "prompt": "API Base URL", "default": "https://api.moonshot.cn/v1", "env": "KIMI_BASE_URL"},
            {"name": "model", "prompt": "模型名称", "default": "moonshot-v1-128k", "env": "KIMI_MODEL"},
        ],
        env_prefix="KIMI",
        doc_url="https://platform.moonshot.cn/",
        priority=1
    ),
    "openai": ServiceConfig(
        name="OpenAI",
        type=ServiceType.LLM,
        description="OpenAI GPT模型 - 国际通用",
        required_packages=["openai"],
        config_fields=[
            {"name": "api_key", "prompt": "请输入 OpenAI API Key", "secret": True, "env": "OPENAI_API_KEY"},
            {"name": "base_url", "prompt": "API Base URL (可选，留空使用默认)", "default": "", "env": "OPENAI_BASE_URL"},
            {"name": "model", "prompt": "模型名称", "default": "gpt-4-turbo-preview", "env": "OPENAI_MODEL"},
        ],
        env_prefix="OPENAI",
        doc_url="https://platform.openai.com/",
        priority=2
    ),
    "zhipuai": ServiceConfig(
        name="智谱AI (GLM)",
        type=ServiceType.LLM,
        description="智谱AI GLM模型 - 国内API",
        required_packages=["zhipuai"],
        config_fields=[
            {"name": "api_key", "prompt": "请输入 智谱AI API Key", "secret": True, "env": "ZHIPUAI_API_KEY"},
            {"name": "model", "prompt": "模型名称", "default": "glm-4", "env": "ZHIPUAI_MODEL"},
        ],
        env_prefix="ZHIPUAI",
        doc_url="https://open.bigmodel.cn/",
        priority=3
    ),
    "siliconflow": ServiceConfig(
        name="硅基流动 (SiliconFlow)",
        type=ServiceType.EMBEDDING,
        description="硅基流动Embedding API - 推荐，中文向量效果好",
        required_packages=["requests"],
        config_fields=[
            {"name": "api_key", "prompt": "请输入 SiliconFlow API Key", "secret": True, "env": "SILICONFLOW_API_KEY"},
            {"name": "model", "prompt": "Embedding模型", "default": "BAAI/bge-large-zh-v1.5", "env": "SILICONFLOW_MODEL"},
        ],
        env_prefix="SILICONFLOW",
        doc_url="https://siliconflow.cn/",
        priority=1
    ),
    "sentence_transformer": ServiceConfig(
        name="SentenceTransformer (本地)",
        type=ServiceType.EMBEDDING,
        description="本地运行Embedding模型 - 无需API，首次下载模型",
        required_packages=["sentence-transformers", "torch"],
        config_fields=[
            {"name": "model", "prompt": "模型名称", "default": "BAAI/bge-small-zh-v1.5", "env": "SENTENCE_TRANSFORMER_MODEL"},
        ],
        env_prefix="SENTENCE_TRANSFORMER",
        doc_url="https://www.sbert.net/",
        priority=2
    ),
    "openai_embedding": ServiceConfig(
        name="OpenAI Embedding",
        type=ServiceType.EMBEDDING,
        description="OpenAI Embedding API",
        required_packages=["openai"],
        config_fields=[
            {"name": "api_key", "prompt": "请输入 OpenAI API Key", "secret": True, "env": "OPENAI_API_KEY"},
            {"name": "model", "prompt": "模型名称", "default": "text-embedding-3-small", "env": "OPENAI_EMBEDDING_MODEL"},
        ],
        env_prefix="OPENAI",
        doc_url="https://platform.openai.com/",
        priority=3
    ),
}


class SetupWizard:
    """配置引导向导"""

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path(__file__).parent.parent
        self.env_file = self.project_root / ".env"
        self.config_file = self.project_root / "config" / "user_config.yaml"
        self.installed_packages: set = set()
        self.config: Dict[str, Any] = {}

    def _print(self, message: str, style: str = ""):
        """打印消息（兼容有无rich的情况）"""
        if RICH_AVAILABLE and console:
            if style:
                console.print(message, style=style)
            else:
                console.print(message)
        else:
            print(message)

    def _print_header(self, title: str):
        """打印标题"""
        if RICH_AVAILABLE and console:
            console.print(Panel(title, style="bold blue"))
        else:
            print(f"\n{'='*60}")
            print(f"  {title}")
            print(f"{'='*60}\n")

    def _print_success(self, message: str):
        """打印成功消息"""
        self._print(f"✓ {message}", style="green" if RICH_AVAILABLE else "")

    def _print_warning(self, message: str):
        """打印警告消息"""
        self._print(f"⚠ {message}", style="yellow" if RICH_AVAILABLE else "")

    def _print_error(self, message: str):
        """打印错误消息"""
        self._print(f"✗ {message}", style="red" if RICH_AVAILABLE else "")

    def _input(self, prompt: str, default: str = "", secret: bool = False) -> str:
        """获取用户输入"""
        if RICH_AVAILABLE and console:
            if secret:
                import getpass
                return getpass.getpass(f"{prompt}: ") or default
            else:
                return Prompt.ask(prompt, default=default) if default else Prompt.ask(prompt)
        else:
            if default:
                full_prompt = f"{prompt} [{default}]: "
            else:
                full_prompt = f"{prompt}: "
            result = input(full_prompt).strip()
            return result if result else default

    def _confirm(self, prompt: str, default: bool = True) -> bool:
        """确认对话框"""
        if RICH_AVAILABLE and console:
            return Confirm.ask(prompt, default=default)
        else:
            default_str = "Y/n" if default else "y/N"
            result = input(f"{prompt} [{default_str}]: ").strip().lower()
            if not result:
                return default
            return result in ['y', 'yes']

    def check_python_version(self) -> bool:
        """检查Python版本"""
        self._print_header("Python版本检查")

        version = sys.version_info
        if version.major < 3 or (version.major == 3 and version.minor < 10):
            self._print_error(f"需要Python 3.10+，当前版本: {version.major}.{version.minor}")
            return False

        self._print_success(f"Python版本: {version.major}.{version.minor}.{version.micro}")
        return True

    def check_package(self, package_name: str) -> bool:
        """检查包是否已安装"""
        try:
            __import__(package_name.replace('-', '_'))
            return True
        except ImportError:
            return False

    def install_package(self, package_name: str) -> bool:
        """安装单个包"""
        self._print(f"正在安装 {package_name}...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", package_name, "-q"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self._print_success(f"{package_name} 安装成功")
            return True
        except subprocess.CalledProcessError as e:
            self._print_error(f"{package_name} 安装失败: {e}")
            return False

    def check_and_install_dependencies(self, packages: List[str]) -> bool:
        """检查并安装依赖"""
        self._print_header("依赖检查")

        missing = []
        for pkg in packages:
            pkg_import = pkg.replace('-', '_').split('[')[0]
            if not self.check_package(pkg_import):
                missing.append(pkg)
            else:
                self._print_success(f"{pkg} 已安装")

        if not missing:
            self._print_success("所有依赖已满足")
            return True

        self._print_warning(f"缺少 {len(missing)} 个依赖包: {', '.join(missing)}")

        if not self._confirm("是否自动安装缺失的依赖？", default=True):
            self._print_error("用户取消安装，无法继续")
            return False

        # 安装缺失的包
        for pkg in missing:
            if not self.install_package(pkg):
                return False

        return True

    def configure_service(self, service_key: str) -> Optional[Dict[str, str]]:
        """配置单个服务"""
        service = SERVICES.get(service_key)
        if not service:
            self._print_error(f"未知服务: {service_key}")
            return None

        self._print_header(f"配置 {service.name}")
        self._print(service.description)
        self._print(f"文档: {service.doc_url}")
        print()

        # 先安装依赖
        if service.required_packages:
            if not self.check_and_install_dependencies(service.required_packages):
                return None

        # 收集配置
        config = {}
        for field in service.config_fields:
            name = field["name"]
            prompt = field["prompt"]
            default = field.get("default", "")
            secret = field.get("secret", False)

            value = self._input(prompt, default=default, secret=secret)
            config[name] = value

        # 验证配置（如果有验证方法）
        if hasattr(self, f'validate_{service_key}'):
            validator = getattr(self, f'validate_{service_key}')
            if not validator(config):
                return None

        return config

    def select_llm_provider(self) -> Tuple[str, Dict[str, str]]:
        """选择LLM提供商"""
        self._print_header("选择大语言模型 (LLM)")

        # 显示选项
        llm_services = [(k, v) for k, v in SERVICES.items() if v.type == ServiceType.LLM]
        llm_services.sort(key=lambda x: x[1].priority)

        if RICH_AVAILABLE and console:
            table = Table(title="可用的LLM服务")
            table.add_column("选项", style="cyan")
            table.add_column("名称", style="green")
            table.add_column("描述", style="white")

            for i, (key, svc) in enumerate(llm_services, 1):
                table.add_row(str(i), svc.name, svc.description)

            console.print(table)
        else:
            print("\n可用的LLM服务:")
            for i, (key, svc) in enumerate(llm_services, 1):
                print(f"  {i}. {svc.name} - {svc.description}")

        print()

        # 获取选择
        while True:
            choice = self._input("请选择 (输入序号)", default="1")
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(llm_services):
                    selected_key, selected_service = llm_services[idx]
                    break
                else:
                    self._print_error("无效的选择")
            except ValueError:
                self._print_error("请输入数字")

        # 配置选中的服务
        config = self.configure_service(selected_key)
        if config is None:
            self._print_error("配置失败")
            return self.select_llm_provider()  # 递归重试

        return selected_key, config

    def select_embedding_provider(self) -> Tuple[str, Dict[str, str]]:
        """选择Embedding提供商"""
        self._print_header("选择向量嵌入 (Embedding) 服务")

        embedding_services = [(k, v) for k, v in SERVICES.items() if v.type == ServiceType.EMBEDDING]
        embedding_services.sort(key=lambda x: x[1].priority)

        if RICH_AVAILABLE and console:
            table = Table(title="可用的Embedding服务")
            table.add_column("选项", style="cyan")
            table.add_column("名称", style="green")
            table.add_column("描述", style="white")

            for i, (key, svc) in enumerate(embedding_services, 1):
                table.add_row(str(i), svc.name, svc.description)

            console.print(table)
        else:
            print("\n可用的Embedding服务:")
            for i, (key, svc) in enumerate(embedding_services, 1):
                print(f"  {i}. {svc.name} - {svc.description}")

        print()

        while True:
            choice = self._input("请选择 (输入序号)", default="1")
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(embedding_services):
                    selected_key, selected_service = embedding_services[idx]
                    break
                else:
                    self._print_error("无效的选择")
            except ValueError:
                self._print_error("请输入数字")

        config = self.configure_service(selected_key)
        if config is None:
            return self.select_embedding_provider()

        return selected_key, config

    def configure_generation_params(self) -> Dict[str, Any]:
        """配置生成参数"""
        self._print_header("配置生成参数")

        params = {}

        if RICH_AVAILABLE and console:
            params['target_length'] = IntPrompt.ask(
                "目标字数",
                default=100000
            )
            params['total_chapters'] = IntPrompt.ask(
                "章节数",
                default=5
            )
        else:
            target = input("目标字数 [100000]: ").strip()
            params['target_length'] = int(target) if target else 100000

            chapters = input("章节数 [5]: ").strip()
            params['total_chapters'] = int(chapters) if chapters else 5

        # 风格选择
        styles = ["literary", "documentary", "investigative"]
        print("\n写作风格:")
        print("  1. literary - 文学散文（抒情描写）")
        print("  2. documentary - 纪实严谨（客观中立）")
        print("  3. investigative - 新闻调查（抽丝剥茧）")

        style_choice = self._input("选择风格", default="1")
        style_map = {"1": "literary", "2": "documentary", "3": "investigative"}
        params['style'] = style_map.get(style_choice, "literary")

        return params

    def save_config(self, llm_provider: str, llm_config: Dict,
                    embedding_provider: str, embedding_config: Dict,
                    generation_params: Dict):
        """保存配置"""
        self._print_header("保存配置")

        # 1. 保存到 .env 文件
        env_lines = [
            "# 传记写作系统自动生成的配置",
            f"# 生成时间: {__import__('datetime').datetime.now().isoformat()}",
            "",
            "# LLM配置",
            f"LLM_PROVIDER={llm_provider}",
        ]

        # 添加LLM配置
        service = SERVICES.get(llm_provider)
        for field in service.config_fields:
            env_name = field["env"]
            value = llm_config.get(field["name"], "")
            if value:
                env_lines.append(f"{env_name}={value}")

        env_lines.append("")
        env_lines.append("# Embedding配置")
        env_lines.append(f"EMBEDDING_PROVIDER={embedding_provider}")

        # 添加Embedding配置
        emb_service = SERVICES.get(embedding_provider)
        for field in emb_service.config_fields:
            env_name = field["env"]
            value = embedding_config.get(field["name"], "")
            if value:
                env_lines.append(f"{env_name}={value}")

        # 写入.env文件
        with open(self.env_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(env_lines))

        self._print_success(f"配置已保存到: {self.env_file}")

        # 2. 保存生成参数到YAML
        import yaml
        self.config_file.parent.mkdir(exist_ok=True)

        yaml_config = {
            'generation': generation_params,
            'model': {
                'provider': llm_provider,
                'embedding_provider': embedding_provider
            }
        }

        with open(self.config_file, 'w', encoding='utf-8') as f:
            yaml.dump(yaml_config, f, allow_unicode=True, default_flow_style=False)

        self._print_success(f"生成参数已保存到: {self.config_file}")

    def run(self) -> bool:
        """运行完整配置向导"""
        self._print_header("🚀 传记写作系统 - 配置向导")

        if RICH_AVAILABLE and console:
            console.print(Markdown("""
欢迎使用传记写作系统配置向导！

本向导将帮助您：
1. 检查Python环境
2. 安装必要的依赖
3. 配置大语言模型 (LLM)
4. 配置向量嵌入服务
5. 设置生成参数
6. 保存配置
"""))
        else:
            print("""
欢迎使用传记写作系统配置向导！

本向导将帮助您：
1. 检查Python环境
2. 安装必要的依赖
3. 配置大语言模型 (LLM)
4. 配置向量嵌入服务
5. 设置生成参数
6. 保存配置
""")

        # 步骤1: 检查Python版本
        if not self.check_python_version():
            return False

        # 步骤2: 安装基础依赖
        if not self.check_and_install_dependencies(['rich', 'pyyaml', 'python-dotenv']):
            return False

        # 步骤3: 选择并配置LLM
        llm_provider, llm_config = self.select_llm_provider()

        # 步骤4: 选择并配置Embedding
        embedding_provider, embedding_config = self.select_embedding_provider()

        # 步骤5: 配置生成参数
        generation_params = self.configure_generation_params()

        # 步骤6: 保存配置
        self.save_config(
            llm_provider, llm_config,
            embedding_provider, embedding_config,
            generation_params
        )

        # 完成
        self._print_header("✨ 配置完成！")
        self._print("您现在可以运行以下命令开始生成传记：")
        self._print("")
        self._print("  python3 generate_book.py", style="bold green" if RICH_AVAILABLE else "")
        self._print("")
        self._print("或：")
        self._print("")
        self._print("  python3 -m src", style="bold green" if RICH_AVAILABLE else "")

        return True


def main():
    """入口函数"""
    wizard = SetupWizard()
    success = wizard.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
