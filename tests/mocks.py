"""
测试用的Mock对象
用于隔离LLM依赖进行单元测试
"""
import json
from typing import List, Dict, Optional, AsyncIterator
from dataclasses import dataclass


@dataclass
class MockLLMResponse:
    """Mock LLM响应"""
    content: str
    model: str = "mock-model"


class MockLLM:
    """
    Mock LLM客户端
    用于测试时替代真实的LLM调用
    """
    
    def __init__(self, responses: Optional[Dict[str, str]] = None):
        """
        初始化Mock LLM
        
        Args:
            responses: 预设的响应字典 {prompt_key: response}
        """
        self.responses = responses or {}
        self.call_history = []
        self.default_response = "这是Mock生成的内容。基于提供的素材，传主在1980年代经历了重要转折。"
    
    def set_response(self, prompt_pattern: str, response: str):
        """设置特定prompt模式的响应"""
        self.responses[prompt_pattern] = response
    
    def set_default_response(self, response: str):
        """设置默认响应"""
        self.default_response = response
    
    def _match_response(self, messages: List[Dict]) -> str:
        """根据消息匹配响应"""
        prompt_text = json.dumps(messages, ensure_ascii=False)
        
        # 尝试匹配预设的响应
        for pattern, response in self.responses.items():
            if pattern in prompt_text:
                return response
        
        # 根据prompt内容生成智能响应
        if "大纲" in prompt_text or "outline" in prompt_text.lower():
            return self._generate_outline_response(messages)
        elif "审查" in prompt_text or "check" in prompt_text.lower():
            return self._generate_check_response(messages)
        elif "扩写" in prompt_text:
            return self._generate_expand_response(messages)
        else:
            return self.default_response
    
    def _generate_outline_response(self, messages: List[Dict]) -> str:
        """生成大纲响应"""
        return json.dumps({
            "title": "第一章：童年的记忆",
            "summary": "讲述传主1965-1978年间在陈家村度过的童年时光，包括饥饿记忆、家庭关系、关键事件。",
            "characters_present": ["陈国伟", "父亲陈大勇", "母亲李氏", "两个姐姐", "弟弟国梁"],
            "sections": [
                {
                    "title": "陈家村的日子",
                    "target_words": 2500,
                    "content_summary": "描述1965年陈国伟出生在佛山南海陈家村的背景，家庭成分问题带来的影响，以及村门口的河流。",
                    "emotional_tone": "怀旧、沉重",
                    "key_events": ["1965年出生", "爷爷是小地主"],
                    "time_location": "1965-1970年，佛山陈家村"
                },
                {
                    "title": "饥饿的记忆",
                    "target_words": 2500,
                    "content_summary": "讲述三年困难时期和文革初期的饥饿记忆，过年杀猪分油渣的细节，偷甘蔗被抓住的事件。",
                    "emotional_tone": "苦涩、温情",
                    "key_events": ["过年杀猪分油渣", "偷甘蔗被抓"],
                    "time_location": "1968-1976年，陈家村"
                }
            ]
        }, ensure_ascii=False)
    
    def _generate_check_response(self, messages: List[Dict]) -> str:
        """生成审查响应（默认无问题）"""
        return json.dumps([], ensure_ascii=False)
    
    def _generate_expand_response(self, messages: List[Dict]) -> str:
        """生成扩写响应"""
        return "扩写后的内容：在原有基础上增加了更多细节描写，包括环境氛围、人物动作、心理活动等。同时保留了所有原始事实信息。"
    
    async def complete(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> str:
        """模拟完成请求"""
        self.call_history.append({
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        })
        
        return self._match_response(messages)
    
    async def complete_stream(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
        **kwargs
    ) -> AsyncIterator[str]:
        """模拟流式完成"""
        response = await self.complete(messages, temperature)
        
        # 模拟流式输出，每次返回10个字符
        for i in range(0, len(response), 10):
            yield response[i:i+10]
    
    def get_call_count(self) -> int:
        """获取调用次数"""
        return len(self.call_history)
    
    def get_last_call(self) -> Optional[Dict]:
        """获取最后一次调用"""
        if self.call_history:
            return self.call_history[-1]
        return None
    
    def clear_history(self):
        """清空调用历史"""
        self.call_history = []


class MockVectorStore:
    """Mock向量存储"""
    
    def __init__(self, materials=None):
        self.materials = materials or []
    
    def search(self, query: str, n_results: int = 5):
        """模拟搜索"""
        # 简单的关键词匹配
        results = []
        for m in self.materials:
            score = 0.5  # 默认相似度
            if any(kw in m.content for kw in query.split()):
                score = 0.8
            results.append((m, score))
        
        # 按相似度排序
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:n_results]
    
    def add_materials(self, materials):
        """添加素材"""
        self.materials.extend(materials)


class MockContentGenerator:
    """Mock内容生成器 - 用于生成测试用的内容样本"""
    
    @staticmethod
    def generate_clean_content() -> str:
        """生成符合规范的优质内容"""
        return """
1965年，陈国伟出生在佛山南海的陈家村（来源：素材1）。那时候村里还没有电，晚上点的是煤油灯。

父亲陈大勇是个老实巴交的农民，因为爷爷以前是小地主，所以家里在村里是夹着尾巴做人的（来源：素材1）。

"我最盼望的就是过年杀猪，"陈国伟回忆道，"大队里分肉，那油渣刚炸出来，撒一点盐，是世界上最好吃的东西。"（来源：素材1）
"""
    
    @staticmethod
    def generate_content_with_placeholder() -> str:
        """生成包含占位符的问题内容"""
        return """
1965年，陈国伟出生在陈家村。他小时候家里很穷，经常吃不饱饭。

（此处需要补充更多童年细节，待后续完善）

1982年，他去了藤编厂工作。这段经历对他很重要。
"""
    
    @staticmethod
    def generate_content_with_templates() -> str:
        """生成包含模板套话的问题内容"""
        return """
晨光透过窗户洒进来，尘埃在光柱中飞舞。陈国伟端起茶杯，凉茶早已凉透，苦涩中带着回甘。

他陷入了沉思，回想着过去的岁月。时光荏苒，转眼间几十年过去了。

命运的齿轮悄然转动，暴风雨前的宁静中，真相正伺机而动。
"""
    
    @staticmethod
    def generate_content_with_vague_expressions() -> str:
        """生成包含空泛表述的问题内容"""
        return """
那是一个风云变幻、波澜壮阔的特殊年代。这段经历对陈国伟产生了深刻影响，意义重大。

众所周知，当时的社会环境很复杂，人们的生活都很不容易。值得一提的是，陈国伟表现出了坚韧不拔的品格。
"""
    
    @staticmethod
    def generate_content_no_substance() -> str:
        """生成缺乏实质内容的问题内容"""
        return """
陈国伟度过了难忘的时光。那段时间对他来说很重要。

他在那里生活了很久，经历了很多事情。这是一段值得铭记的岁月。

后来他又去了别的地方，继续他的生活。
"""
