"""
传记生成状态机 - 工程化流程管理

状态流转：
INIT -> OUTLINE_GENERATING -> OUTLINE_REVIEWING -> OUTLINE_APPROVED
  -> CHAPTER_GENERATING -> CHAPTER_REVIEWING -> CHAPTER_APPROVED
  -> FINAL_REVIEWING -> FINAL_REVISION -> FINAL_APPROVED -> COMPLETED
  
错误处理：任何状态出错可进入 ERROR，支持从断点恢复
"""
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime
from pathlib import Path
import json


class GenerationState(Enum):
    """生成状态枚举"""
    INIT = "initialized"
    OUTLINE_GENERATING = "outline_generating"
    OUTLINE_REVIEWING = "outline_reviewing"
    OUTLINE_APPROVED = "outline_approved"
    CHAPTER_GENERATING = "chapter_generating"
    CHAPTER_REVIEWING = "chapter_reviewing"
    CHAPTER_APPROVED = "chapter_approved"
    FINAL_REVIEWING = "final_reviewing"
    FINAL_REVISION = "final_revision"
    FINAL_APPROVED = "final_approved"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class StateTransition:
    """状态转换记录"""
    from_state: GenerationState
    to_state: GenerationState
    timestamp: str
    reason: str
    metadata: Dict = field(default_factory=dict)


@dataclass  
class GenerationContext:
    """生成上下文"""
    project_id: str
    current_state: GenerationState = GenerationState.INIT
    current_chapter: int = 0
    total_chapters: int = 0
    completed_chapters: List[int] = field(default_factory=list)
    failed_chapters: List[int] = field(default_factory=list)
    error_count: int = 0
    max_errors: int = 3
    state_history: List[StateTransition] = field(default_factory=list)
    checkpoints: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "project_id": self.project_id,
            "current_state": self.current_state.value,
            "current_chapter": self.current_chapter,
            "total_chapters": self.total_chapters,
            "completed_chapters": self.completed_chapters,
            "failed_chapters": self.failed_chapters,
            "error_count": self.error_count,
            "state_history": [
                {
                    "from": t.from_state.value,
                    "to": t.to_state.value,
                    "timestamp": t.timestamp,
                    "reason": t.reason
                }
                for t in self.state_history
            ]
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "GenerationContext":
        return cls(
            project_id=data.get("project_id", ""),
            current_state=GenerationState(data.get("current_state", "initialized")),
            current_chapter=data.get("current_chapter", 0),
            total_chapters=data.get("total_chapters", 0),
            completed_chapters=data.get("completed_chapters", []),
            failed_chapters=data.get("failed_chapters", []),
            error_count=data.get("error_count", 0)
        )


class GenerationStateMachine:
    """生成状态机"""
    
    # 定义合法的状态转换
    VALID_TRANSITIONS = {
        GenerationState.INIT: [
            GenerationState.OUTLINE_GENERATING,
            GenerationState.ERROR
        ],
        GenerationState.OUTLINE_GENERATING: [
            GenerationState.OUTLINE_REVIEWING,
            GenerationState.ERROR
        ],
        GenerationState.OUTLINE_REVIEWING: [
            GenerationState.OUTLINE_APPROVED,
            GenerationState.OUTLINE_GENERATING,  # 重新生成
            GenerationState.ERROR
        ],
        GenerationState.OUTLINE_APPROVED: [
            GenerationState.CHAPTER_GENERATING,
            GenerationState.ERROR
        ],
        GenerationState.CHAPTER_GENERATING: [
            GenerationState.CHAPTER_REVIEWING,
            GenerationState.ERROR
        ],
        GenerationState.CHAPTER_REVIEWING: [
            GenerationState.CHAPTER_APPROVED,
            GenerationState.CHAPTER_GENERATING,  # 重新生成
            GenerationState.ERROR
        ],
        GenerationState.CHAPTER_APPROVED: [
            GenerationState.CHAPTER_GENERATING,  # 下一章
            GenerationState.FINAL_REVIEWING,      # 所有章节完成
            GenerationState.ERROR
        ],
        GenerationState.FINAL_REVIEWING: [
            GenerationState.FINAL_REVISION,
            GenerationState.FINAL_APPROVED,       # 无需修订
            GenerationState.ERROR
        ],
        GenerationState.FINAL_REVISION: [
            GenerationState.FINAL_REVIEWING,      # 重新审核
            GenerationState.FINAL_APPROVED,
            GenerationState.ERROR
        ],
        GenerationState.FINAL_APPROVED: [
            GenerationState.COMPLETED,
            GenerationState.ERROR
        ],
        GenerationState.ERROR: [
            GenerationState.INIT,                 # 重新开始
            GenerationState.OUTLINE_GENERATING,   # 从大纲开始
            GenerationState.CHAPTER_GENERATING    # 从当前章节继续
        ]
    }
    
    def __init__(self, context: GenerationContext, storage_path: Optional[Path] = None):
        self.context = context
        self.storage_path = storage_path
        self.state_handlers: Dict[GenerationState, Callable] = {}
        if storage_path:
            self._load_checkpoint()
    
    def register_handler(self, state: GenerationState, handler: Callable):
        """注册状态处理器"""
        self.state_handlers[state] = handler
    
    def can_transition(self, to_state: GenerationState) -> bool:
        """检查状态转换是否合法"""
        valid_states = self.VALID_TRANSITIONS.get(self.context.current_state, [])
        return to_state in valid_states
    
    def transition(self, to_state: GenerationState, reason: str = "", metadata: Dict = None):
        """执行状态转换"""
        if not self.can_transition(to_state):
            raise StateMachineError(
                f"非法状态转换: {self.context.current_state.value} -> {to_state.value}"
            )
        
        # 记录转换
        transition = StateTransition(
            from_state=self.context.current_state,
            to_state=to_state,
            timestamp=datetime.now().isoformat(),
            reason=reason,
            metadata=metadata or {}
        )
        self.context.state_history.append(transition)
        
        # 更新状态
        from_state = self.context.current_state
        self.context.current_state = to_state
        
        # 保存检查点
        self._save_checkpoint()
        
        print(f"[StateMachine] {from_state.value} -> {to_state.value}: {reason}")
    
    def run(self):
        """运行状态机"""
        while self.context.current_state != GenerationState.COMPLETED:
            state = self.context.current_state
            handler = self.state_handlers.get(state)
            
            if not handler:
                raise StateMachineError(f"状态 {state.value} 没有注册处理器")
            
            try:
                result = handler(self.context)
                
                # 根据结果决定下一步
                if result.get("success"):
                    next_state = result.get("next_state")
                    if next_state:
                        self.transition(next_state, result.get("reason", ""))
                else:
                    # 处理失败
                    self.context.error_count += 1
                    if self.context.error_count >= self.context.max_errors:
                        self.transition(GenerationState.ERROR, "错误次数超限")
                        break
                    else:
                        # 重试当前状态
                        print(f"[StateMachine] 错误，准备重试 ({self.context.error_count}/{self.context.max_errors})")
                        
            except Exception as e:
                print(f"[StateMachine] 状态处理异常: {e}")
                self.context.error_count += 1
                self.transition(GenerationState.ERROR, str(e))
                break
    
    def _save_checkpoint(self):
        """保存检查点"""
        if not self.storage_path:
            return
        checkpoint_file = self.storage_path / "checkpoint.json"
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(self.context.to_dict(), f, ensure_ascii=False, indent=2)
    
    def _load_checkpoint(self):
        """加载检查点"""
        if not self.storage_path:
            return
        checkpoint_file = self.storage_path / "checkpoint.json"
        if checkpoint_file.exists():
            try:
                with open(checkpoint_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 恢复上下文但不覆盖当前状态
                    self.context.completed_chapters = data.get("completed_chapters", [])
                    self.context.failed_chapters = data.get("failed_chapters", [])
                    self.context.error_count = data.get("error_count", 0)
            except Exception as e:
                print(f"[StateMachine] 加载检查点失败: {e}")


class StateMachineError(Exception):
    """状态机错误"""
    pass
