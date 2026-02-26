"""
配置管理器 - 运行时配置检查和交互式配置获取

功能：
1. 自动检测配置是否完整
2. 缺失配置时暂停并引导用户输入
3. 支持环境变量、.env文件、交互式输入三级配置
4. 配置验证和缓存
"""
import os
import sys
import json
from pathlib import Path
from typing import Dict, Optional, Any, List, Callable
from dataclasses import dataclass
from functools import wraps

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# 尝试加载python-dotenv
try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False


console = Console() if RICH_AVAILABLE else None


def _print(message: str, style: str = ""):
    """打印消息"""
    if RICH_AVAILABLE and console:
        if style:
            console.print(message, style=style)
        else:
            console.print(message)
    else:
        print(message)


def _input(prompt: str, default: str = "", secret: bool = False) -> str:
    """获取用户输入"""
    if secret:
        import getpass
        return getpass.getpass(f"{prompt}: ") or default

    if RICH_AVAILABLE and console:
        return Prompt.ask(prompt, default=default) if default else Prompt.ask(prompt)
    else:
        if default:
            full_prompt = f"{prompt} [{default}]: "
        else:
            full_prompt = f"{prompt}: "
        result = input(full_prompt).strip()
        return result if result else default


def _confirm(prompt: str, default: bool = True) -> bool:
    """确认对话框"""
    if RICH_AVAILABLE and console:
        return Confirm.ask(prompt, default=default)
    else:
        default_str = "Y/n" if default else "y/N"
        result = input(f"{prompt} [{default_str}]: ").strip().lower()
        if not result:
            return default
        return result in ['y', 'yes']


@dataclass
class ConfigRequirement:
    """配置需求定义"""
    key: str
    name: str
    description: str
    prompt: str
    secret: bool = False
    default: Optional[str] = None
    validator: Optional[Callable[[str], bool]] = None
    env_vars: List[str] = None  # 可能的环境变量名列表


class ConfigManager:
    """配置管理器"""

    # 预定义的配置需求
    REQUIREMENTS = {
        'llm': {
            'kimi': [
                ConfigRequirement(
                    key='api_key',
                    name='Kimi API Key',
                    description='月之暗面Kimi API密钥',
                    prompt='请输入 Kimi API Key',
                    secret=True,
                    env_vars=['KIMI_API_KEY', 'MOONSHOT_API_KEY', 'OPENAI_API_KEY']
                ),
                ConfigRequirement(
                    key='base_url',
                    name='Base URL',
                    description='API基础URL',
                    prompt='API Base URL',
                    default='https://api.moonshot.cn/v1',
                    env_vars=['KIMI_BASE_URL', 'MOONSHOT_BASE_URL']
                ),
            ],
            'openai': [
                ConfigRequirement(
                    key='api_key',
                    name='OpenAI API Key',
                    description='OpenAI API密钥',
                    prompt='请输入 OpenAI API Key',
                    secret=True,
                    env_vars=['OPENAI_API_KEY']
                ),
                ConfigRequirement(
                    key='base_url',
                    name='Base URL',
                    description='API基础URL（可选）',
                    prompt='API Base URL (可选)',
                    default='',
                    env_vars=['OPENAI_BASE_URL']
                ),
            ],
            'zhipuai': [
                ConfigRequirement(
                    key='api_key',
                    name='智谱AI API Key',
                    description='智谱AI API密钥',
                    prompt='请输入 智谱AI API Key',
                    secret=True,
                    env_vars=['ZHIPUAI_API_KEY']
                ),
            ],
        },
        'embedding': {
            'siliconflow': [
                ConfigRequirement(
                    key='api_key',
                    name='SiliconFlow API Key',
                    description='硅基流动API密钥',
                    prompt='请输入 SiliconFlow API Key',
                    secret=True,
                    env_vars=['SILICONFLOW_API_KEY']
                ),
                ConfigRequirement(
                    key='model',
                    name='模型',
                    description='Embedding模型',
                    prompt='Embedding模型',
                    default='BAAI/bge-large-zh-v1.5',
                    env_vars=['SILICONFLOW_MODEL']
                ),
            ],
            'sentence_transformer': [
                ConfigRequirement(
                    key='model',
                    name='模型',
                    description='本地模型名称',
                    prompt='模型名称',
                    default='BAAI/bge-small-zh-v1.5',
                    env_vars=['SENTENCE_TRANSFORMER_MODEL']
                ),
            ],
        }
    }

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path(__file__).parent.parent
        self.env_file = self.project_root / ".env"
        self.cache_file = self.project_root / ".cache" / "config_cache.json"
        self._config_cache: Dict[str, Any] = {}
        self._interactive_mode = True

        # 加载.env文件
        if DOTENV_AVAILABLE and self.env_file.exists():
            load_dotenv(self.env_file)

        # 加载缓存
        self._load_cache()

    def _load_cache(self):
        """加载配置缓存"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self._config_cache = json.load(f)
            except:
                self._config_cache = {}

    def _save_cache(self):
        """保存配置缓存"""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self._config_cache, f, ensure_ascii=False, indent=2)

    def _get_from_env(self, env_vars: List[str]) -> Optional[str]:
        """从环境变量获取配置"""
        for var in env_vars:
            value = os.getenv(var)
            if value:
                return value
        return None

    def _save_to_env_file(self, key: str, value: str):
        """保存配置到.env文件"""
        lines = []
        if self.env_file.exists():
            with open(self.env_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

        # 查找并替换或追加
        key_found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                key_found = True
                break

        if not key_found:
            lines.append(f"{key}={value}\n")

        with open(self.env_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)

    def disable_interactive(self):
        """禁用交互模式（用于CI/CD）"""
        self._interactive_mode = False

    def require_config(self, service_type: str, service_name: str) -> Dict[str, str]:
        """
        确保服务配置存在，缺失时引导用户输入

        Args:
            service_type: 服务类型 ('llm', 'embedding')
            service_name: 服务名称 ('kimi', 'openai', etc.)

        Returns:
            配置字典
        """
        cache_key = f"{service_type}:{service_name}"

        # 检查缓存
        if cache_key in self._config_cache:
            return self._config_cache[cache_key]

        requirements = self.REQUIREMENTS.get(service_type, {}).get(service_name, [])
        if not requirements:
            raise ValueError(f"未知的配置类型: {service_type}/{service_name}")

        config = {}
        missing_requirements = []

        # 首先尝试从环境变量获取
        for req in requirements:
            value = None
            if req.env_vars:
                value = self._get_from_env(req.env_vars)

            if value:
                config[req.key] = value
            else:
                missing_requirements.append(req)

        # 如果有缺失的配置，进入交互模式
        if missing_requirements:
            if not self._interactive_mode:
                # 非交互模式，抛出错误
                missing_names = [r.name for r in missing_requirements]
                raise RuntimeError(
                    f"缺少必要的配置: {', '.join(missing_names)}。"
                    f"请设置环境变量或在.env文件中配置。"
                )

            # 显示提示信息
            _print(f"\n⚠️  检测到 {service_name} 配置缺失", style="yellow")
            _print(f"服务类型: {service_type}")
            _print("")

            # 引导用户输入
            for req in missing_requirements:
                _print(f"📋 {req.name}", style="bold")
                _print(f"   {req.description}")

                while True:
                    value = _input(req.prompt, default=req.default or "", secret=req.secret)

                    if not value and not req.default:
                        _print("❌ 此项为必填项，请重新输入", style="red")
                        continue

                    # 验证
                    if req.validator and not req.validator(value):
                        _print("❌ 输入格式不正确，请重新输入", style="red")
                        continue

                    break

                config[req.key] = value

                # 保存到环境变量文件
                if req.env_vars:
                    self._save_to_env_file(req.env_vars[0], value)

        # 缓存配置
        self._config_cache[cache_key] = config
        self._save_cache()

        return config

    def check_llm_config(self, provider: Optional[str] = None) -> Tuple[str, Dict[str, str]]:
        """
        检查并获取LLM配置

        Returns:
            (provider, config)
        """
        # 尝试从环境变量获取提供商
        if not provider:
            provider = os.getenv('LLM_PROVIDER', '').lower()

        if not provider:
            # 交互式选择
            if not self._interactive_mode:
                raise RuntimeError("未设置 LLM_PROVIDER 环境变量")

            _print("\n🤖 请选择大语言模型 (LLM) 提供商:", style="bold")
            _print("  1. kimi - 月之暗面Kimi (推荐)")
            _print("  2. openai - OpenAI GPT")
            _print("  3. zhipuai - 智谱AI GLM")

            choice = _input("选择 (1-3)", default="1")
            provider_map = {'1': 'kimi', '2': 'openai', '3': 'zhipuai'}
            provider = provider_map.get(choice, 'kimi')

            self._save_to_env_file('LLM_PROVIDER', provider)

        config = self.require_config('llm', provider)
        return provider, config

    def check_embedding_config(self, provider: Optional[str] = None) -> Tuple[str, Dict[str, str]]:
        """
        检查并获取Embedding配置

        Returns:
            (provider, config)
        """
        if not provider:
            provider = os.getenv('EMBEDDING_PROVIDER', '').lower()

        if not provider:
            if not self._interactive_mode:
                raise RuntimeError("未设置 EMBEDDING_PROVIDER 环境变量")

            _print("\n🔢 请选择向量嵌入 (Embedding) 提供商:", style="bold")
            _print("  1. siliconflow - 硅基流动API (推荐，无需本地模型)")
            _print("  2. sentence_transformer - 本地模型 (需下载，无需API)")
            _print("  3. openai - OpenAI Embedding")

            choice = _input("选择 (1-3)", default="1")
            provider_map = {'1': 'siliconflow', '2': 'sentence_transformer', '3': 'openai'}
            provider = provider_map.get(choice, 'siliconflow')

            self._save_to_env_file('EMBEDDING_PROVIDER', provider)

        config = self.require_config('embedding', provider)
        return provider, config

    def get_full_config(self) -> Dict[str, Any]:
        """获取完整配置"""
        llm_provider, llm_config = self.check_llm_config()
        emb_provider, emb_config = self.check_embedding_config()

        return {
            'llm': {
                'provider': llm_provider,
                'config': llm_config
            },
            'embedding': {
                'provider': emb_provider,
                'config': emb_config
            }
        }


def require_config(service_type: str, service_name: str) -> Dict[str, str]:
    """
    便捷函数：获取服务配置，缺失时引导用户输入

    使用示例:
        config = require_config('llm', 'kimi')
        api_key = config['api_key']
    """
    manager = ConfigManager()
    return manager.require_config(service_type, service_name)


def check_all_configs() -> Dict[str, Any]:
    """
    便捷函数：检查并获取所有配置

    使用示例:
        config = check_all_configs()
        llm_config = config['llm']
    """
    manager = ConfigManager()
    return manager.get_full_config()


# 装饰器：自动检查配置
def with_config(service_type: str, service_name: str):
    """
    装饰器：自动注入服务配置

    使用示例:
        @with_config('llm', 'kimi')
        def generate_content(config, text):
            api_key = config['api_key']
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            config = require_config(service_type, service_name)
            return func(config, *args, **kwargs)
        return wrapper
    return decorator


if __name__ == "__main__":
    # 测试配置管理器
    print("测试配置管理器...")

    try:
        config = check_all_configs()
        print("\n配置获取成功:")
        print(f"  LLM: {config['llm']['provider']}")
        print(f"  Embedding: {config['embedding']['provider']}")
    except Exception as e:
        print(f"错误: {e}")
