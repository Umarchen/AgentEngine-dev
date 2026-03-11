"""
Agent 基类和动态注册机制
"""

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from loguru import logger

from src.models.schemas import (
    AgentConfig,
    AgentHealthStatus,
    ContextContent,
    HealthChecks,
    TrajectoryStep,
    Trajectory,
)


class AgentRegistry:
    """
    Agent 注册表
    用于动态注册和获取 Agent 类
    """
    
    _registry: Dict[str, Type["ABC"]] = {}
    
    @classmethod
    def register(cls, agent_type_name: str):
        """
        装饰器：注册 Agent 类
        
        Args:
            agent_type_name: Agent 类型标识符
            
        Usage:
            @AgentRegistry.register("echo")
            class EchoAgent(ABC):
                pass
        """
        def decorator(agent_class: Type["ABC"]):
            # 接口校验：确保 agent_class 实现了可调用的 `invoke` 方法（同步或异步）
            invoke_attr = getattr(agent_class, "invoke", None)
            if invoke_attr is None or not callable(invoke_attr):
                logger.error(
                    f"不能注册 Agent 类型 '{agent_type_name}': 类 {agent_class.__name__} 未实现可调用的 'invoke' 方法"
                )
                raise TypeError(
                    f"Agent class {agent_class.__name__} must implement a callable 'invoke' method to be registered as '{agent_type_name}'"
                )

            if agent_type_name in cls._registry:
                logger.warning(f"Agent类型 '{agent_type_name}' 已存在，将被覆盖")
            cls._registry[agent_type_name] = agent_class
            logger.info(f"Agent类型 '{agent_type_name}' 注册成功: {agent_class.__name__}")
            return agent_class
        return decorator
    
    @classmethod
    def get(cls, agent_type_name: str) -> Optional[Type["ABC"]]:
        """
        获取已注册的 Agent 类
        
        Args:
            agent_type_name: Agent 类型标识符
            
        Returns:
            Agent 类，如果不存在则返回 None
        """
        return cls._registry.get(agent_type_name)
    
    @classmethod
    def get_all(cls) -> Dict[str, Type["ABC"]]:
        """获取所有已注册的 Agent 类"""
        return cls._registry.copy()
    
    @classmethod
    def is_registered(cls, agent_type_name: str) -> bool:
        """检查 Agent 类型是否已注册"""
        return agent_type_name in cls._registry
    
    @classmethod
    def unregister(cls, agent_type_name: str) -> bool:
        """
        注销 Agent 类型
        
        Args:
            agent_type_name: Agent 类型标识符
            
        Returns:
            是否成功注销
        """
        if agent_type_name in cls._registry:
            del cls._registry[agent_type_name]
            logger.info(f"Agent类型 '{agent_type_name}' 已注销")
            return True
        return False


class BaseAgent(ABC):
    """
    Agent 基类
    所有 Agent 实现都应继承此类
    """
    
    def __init__(self, config: str):
        """
        初始化 Agent
        
        Args:
            config: Agent 配置信息
        """

        # 运行状态
        self._start_time = time.time()
        self._is_alive = True
        self._is_responsive = True
        self._task_queue_healthy = True
        self._current_task_count = 0

        # 内存/会话管理
        self._sessions: Dict[str, Dict[str, Any]] = {}

        logger.info(f"Agent 初始化完成)")
    
    @property
    def uptime_seconds(self) -> float:
        """获取运行时间（秒）"""
        return time.time() - self._start_time
    
    # ==================== 抽象方法 ====================
        
    async def execute_stream(
        self,
        user_id: str,
        session_id: str,
        input_data: Dict[str, Any],
        timeout: int = 300
    ):
        """
        流式执行 Agent 任务（异步生成器）
        
        子类可重写此方法实现自定义流式输出。
        默认实现会调用 execute() 并将结果作为单个块返回。
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            input_data: 任务输入数据
            timeout: 超时时间（秒）
            
        Yields:
            StreamChunk: 流式数据块
        """
        from src.models.schemas import StreamChunk, StreamEventType
        
        chunk_index = 0
        
        # 发送开始事件
        yield StreamChunk(
            event=StreamEventType.START,
            data={"message": "开始处理"},
            agent_id=self.agent_id,
            session_id=session_id,
            chunk_index=chunk_index
        )
        chunk_index += 1
        
        try:
            # 调用普通 execute 方法
            result = await self.execute(user_id, session_id, input_data, timeout)
            
            # 发送内容块
            yield StreamChunk(
                event=StreamEventType.CONTENT,
                data=result,
                agent_id=self.agent_id,
                session_id=session_id,
                chunk_index=chunk_index
            )
            chunk_index += 1
            
            # 发送完成事件
            yield StreamChunk(
                event=StreamEventType.DONE,
                data={"message": "处理完成", "result": result},
                agent_id=self.agent_id,
                session_id=session_id,
                chunk_index=chunk_index
            )
            
        except Exception as e:
            yield StreamChunk(
                event=StreamEventType.ERROR,
                data={"error": str(e)},
                session_id=session_id,
                chunk_index=chunk_index
            )
        
    # ==================== 会话管理 ====================
    
    def get_session(self, session_id: str) -> Dict[str, Any]:
        """
        获取或创建会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话数据
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "history": [],
                "memory": {},
                "created_at": datetime.now()
            }
        return self._sessions[session_id]
    
    def save_to_session(self, session_id: str, key: str, value: Any) -> None:
        """保存数据到会话"""
        session = self.get_session(session_id)
        session["memory"][key] = value
    
    def get_from_session(self, session_id: str, key: str, default: Any = None) -> Any:
        """从会话获取数据"""
        session = self.get_session(session_id)
        return session["memory"].get(key, default)
        
    # ==================== 健康状态 ====================

    
    async def _check_responsive(self) -> bool:
        """检查响应能力（子类可覆盖）"""
        return True
    
    # ==================== 生命周期 ====================
    
    async def start(self) -> None:
        """启动 Agent（子类可覆盖）"""
        logger.info(f"Agent 启动")
    
    async def stop(self) -> None:
        """停止 Agent（子类可覆盖）"""
        self._is_alive = False
        logger.info(f"Agent 停止")
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"