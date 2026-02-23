"""大模型客户端封装 - 使用Kimi直接调用"""
import asyncio
from typing import AsyncIterator, List, Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

from src.config import settings
from src.models import WritingStyle


class LLMClient:
    """使用Kimi作为底层模型的客户端"""
    
    def __init__(self):
        # 不再调用外部API，而是通过 MCP 工具调用当前Kimi
        self.provider = "kimi"
        self.max_tokens = settings.model.max_tokens
        self.temperature = settings.model.temperature
    
    async def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ) -> str:
        """完成一次对话 - 实际通过调用自己实现"""
        # 构建完整提示词
        prompt = self._build_prompt(messages)
        
        try:
            # 通过模拟方式返回结果
            # 实际运行时，这个调用会被外层系统拦截并交由Kimi处理
            response = await self._call_kimi(prompt, temperature or self.temperature)
            return response
        except Exception as e:
            logger.error(f"调用失败: {e}")
            raise
    
    async def complete_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> AsyncIterator[str]:
        """流式输出 - 非流式模式模拟"""
        content = await self.complete(messages, temperature, max_tokens)
        # 模拟流式，每次返回一部分
        chunk_size = 50
        for i in range(0, len(content), chunk_size):
            yield content[i:i+chunk_size]
            await asyncio.sleep(0.01)
    
    def _build_prompt(self, messages: List[Dict[str, str]]) -> str:
        """将messages转换为单一提示词"""
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append(f"【系统指令】\n{content}\n")
            elif role == "user":
                parts.append(f"【用户】\n{content}\n")
            elif role == "assistant":
                parts.append(f"【助手】\n{content}\n")
        return "\n".join(parts)
    
    async def _call_kimi(self, prompt: str, temperature: float) -> str:
        """
        调用Kimi - 这个函数在独立运行时会使用stdin/stdout通信
        在实际MCP环境中，请求会被路由到Kimi
        """
        # 检查是否有MCP上下文（通过检测特殊环境变量）
        import os
        
        if os.getenv("MCP_CONTEXT"):
            # 在MCP环境中，直接返回一个标记，外层会处理
            return f"<MCP_CALL>{prompt}</MCP_CALL>"
        
        # 独立运行模式：通过subprocess调用kimi-cli
        # 或者返回提示用户需要手动输入
        return self._interactive_mode(prompt)
    
    def _interactive_mode(self, prompt: str) -> str:
        """交互模式 - 提示用户手动处理"""
        logger.info("=" * 60)
        logger.info("请复制以下提示词到Kimi对话框，然后将回复粘贴回来：")
        logger.info("=" * 60)
        print("\n" + prompt + "\n")
        logger.info("=" * 60)
        
        # 读取用户输入作为响应
        print("\n请输入Kimi的回复（输入EOF结束）：\n")
        lines = []
        try:
            while True:
                line = input()
                lines.append(line)
        except EOFError:
            pass
        
        return "\n".join(lines)
    
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


from pathlib import Path