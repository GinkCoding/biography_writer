"""大模型客户端封装 - 支持多提供商和自动配置"""
import os
import asyncio
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, List, Dict, Any, Optional, Callable
from loguru import logger

from src.config import settings
from src.models import WritingStyle

# 导入可观测性模块
from src.observability import MetricsCollector
from src.observability.workflow_tracer import WorkflowTracer, LayerType, TraceStatus
from src.observability.runtime_monitor import get_runtime_monitor


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
        self.max_attempts = max(1, int(getattr(settings.retry, "max_attempts", 3)))
        self.backoff_factor = max(1, int(getattr(settings.retry, "backoff_factor", 2)))
        self.request_timeout_seconds = max(
            10,
            int(
                os.getenv(
                    "LLM_REQUEST_TIMEOUT_SECONDS",
                    str(getattr(settings.model, "request_timeout_seconds", 300)),
                )
            ),
        )
        self.heartbeat_interval_seconds = max(
            3,
            int(
                os.getenv(
                    "LLM_HEARTBEAT_INTERVAL_SECONDS",
                    str(getattr(settings.model, "heartbeat_interval_seconds", 10)),
                )
            ),
        )

        # 初始化可观测性组件
        self.metrics = MetricsCollector()
        self.tracer = WorkflowTracer()
        self.runtime_monitor = get_runtime_monitor(project_root=Path(__file__).parent.parent)
        self._progress_callback: Optional[Callable[[str], None]] = None

        # 初始化对应提供商的客户端
        self._init_client()

    def set_progress_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        """设置进度回调，用于CLI实时输出。"""
        self._progress_callback = callback

    def _notify_progress(self, message: str) -> None:
        logger.info(message)
        if self._progress_callback:
            try:
                self._progress_callback(message)
            except Exception:
                # 不允许回调异常影响主流程
                pass

    async def _wait_with_heartbeat(
        self,
        awaitable: "asyncio.Future[str]",
        attempt: int,
    ) -> str:
        """等待异步请求完成，并输出心跳日志。"""
        task = asyncio.ensure_future(awaitable)
        started = datetime.now()

        while True:
            elapsed = (datetime.now() - started).total_seconds()
            remaining = self.request_timeout_seconds - elapsed
            if remaining <= 0:
                task.cancel()
                timeout_msg = (
                    f"LLM请求超时: 已等待{int(elapsed)}秒 "
                    f"(timeout={self.request_timeout_seconds}s, attempt={attempt})"
                )
                self.runtime_monitor.log_event(
                    stage="llm",
                    status="failed",
                    message=timeout_msg,
                    metadata={"attempt": attempt},
                )
                raise TimeoutError(timeout_msg)

            wait_window = min(self.heartbeat_interval_seconds, remaining)
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=wait_window)
            except asyncio.TimeoutError:
                heartbeat_msg = (
                    f"LLM请求进行中... 已等待{int(elapsed)}秒 "
                    f"(attempt={attempt}/{self.max_attempts})"
                )
                self._notify_progress(heartbeat_msg)
                self.runtime_monitor.heartbeat(
                    stage="llm",
                    message=heartbeat_msg,
                    metadata={"attempt": attempt, "elapsed_seconds": int(elapsed)},
                )

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

        prompt_text = "\n".join([m.get("content", "") for m in messages])
        prompt_tokens = len(prompt_text) // 4  # 粗略估算
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_attempts + 1):
            trace_id = self.tracer.start_trace(
                LayerType.LLM_CLIENT,
                "complete",
                {
                    "provider": self.provider,
                    "model": self.model,
                    "message_count": len(messages),
                    "temperature": temp,
                    "max_tokens": max_tok,
                    "attempt": attempt,
                },
            )
            self.runtime_monitor.log_event(
                stage="llm",
                status="started",
                message=f"LLM调用开始 (attempt {attempt}/{self.max_attempts})",
                metadata={
                    "provider": self.provider,
                    "model": self.model,
                    "temperature": temp,
                    "max_tokens": max_tok,
                },
            )
            self._notify_progress(
                f"LLM请求已发送 (attempt {attempt}/{self.max_attempts}, provider={self.provider}, model={self.model})"
            )
            start_time = datetime.now()

            try:
                if self.provider in ["kimi", "openai"]:
                    result = await self._wait_with_heartbeat(
                        self._call_openai_compatible(messages, temp, max_tok),
                        attempt=attempt,
                    )
                elif self.provider == "zhipuai":
                    result = await self._wait_with_heartbeat(
                        self._call_zhipuai(messages, temp, max_tok),
                        attempt=attempt,
                    )
                else:
                    raise ValueError(f"不支持的提供商: {self.provider}")

                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                completion_tokens = len(result) // 4
                total_tokens = prompt_tokens + completion_tokens

                self.metrics.record_api_call(
                    provider=self.provider,
                    model=self.model,
                    tokens=total_tokens,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=duration_ms,
                    error=False,
                    retry=attempt > 1,
                )
                self.tracer.end_trace(
                    trace_id,
                    TraceStatus.COMPLETED,
                    {
                        "duration_ms": duration_ms,
                        "tokens": total_tokens,
                        "result_length": len(result),
                        "attempt": attempt,
                    },
                )
                self.runtime_monitor.log_event(
                    stage="llm",
                    status="completed",
                    message=f"LLM调用完成 (attempt {attempt})",
                    metadata={
                        "duration_ms": round(duration_ms, 2),
                        "tokens": total_tokens,
                    },
                )
                return result

            except Exception as e:
                last_error = e
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                self.metrics.record_api_call(
                    provider=self.provider,
                    model=self.model,
                    latency_ms=duration_ms,
                    error=True,
                    retry=attempt > 1,
                )
                self.tracer.end_trace(trace_id, TraceStatus.FAILED, error=str(e))
                self.runtime_monitor.log_event(
                    stage="llm",
                    status="failed",
                    message=f"LLM调用失败 (attempt {attempt}): {e}",
                    metadata={"duration_ms": round(duration_ms, 2)},
                )

                if attempt >= self.max_attempts:
                    logger.error(f"LLM调用失败: {e}")
                    raise

                backoff_seconds = min(10, self.backoff_factor ** attempt)
                self._notify_progress(
                    f"LLM调用失败，{backoff_seconds}s后自动重试 "
                    f"(attempt {attempt}/{self.max_attempts})"
                )
                await asyncio.sleep(backoff_seconds)

        if last_error:
            raise last_error
        raise RuntimeError("LLM调用失败")

    async def _call_openai_compatible(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int
    ) -> str:
        """调用OpenAI兼容API"""
        loop = asyncio.get_running_loop()

        def _call():
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            try:
                response = self.client.chat.completions.create(
                    **kwargs,
                    timeout=self.request_timeout_seconds,
                )
            except TypeError:
                # 兼容不支持timeout参数的SDK版本
                response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content

        return await loop.run_in_executor(None, _call)

    async def _call_zhipuai(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int
    ) -> str:
        """调用智谱AI API"""
        loop = asyncio.get_running_loop()

        def _call():
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            try:
                response = self.client.chat.completions.create(
                    **kwargs,
                    timeout=self.request_timeout_seconds,
                )
            except TypeError:
                response = self.client.chat.completions.create(**kwargs)
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
