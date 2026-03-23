"""LLM 客户端"""
import os
import asyncio
from typing import Optional
from dataclasses import dataclass
import yaml
from pathlib import Path


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str = "tencent"
    model: str = "glm-5"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: int = 4096  # 增加到 4096
    temperature: float = 0.7
    
    def __post_init__(self):
        # 从配置文件加载
        config_path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                model_config = config.get('model', {})
                self.api_key = self.api_key or model_config.get('api_key')
                self.base_url = self.base_url or model_config.get('base_url')
                self.model = self.model or model_config.get('model', 'glm-5')
                self.max_tokens = model_config.get('max_tokens', 4096)
                self.temperature = model_config.get('temperature', 0.7)
        
        # 从环境变量覆盖
        if not self.api_key:
            self.api_key = os.getenv("MODEL_API_KEY") or os.getenv("OPENAI_API_KEY")


class LLMClient:
    """LLM 客户端"""
    
    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
    
    async def complete(
        self, 
        messages: list, 
        temperature: float = None,
        max_tokens: int = None,
        timeout: int = 300
    ) -> str:
        """调用 LLM"""
        import openai
        
        client = openai.AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url
        )
        
        # GLM-5 需要更大的 max_tokens
        actual_max_tokens = max_tokens or self.config.max_tokens
        if actual_max_tokens < 2000:
            actual_max_tokens = 2000
        
        response = await client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=temperature or self.config.temperature,
            max_tokens=actual_max_tokens,
            timeout=timeout
        )
        
        # GLM-5 可能返回 reasoning_content 而不是 content
        content = response.choices[0].message.content
        
        # 如果 content 为空，尝试使用 reasoning_content
        if not content:
            reasoning = getattr(response.choices[0].message, 'reasoning_content', None)
            if reasoning:
                # reasoning_content 可能包含思考过程 + 最终答案
                # 尝试提取最后的JSON部分
                content = self._extract_final_answer(reasoning)
        
        return content or ""
    
    def _extract_final_answer(self, reasoning: str) -> str:
        """从 reasoning_content 中提取最终答案"""
        # 方法1：查找JSON块
        import re
        json_match = re.search(r'\{[\s\S]*\}', reasoning)
        if json_match:
            return json_match.group()
        
        # 方法2：查找markdown代码块
        code_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', reasoning)
        if code_match:
            return code_match.group(1)
        
        # 方法3：返回最后一段
        paragraphs = reasoning.strip().split('\n\n')
        if paragraphs:
            return paragraphs[-1]
        
        return reasoning
    
    async def complete_with_thinking(
        self,
        messages: list,
        temperature: float = None,
        max_tokens: int = None,
        timeout: int = 600
    ) -> tuple[str, str]:
        """调用 LLM（带思考模式）"""
        # 添加思考提示
        enhanced_messages = messages.copy()
        if enhanced_messages[-1]["role"] == "user":
            enhanced_messages[-1]["content"] += "\n\n请先深入思考，然后给出详细的回复。"
        
        response = await self.complete(
            enhanced_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout
        )
        
        # 简单分离思考和回复（如果模型遵循格式）
        if "<thinkings>" in response and "</thinkings>" in response:
            thinking = response.split("<thinkings>")[1].split("</thinkings>")[0].strip()
            content = response.split("</thinkings>")[1].strip()
        else:
            thinking = ""
            content = response
        
        return thinking, content
