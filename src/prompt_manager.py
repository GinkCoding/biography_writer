"""
提示词模板管理器

提供基于Jinja2的提示词模板系统，支持：
- 模板化提示词管理
- 分层引用披露（L0-L3）
- 结构化输出格式定义
- Few-shot示例管理
- 约束分级（硬约束/软约束）
"""

import json
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from enum import Enum

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape
from pydantic import BaseModel, Field
from loguru import logger


class ContextLevel(Enum):
    """上下文加载级别"""
    L0_MINIMAL = "l0"      # 最小上下文
    L1_ESSENTIAL = "l1"    # 必要上下文
    L2_EXTENDED = "l2"     # 扩展上下文
    L3_COMPLETE = "l3"     # 完整上下文


class WritingStyle(Enum):
    """写作风格"""
    DOCUMENTARY = "documentary"      # 纪实风格
    LITERARY = "literary"            # 文学风格
    INVESTIGATIVE = "investigative"  # 调查风格
    MEMOIR = "memoir"                # 回忆录风格


@dataclass
class Constraint:
    """约束定义"""
    text: str
    is_hard: bool = True  # True=硬约束, False=软约束
    category: str = "general"  # general, content, style, fact


@dataclass
class Example:
    """示例定义"""
    title: str
    content: str
    analysis: str
    is_positive: bool = True  # True=正面示例, False=反面示例
    category: str = "general"


class PromptManager:
    """
    提示词模板管理器

    负责加载、渲染和管理所有提示词模板。
    支持分层模板继承和动态内容注入。
    """

    def __init__(self, templates_dir: Optional[Path] = None):
        """
        初始化提示词管理器

        Args:
            templates_dir: 模板目录路径，默认为项目根目录下的templates/
        """
        if templates_dir is None:
            # 默认模板目录：项目根目录/templates/
            self.templates_dir = Path(__file__).parent.parent / "templates"
        else:
            self.templates_dir = Path(templates_dir)

        # 初始化Jinja2环境
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
            enable_async=False
        )

        # 添加自定义过滤器
        self.env.filters['tojson'] = json.dumps

        # 缓存已加载的模板
        self._template_cache: Dict[str, Template] = {}

        # 缓存示例和约束
        self._examples_cache: Optional[Dict[str, List[Example]]] = None
        self._constraints_cache: Optional[Dict[str, List[Constraint]]] = None

        logger.info(f"PromptManager初始化完成，模板目录: {self.templates_dir}")

    def load_template(self, template_name: str) -> Template:
        """
        加载模板

        Args:
            template_name: 模板名称（相对templates目录的路径）

        Returns:
            Template: Jinja2模板对象

        Raises:
            TemplateNotFound: 模板不存在时抛出
        """
        # 检查缓存
        if template_name in self._template_cache:
            return self._template_cache[template_name]

        # 加载模板
        template = self.env.get_template(template_name)
        self._template_cache[template_name] = template

        logger.debug(f"模板已加载: {template_name}")
        return template

    def render(self, template_name: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        渲染模板

        Args:
            template_name: 模板名称
            context: 渲染上下文变量

        Returns:
            str: 渲染后的提示词文本
        """
        template = self.load_template(template_name)
        ctx = context or {}

        # 添加默认上下文变量
        ctx.setdefault('context_level', 'l1')
        ctx.setdefault('inference_mode', False)

        try:
            result = template.render(**ctx)
            return result.strip()
        except Exception as e:
            logger.error(f"模板渲染失败 {template_name}: {e}")
            raise

    def get_style_template(self, style: Union[WritingStyle, str]) -> Template:
        """
        获取风格模板

        Args:
            style: 写作风格枚举或字符串

        Returns:
            Template: 对应风格的模板
        """
        if isinstance(style, str):
            style = WritingStyle(style)

        template_name = f"styles/{style.value}.j2"
        return self.load_template(template_name)

    def render_style_prompt(
        self,
        style: Union[WritingStyle, str],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        渲染风格化系统提示词

        Args:
            style: 写作风格
            context: 渲染上下文

        Returns:
            str: 渲染后的系统提示词
        """
        ctx = context or {}
        ctx['style'] = style.value if isinstance(style, WritingStyle) else style

        return self.render(f"styles/{ctx['style']}.j2", ctx)

    def get_examples(
        self,
        category: str = "general",
        positive: Optional[bool] = None
    ) -> List[Example]:
        """
        获取示例

        Args:
            category: 示例类别
            positive: True=只返回正面示例, False=只返回反面示例, None=全部

        Returns:
            List[Example]: 示例列表
        """
        if self._examples_cache is None:
            self._load_examples()

        examples = self._examples_cache.get(category, [])

        if positive is not None:
            examples = [e for e in examples if e.is_positive == positive]

        return examples

    def _load_examples(self):
        """加载所有示例"""
        self._examples_cache = {
            "concrete_detail": [
                Example(
                    title="基于具体素材",
                    content="1982年春天，陈国伟背着布包走进藤编厂（来源：素材3）。厂门口有棵老榕树，车间里是成捆的藤条和化学药剂的味道。门卫老头翻着登记簿说：'你就是那个手很巧的小子。'",
                    analysis="优点：具体时间、地点、对话、气味细节，都有来源支撑",
                    is_positive=True
                ),
                Example(
                    title="套路化意象",
                    content="晨光透过窗户洒进来，尘埃在光柱中飞舞。陈国伟端起茶杯，凉茶早已凉透，苦涩中带着回甘。",
                    analysis="问题：'尘埃光柱'、'凉茶苦甘'是AI常见套路，无具体来源",
                    is_positive=False
                )
            ],
            "show_dont_tell": [
                Example(
                    title="有言行支撑的心理",
                    content="陈国伟站在厂门口，深吸一口气——那是藤条被水泡发后的清香，混合着汗味和机油味（来源：素材3）。他没有立即进去，而是在榕树下站了几分钟，把布包的带子攥紧了又松开。",
                    analysis="优点：通过动作（吸气、攥带子）表现紧张，而非直接说'他很紧张'",
                    is_positive=True
                ),
                Example(
                    title="情感标签",
                    content="得知这个消息，陈国伟陷入了沉思，心中充满了复杂的情绪。",
                    analysis="问题：'陷入沉思'、'充满情绪'是空洞标签，没有具体言行支撑",
                    is_positive=False
                )
            ],
            "era_context": [
                Example(
                    title="时代背景具体化",
                    content="1984年，陈国伟第一次离开佛山去广州。那时候广州火车站很乱，他在流花湖那边倒腾服装，从石狮进货。没有营业执照，看到戴红袖箍的来抓，卷起包袱就跑（来源：素材2）。",
                    analysis="优点：具体年份、地点、行为细节，而非'改革开放初期'的空泛描述",
                    is_positive=True
                ),
                Example(
                    title="空泛表述",
                    content="那是一个风云变幻、波澜壮阔的特殊年代，对陈国伟的人生产生了深刻影响。",
                    analysis="问题：没有具体时间地点，全是空泛形容词",
                    is_positive=False
                )
            ]
        }

    def get_constraints(
        self,
        category: str = "general",
        hard_only: Optional[bool] = None
    ) -> List[Constraint]:
        """
        获取约束

        Args:
            category: 约束类别
            hard_only: True=只返回硬约束, False=只返回软约束, None=全部

        Returns:
            List[Constraint]: 约束列表
        """
        if self._constraints_cache is None:
            self._load_constraints()

        constraints = self._constraints_cache.get(category, [])

        if hard_only is not None:
            constraints = [c for c in constraints if c.is_hard == hard_only]

        return constraints

    def _load_constraints(self):
        """加载所有约束"""
        self._constraints_cache = {
            "general": [
                Constraint(
                    text="必须使用提供的采访素材中的具体细节：人名、地名、时间、对话、数字",
                    is_hard=True,
                    category="fact"
                ),
                Constraint(
                    text="引用采访内容时，在括号中标注来源，如（来源：素材1）",
                    is_hard=True,
                    category="fact"
                ),
                Constraint(
                    text="不得编造未在素材中出现的具体人物、事件、地点",
                    is_hard=True,
                    category="fact"
                ),
                Constraint(
                    text="必须明确时间点，结合当时的社会背景",
                    is_hard=True,
                    category="content"
                ),
                Constraint(
                    text="每300字必须包含至少1个具体时间、地点、数字或人物对话",
                    is_hard=True,
                    category="content"
                ),
                Constraint(
                    text="建议使用感官描写增强场景感",
                    is_hard=False,
                    category="style"
                ),
                Constraint(
                    text="建议保持段落长度适中，避免过长段落",
                    is_hard=False,
                    category="style"
                )
            ],
            "forbidden": [
                Constraint(text="待补充、待完善、此处需要展开", is_hard=True, category="placeholder"),
                Constraint(text="尘埃在光柱中飞舞、苦涩中带着回甘、命运的齿轮", is_hard=True, category="cliche"),
                Constraint(text="那是一个特殊的年代、风云变幻、波澜壮阔", is_hard=True, category="vague"),
                Constraint(text="我为您撰写、这是一个通用模板", is_hard=True, category="ai_exposure"),
                Constraint(text="暴风雨前的宁静、真相伺机而动", is_hard=True, category="suspense"),
                Constraint(text="陷入了沉思、百感交集、心中充满", is_hard=True, category="emotion_label"),
            ]
        }

    def render_for_context_level(
        self,
        template_name: str,
        context_level: ContextLevel,
        base_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        根据上下文级别渲染模板

        Args:
            template_name: 模板名称
            context_level: 上下文级别
            base_context: 基础上下文

        Returns:
            str: 渲染后的提示词
        """
        ctx = base_context or {}
        ctx['context_level'] = context_level.value

        # 根据级别调整约束和示例
        if context_level == ContextLevel.L0_MINIMAL:
            # L0: 最小约束
            ctx['hard_constraints'] = self.get_constraints(hard_only=True)[:3]
            ctx['show_examples'] = False
        elif context_level == ContextLevel.L1_ESSENTIAL:
            # L1: 基本约束
            ctx['hard_constraints'] = self.get_constraints(hard_only=True)
            ctx['show_examples'] = True
            ctx['show_negative'] = True
        elif context_level == ContextLevel.L2_EXTENDED:
            # L2: 扩展约束
            ctx['hard_constraints'] = self.get_constraints(hard_only=True)
            ctx['soft_constraints'] = self.get_constraints(hard_only=False)
            ctx['show_examples'] = True
            ctx['show_positive'] = True
            ctx['show_negative'] = True
        else:  # L3_COMPLETE
            # L3: 完整约束
            ctx['hard_constraints'] = self.get_constraints(hard_only=True)
            ctx['soft_constraints'] = self.get_constraints(hard_only=False)
            ctx['show_examples'] = True
            ctx['show_positive'] = True
            ctx['show_negative'] = True
            ctx['detailed_guidance'] = True

        return self.render(template_name, ctx)

    def get_output_schema(self, schema_name: str) -> Optional[Dict]:
        """
        获取输出格式定义（JSON Schema）

        Args:
            schema_name: Schema名称（如 'chapter', 'outline', 'review'）

        Returns:
            Optional[Dict]: JSON Schema定义
        """
        schema_path = self.templates_dir / "output_schemas" / f"{schema_name}.json"

        if not schema_path.exists():
            logger.warning(f"Schema不存在: {schema_path}")
            return None

        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载Schema失败 {schema_name}: {e}")
            return None

    def validate_output(self, output: Dict, schema_name: str) -> tuple[bool, List[str]]:
        """
        验证输出是否符合Schema

        Args:
            output: 待验证的输出数据
            schema_name: Schema名称

        Returns:
            tuple[bool, List[str]]: (是否通过, 错误信息列表)
        """
        try:
            from jsonschema import validate, ValidationError

            schema = self.get_output_schema(schema_name)
            if not schema:
                return False, [f"Schema不存在: {schema_name}"]

            validate(instance=output, schema=schema)
            return True, []
        except ValidationError as e:
            return False, [str(e)]
        except ImportError:
            logger.warning("jsonschema未安装，跳过验证")
            return True, []
        except Exception as e:
            return False, [str(e)]

    def render_generation_prompt(
        self,
        style: WritingStyle,
        context: Dict[str, Any],
        context_level: ContextLevel = ContextLevel.L1_ESSENTIAL
    ) -> str:
        """
        渲染生成层系统提示词

        Args:
            style: 写作风格
            context: 上下文变量
            context_level: 上下文级别

        Returns:
            str: 系统提示词
        """
        ctx = context.copy()
        ctx['style'] = style.value

        return self.render_for_context_level(
            "system/generation.j2",
            context_level,
            ctx
        )

    def render_review_prompt(
        self,
        review_type: str,
        context: Dict[str, Any],
        context_level: ContextLevel = ContextLevel.L1_ESSENTIAL
    ) -> str:
        """
        渲染审校提示词

        Args:
            review_type: 审校类型（continuity/fact_check/quality/placeholder_check）
            context: 上下文变量
            context_level: 上下文级别

        Returns:
            str: 审校提示词
        """
        ctx = context.copy()
        ctx['review_type'] = review_type

        return self.render_for_context_level(
            "system/review.j2",
            context_level,
            ctx
        )

    def render_extraction_prompt(
        self,
        extraction_type: str,
        context: Dict[str, Any]
    ) -> str:
        """
        渲染信息提取提示词

        Args:
            extraction_type: 提取类型（entities/timeline/character_state/scenes）
            context: 上下文变量

        Returns:
            str: 提取提示词
        """
        ctx = context.copy()
        ctx['extraction_type'] = extraction_type

        return self.render("system/extraction.j2", ctx)

    def list_available_templates(self) -> List[str]:
        """
        列出所有可用模板

        Returns:
            List[str]: 模板路径列表
        """
        templates = []

        for ext in ['*.j2']:
            for template_file in self.templates_dir.rglob(ext):
                # 获取相对路径
                rel_path = template_file.relative_to(self.templates_dir)
                templates.append(str(rel_path))

        return sorted(templates)

    def list_available_schemas(self) -> List[str]:
        """
        列出所有可用输出Schema

        Returns:
            List[str]: Schema名称列表
        """
        schemas_dir = self.templates_dir / "output_schemas"
        if not schemas_dir.exists():
            return []

        return sorted([f.stem for f in schemas_dir.glob("*.json")])


# =============================================================================
# 便捷函数
# =============================================================================

_default_manager: Optional[PromptManager] = None


def get_prompt_manager(templates_dir: Optional[Path] = None) -> PromptManager:
    """
    获取默认提示词管理器实例（单例模式）

    Args:
        templates_dir: 模板目录路径

    Returns:
        PromptManager: 提示词管理器实例
    """
    global _default_manager

    if _default_manager is None:
        _default_manager = PromptManager(templates_dir)

    return _default_manager


def render_prompt(
    template_name: str,
    context: Optional[Dict[str, Any]] = None,
    templates_dir: Optional[Path] = None
) -> str:
    """
    便捷函数：渲染提示词

    Args:
        template_name: 模板名称
        context: 渲染上下文
        templates_dir: 模板目录路径

    Returns:
        str: 渲染后的提示词
    """
    manager = get_prompt_manager(templates_dir)
    return manager.render(template_name, context)


# 导出主要类和函数
__all__ = [
    'PromptManager',
    'ContextLevel',
    'WritingStyle',
    'Constraint',
    'Example',
    'get_prompt_manager',
    'render_prompt'
]
