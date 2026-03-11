"""
Echo Agent implementation
"""

import asyncio
from typing import Any, Dict, List

from loguru import logger

from src.core.base import BaseAgent, AgentRegistry
from src.models.schemas import AgentConfig, ContextContent, StreamChunk, StreamEventType, Trajectory, TrajectoryStep


@AgentRegistry.register("echo_agent")
class EchoAgent(BaseAgent):
    """
    Echo Agent
    简单的回显 Agent，会将输入原样返回，同时记录执行轨迹用于演示
    """

    def __init__(self, config: str):
        """初始化 EchoAgent"""
        super().__init__(config)

    async def invoke(
        self,
        input_data: Dict[str, Any],
        history: List[Dict] = None
    ) -> Any:
        """
        执行 Echo 任务
        """
        logger.info(f"EchoAgent 执行任务")

        # 获取输入内容（兼容 string 或 dict）
        query = input_data

        # 模拟处理过程
        await asyncio.sleep(0.1)


        # 构造响应
        query_content = query.get("content", str(query.get("query"))) if isinstance(query, dict) else str(query)
        response = {"role": "risk control agent", "content": f"Echo Agent 收到您的消息: {query_content}"}

        logger.info(f"EchoAgent 任务完成: {response}")

        # 构造上下文数据
        # Trajectory construction will access key 'content' so we need to ensure query is compatible or transformed
        if isinstance(query, dict):
             # Try to find content from common keys
             content_val = query.get("content") or query.get("query") or str(query)
             user_msg = {"role": "user", "content": content_val}
        else:
             user_msg = {"role": "user", "content": str(query)}

        output = [user_msg, response]
        return output

    async def execute_stream(
        self,
        user_id: str,
        session_id: str,
        input_data: Dict[str, Any],
        timeout: int = 300,
    ):
        """
        流式执行 Echo 任务，演示逐字输出效果
        """
        logger.info(f"EchoAgent 流式执行: user={user_id}, session={session_id}")

        query = input_data.get("query", input_data)
        if isinstance(query, dict):
            query_text = query.get("content", str(query))
        else:
            query_text = str(query)
        chunk_index = 0

        # 1. 开始
        yield StreamChunk(
            event=StreamEventType.START,
            data={"message": "Echo Agent 开始处理"},
            agent_id=self.agent_id,
            session_id=session_id,
            chunk_index=chunk_index,
        )
        chunk_index += 1

        await asyncio.sleep(0.05)

        # 2. 思考
        yield StreamChunk(
            event=StreamEventType.THINKING,
            data={"message": "正在处理..."},
            agent_id=self.agent_id,
            session_id=session_id,
            chunk_index=chunk_index,
        )
        chunk_index += 1

        await asyncio.sleep(0.05)

        # 3. 流式输出内容（逐字）
        response_text = f"Echo: {query_text}"
        for char in response_text:
            yield StreamChunk(
                event=StreamEventType.CONTENT,
                data={"text": char},
                agent_id=self.agent_id,
                session_id=session_id,
                chunk_index=chunk_index,
            )
            chunk_index += 1
            await asyncio.sleep(0.02)


        # 4. 完成
        final_result = {
            "echo": query,
            "agent_type_name": self.agent_type_name,
            "session_id": session_id,
            "message": response_text,
        }

        yield StreamChunk(
            event=StreamEventType.DONE,
            data={"message": "完成", "result": final_result},
            agent_id=self.agent_id,
            session_id=session_id,
            chunk_index=chunk_index,
        )

        logger.info(f"EchoAgent 流式任务完成")
