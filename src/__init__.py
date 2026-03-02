"""传记写作系统 - 五层架构实现

该系统实现了从采访稿到完整传记书籍的自动化生成流程，
采用五层架构设计：数据摄入→知识记忆→规划→生成→审校输出。

提示词模板系统：
- 使用Jinja2模板引擎管理提示词
- 支持分层引用披露（L0-L3）
- 支持风格模板切换
"""

__version__ = "1.0.0"
__author__ = "Biography Writer Team"

# 导出核心组件（延迟导入避免循环依赖）
def __getattr__(name):
    if name == "Settings":
        from .config import Settings
        return Settings
    if name == "settings":
        from .config import settings
        return settings
    if name == "ConfigManager":
        from .config_manager import ConfigManager
        return ConfigManager
    if name == "require_config":
        from .config_manager import require_config
        return require_config
    if name == "PromptManager":
        from .prompt_manager import PromptManager
        return PromptManager
    if name == "get_prompt_manager":
        from .prompt_manager import get_prompt_manager
        return get_prompt_manager
    if name == "ContextLevel":
        from .prompt_manager import ContextLevel
        return ContextLevel
    if name == "WritingStyle":
        from .prompt_manager import WritingStyle
        return WritingStyle
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
