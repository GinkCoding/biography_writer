"""大模型客户端封装 - 支持多提供商和自动配置"""
import os
import asyncio
from datetime import datetime
from typing import AsyncIterator, List, Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

from src.config import settings
from src.models import WritingStyle

# 导入可观测性模块
from src.observability import MetricsCollector
from src.observability.workflow_tracer import WorkflowTracer, LayerType, TraceStatus


class LLMClient:
    """
    多提供商LLM客户端

    支持：Kimi、OpenAI、智谱AI等
    自动检测配置并引导用户输入
    """

    def __init__(self, provider: Optional[str] = None, config: Optional[Dict] = None):
        """
        初始化LLM客户端

        Args:
            provider: 提供商名称 (kimi, openai, zhipuai)，None则自动检测
            config: 配置字典，None则自动获取
        """
        # 如果未提供配置，使用配置管理器获取
        if provider is None or config is None:
            from src.config_manager import ConfigManager
            manager = ConfigManager()
            self.provider, self.config = manager.check_llm_config(provider)
        else:
            self.provider = provider
            self.config = config

        self.max_tokens = settings.model.max_tokens
        self.temperature = settings.model.temperature

        # 初始化可观测性组件
        self.metrics = MetricsCollector()
        self.tracer = WorkflowTracer()

        # 初始化对应提供商的客户端
        self._init_client()

    def _init_client(self):
        """初始化具体提供商的客户端"""
        if self.provider == "kimi":
            self._init_kimi()
        elif self.provider == "openai":
            self._init_openai()
        elif self.provider == "zhipuai":
            self._init_zhipuai()
        else:
            raise ValueError(f"不支持的提供商: {self.provider}")

    def _init_kimi(self):
        """初始化Kimi客户端"""
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=self.config.get('api_key'),
                base_url=self.config.get('base_url', 'https://api.moonshot.cn/v1')
            )
            self.model = self.config.get('model', 'moonshot-v1-128k')
            logger.info(f"Kimi客户端初始化成功，模型: {self.model}")
        except ImportError:
            logger.error("未安装openai包，请运行: pip install openai")
            raise

    def _init_openai(self):
        """初始化OpenAI客户端"""
        try:
            from openai import OpenAI
            base_url = self.config.get('base_url')
            kwargs = {'api_key': self.config.get('api_key')}
            if base_url:
                kwargs['base_url'] = base_url
            self.client = OpenAI(**kwargs)
            self.model = self.config.get('model', 'gpt-4-turbo-preview')
            logger.info(f"OpenAI客户端初始化成功，模型: {self.model}")
        except ImportError:
            logger.error("未安装openai包，请运行: pip install openai")
            raise

    def _init_zhipuai(self):
        """初始化智谱AI客户端"""
        try:
            from zhipuai import ZhipuAI
            self.client = ZhipuAI(api_key=self.config.get('api_key'))
            self.model = self.config.get('model', 'glm-4')
            logger.info(f"智谱AI客户端初始化成功，模型: {self.model}")
        except ImportError:
            logger.error("未安装zhipuai包，请运行: pip install zhipuai")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    async def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ) -> str:
        """
        完成一次对话

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            stream: 是否流式输出

        Returns:
            生成的文本
        """
        temp = temperature or self.temperature
        max_tok = max_tokens or self.max_tokens

        # 开始追踪
        trace_id = self.tracer.start_trace(
            LayerType.LLM_CLIENT,
            "complete",
            {
                "provider": self.provider,
                "model": self.model,
                "message_count": len(messages),
                "temperature": temp,
                "max_tokens": max_tok
            }
        )

        start_time = datetime.now()
        error = False
        retry_count = 0

        try:
            if self.provider in ['kimi', 'openai']:
                result = await self._call_openai_compatible(messages, temp, max_tok)
            elif self.provider == 'zhipuai':
                result = await self._call_zhipuai(messages, temp, max_tok)
            else:
                raise ValueError(f"不支持的提供商: {self.provider}")

            # 计算延迟
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            # 估算token数量 (简化估算: 中文字符数 + 英文单词数)
            prompt_text = "\n".join([m.get("content", "") for m in messages])
            prompt_tokens = len(prompt_text) // 4  # 粗略估算
            completion_tokens = len(result) // 4
            total_tokens = prompt_tokens + completion_tokens

            # 记录指标
            self.metrics.record_api_call(
                provider=self.provider,
                model=self.model,
                tokens=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=duration_ms,
                error=False,
                retry=retry_count > 0
            )

            # 结束追踪
            self.tracer.end_trace(
                trace_id,
                TraceStatus.COMPLETED,
                {
                    "duration_ms": duration_ms,
                    "tokens": total_tokens,
                    "result_length": len(result)
                }
            )

            return result

        except Exception as e:
            error = True
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            # 记录失败指标
            self.metrics.record_api_call(
                provider=self.provider,
                model=self.model,
                latency_ms=duration_ms,
                error=True,
                retry=retry_count > 0
            )

            # 结束追踪
            self.tracer.end_trace(
                trace_id,
                TraceStatus.FAILED,
                error=str(e)
            )

            logger.error(f"LLM调用失败: {e}")
            raise

    async def _call_openai_compatible(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int
    ) -> str:
        """调用OpenAI兼容API"""
        loop = asyncio.get_event_loop()

        def _call():
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content

        return await loop.run_in_executor(None, _call)

    async def _call_zhipuai(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int
    ) -> str:
        """调用智谱AI API"""
        loop = asyncio.get_event_loop()

        def _call():
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content

        return await loop.run_in_executor(None, _call)

    async def complete_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> AsyncIterator[str]:
        """流式输出"""
        temp = temperature or self.temperature
        max_tok = max_tokens or self.max_tokens

        loop = asyncio.get_event_loop()

        def _stream():
            if self.provider in ['kimi', 'openai']:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=max_tok,
                    stream=True
                )
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            elif self.provider == 'zhipuai':
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=max_tok,
                    stream=True
                )
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content

        # 将同步生成器转换为异步生成器
        import threading
        import queue

        result_queue = queue.Queue()

        def _producer():
            try:
                for chunk in _stream():
                    result_queue.put(chunk)
                result_queue.put(None)  # 结束标记
            except Exception as e:
                result_queue.put(e)

        thread = threading.Thread(target=_producer)
        thread.start()

        while True:
            try:
                item = await loop.run_in_executor(None, result_queue.get, True, 0.1)
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
            except queue.Empty:
                if not thread.is_alive():
                    break
                await asyncio.sleep(0.01)

    def build_system_prompt(self, style: WritingStyle, extra_context: str = "") -> str:
        """构建系统提示词"""
        import yaml
        from pathlib import Path

        # 加载风格配置
        style_file = Path(__file__).parent.parent / "config" / "styles.yaml"
        with open(style_file, "r", encoding="utf-8") as f:
            styles_config = yaml.safe_load(f)

        style_key = style.value
        style_config = styles_config.get("styles", {}).get(style_key, {})

        system_prompt = style_config.get("system_prompt", "")

        if extra_context:
            system_prompt += f"\n\n=== 额外上下文 ===\n{extra_context}"

        return system_prompt


# 便捷函数
def get_llm_client(provider: Optional[str] = None) -> LLMClient:
    """
    获取LLM客户端（自动处理配置）

    如果配置缺失，会自动暂停并引导用户输入
    """
    return LLMClient(provider=provider)
