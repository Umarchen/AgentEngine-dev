"""
Pydantic 数据模型定义
包括 Agent 配置、任务请求响应、状态信息、轨迹信息等
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


# ==================== 流式响应相关 ====================

class StreamEventType(str, Enum):
    """流式事件类型"""
    START = "start"           # 开始处理
    THINKING = "thinking"     # 思考中
    CONTENT = "content"       # 内容块
    TOOL_CALL = "tool_call"   # 工具调用
    TOOL_RESULT = "tool_result"  # 工具结果
    ERROR = "error"           # 错误
    DONE = "done"             # 完成


class StreamChunk(BaseModel):
    """流式数据块模型"""
    event: StreamEventType = Field(..., description="事件类型")
    data: Any = Field(default=None, description="数据内容")
    agent_id: str = Field(..., description="Agent ID")
    session_id: str = Field(..., description="会话ID")
    chunk_index: int = Field(default=0, description="块序号")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")

    def to_sse(self) -> str:
        """转换为 Server-Sent Events 格式"""
        import json
        data = self.model_dump(mode="json")
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

# ================== AgentType配置信息 ====================

class AgentTypeConfig(BaseModel):
    """AgentType 配置信息模型"""
    agent_type_id: str = Field(..., description="AgentType唯一标识符")
    agent_type_name: str = Field(..., description="AgentType名称")
    agent_template_id: str = Field(default="", description="Agent配置模板ID")
    create_time: datetime = Field(default_factory=datetime.now, description="AgentType创建时间")
    update_time: datetime = Field(default_factory=datetime.now, description="AgentType更新时间")

# ================== Agent配置模板信息 ====================
class AgentTemplate(BaseModel):
    """Agent配置模板信息模型

    注意：Pydantic v2 使用 `model_config` 作为配置字段名，因此这里避免直接使用
    `model_config` 作为模型字段名，改为内部字段 `model_items`，同时通过 `alias` 保持
    与配置文件中的 key(`model_config`) 兼容。
    """

    agent_template_id: Optional[str] = Field(default="", description="Agent配置模板ID")
    agent_type_id: Optional[str] = Field(default="", description="Agent类型ID")
    agent_type_name: str = Field(..., description="Agent类型名称")
    model_items: List[Dict[str, Any]] = Field(
        default_factory=list,
        alias="model_config",
        description="模型配置信息",
    )
    prompt_config: List[Dict[str, Any]] = Field(default_factory=list, description="提示词配置信息")
    mcp_tool_config: List[Dict[str, Any]] = Field(default_factory=list, description="MCP工具配置信息")
    mcp_server_config: List[Dict[str, Any]] = Field(default_factory=list, description="MCP服务配置信息")
    create_time: Optional[datetime] = Field(default="", description="创建时间")
    update_time: Optional[datetime] = Field(default="", description="更新时间")

# ==================== Agent 配置信息 ====================

class AgentConfig(BaseModel):
    """Agent 配置信息模型，基于数据库表 `t_sys_agents_configs` 的字段定义。

    使用 `agent_type_id`（类型唯一标识符）和 `agent_type_name`（可读显示名称）两个字段描述 Agent 类型。
    """
    agent_config_id: str = Field(..., description="配置记录的主键ID")
    agent_id: str = Field(..., description="用于找到对应的agent，用于唯一标识来源")
    agent_type_id: str = Field(..., description="Agent类型唯一标识符（在DB中为 agent_type_id）")
    agent_type_name: str = Field(..., description="Agent显示名称（在DB中为 agent_type_name）")

    description: str = Field(default="", description="Agent功能描述")
    config_schema: Dict[str, Any] = Field(default_factory=dict, description="配置参数的JSON Schema定义")
    create_time: datetime = Field(default_factory=datetime.now, description="Agent类型注册时间")
    update_time: Optional[datetime] = Field(default=None, description="更新时间")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_config_id": "cfg-550e8400-e29b-41d4-a716-446655440000",
                "agent_id": "agent-550e8400-e29b-41d4-a716-446655440000",
                "agent_type_id": "uuid-echo-agent-550e8400-e29b-41d4",
                "agent_type_name": "echo_agent",
                "description": "一个简单的回显Agent",
                "config_schema": {},
                "create_time": "2026-01-20T10:00:00Z"
            }
        }
    )


# ==================== Agent 任务请求响应 ====================

class AgentTaskRequest(BaseModel):
    """Agent 任务请求模型"""
    agent_id: str = Field(..., description="用于找到对应的agent对象")
    user_id: str = Field(..., description="用户的唯一标识，用于鉴权、统计费率、隔离记忆")
    user_name: Optional[str] = Field(default=None, description="用户名称，用于展示或个性化处理")
    session_id: Optional[str] = Field(default=None, description="会话ID，如果传入Agent会加载该会话的历史记忆")
    input: Dict[str, Any] = Field(..., description="任务输入数据")
    timeout: int = Field(default=300, ge=1, le=3600, description="超时时间(秒)")
    stream: bool = Field(default=False, description="是否启用流式返回，启用后返回 SSE 格式的流式数据")
    session_ended: bool = Field(default=False, description="会话是否结束，用于触发会话结束后的处理逻辑（如评估任务）")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_id": "agent-550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user-12345",
                "user_name": "Alice",
                "session_id": "session-67890",
                "input": {"query": "请评估企业风险"},
                "timeout": 300,
                "stream": False,
                "session_ended": False
            }
        }
    )


class AgentTaskResponse(BaseModel):
    """Agent 任务响应模型"""
    success: bool = Field(..., description="任务是否成功")
    agent_id: str = Field(..., description="Agent包ID")
    session_id: str = Field(..., description="会话ID")
    output: Any = Field(default=None, description="任务输出结果")
    error: Optional[str] = Field(default=None, description="错误信息")
    execution_time: float = Field(default=0.0, description="执行时间(秒)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "agent_id": "agent-550e8400-e29b-41d4-a716-446655440000",
                "session_id": "session-67890",
                "output": "企业风险等级较高",
                "error": None,
                "execution_time": 1.5
            }
        }
    )


# ==================== Agent 健康状态信息 ====================

class HealthChecks(BaseModel):
    """健康检查详情"""
    alive: bool = Field(default=True, description="Agent是否存活")
    responsive: bool = Field(default=True, description="Agent是否响应")
    task_queue_healthy: bool = Field(default=True, description="任务队列是否健康")


class AgentHealthStatus(BaseModel):
    """Agent 健康状态模型"""
    agent_id: str = Field(..., description="Agent包ID")
    # 使用 agent_type_name 作为类型显示字段
    agent_type_name: str = Field(..., description="Agent类型名称（用于显示/注册表查找）")
    status: str = Field(default="healthy", description="状态: healthy, unhealthy, unknown")
    checks: HealthChecks = Field(default_factory=HealthChecks, description="健康检查详情")
    uptime_seconds: float = Field(default=0.0, description="运行时间(秒)")
    checked_at: datetime = Field(default_factory=datetime.now, description="检查时间")
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_id": "agent-550e8400-e29b-41d4-a716-446655440000",
                "agent_type_name": "echo_agent",
                "status": "healthy",
                "checks": {
                    "alive": True,
                    "responsive": True,
                    "task_queue_healthy": True
                },
                "uptime_seconds": 3600.5,
                "checked_at": "2026-01-20T11:30:00Z"
            }
        }
    )


# ==================== Agent 运行轨迹信息 ====================

class TrajectoryStep(BaseModel):
    """轨迹步骤模型"""
    role: str = Field(default=None, description="当前会话角色")
    content: str = Field(default=None, description="当前会话内容")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "role": "当前会话角色",
                "content": "当前会话内容"
            }
        }
    )


class Trajectory(BaseModel):
    """轨迹数据模型"""
    steps: List[TrajectoryStep] = Field(default_factory=list, description="轨迹步骤列表")


class AgentTrajectory(BaseModel):
    """Agent 运行轨迹信息模型"""
    agent_id: str = Field(..., description="Agent包ID")
    session_id: str = Field(..., description="会话ID")
    user_id: str = Field(..., description="用户ID")
    trajectory: Trajectory = Field(default_factory=Trajectory, description="轨迹信息")
    create_time: datetime = Field(default_factory=datetime.now, description="创建时间")
    update_time: datetime = Field(default_factory=datetime.now, description="更新时间")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_id": "agent-550e8400-e29b-41d4-a716-446655440000",
                "session_id": "agent-session-550e8400",
                "user_id": "user-12345",
                "trajectory": {
                    "steps": [
                        {
                            "role": "当前会话角色",
                            "content": "当前会话内容"
                        }
                    ]
                },
                "create_time": "2026-01-20T11:30:00Z",
                "update_time": "2026-01-20T11:30:00Z"
            }
        }
    )

# ==================== Agent 任务运行信息 ====================

class ContextContent(BaseModel):
    """上下文内容模型，包含多个上下文项"""
    context: List[Dict] = Field(default_factory=list, description="上下文项列表")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "context": [
                    {
                        "type": "user",
                        "content": "请评估风险"
                    },
                    {
                        "type": "assistant",
                        "content": "无风险"
                    }
                ]
            }
        }
    )

class AgentTask(BaseModel):
    """Agent Task信息"""
    task_id: str = Field(..., description="Agent执行任务ID")
    agent_id: str = Field(..., description="Agent ID")
    user_id: Optional[str] = Field(default=None, description="用户ID")
    session_id: str = Field(..., description="会话ID")
    task_status: Optional[str] = Field(default=None, description="Task任务执行结果")
    token_count: Optional[int] = Field(default=None, description="token数")
    create_time: datetime = Field(..., description="Task任务创建时间")
    context_content: ContextContent = Field(..., description="Context内容")
    update_time: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "task_id": "123e4567-e89b-12d3-a456-426614174000",
                "agent_id": "agent-001",
                "user_id": "user-12345",
                "session_id": "session-67890",
                "task_status": "completed",
                "token_count": 100,
                "create_time": "2023-10-01T12:00:00Z",
                "context_content": {"context":[{"type":"user","content":"请评估风险"},{"type":"assistant","content":"无风险"}]},
                "update_time": "2023-10-01T12:00:00Z"
            }
        }
    )

class SessionInfo(BaseModel):
    """会话信息模型"""
    session_id: str = Field(..., description="会话ID")
    agent_ids: List[str] = Field(default_factory=list, description="会话相关的所有Agent ID")
    user_ids: List[str] = Field(default_factory=list, description="会话相关的所有User ID")
    task_ids: List[str] = Field(default_factory=list, description="会话相关的所有Task ID")
    conversation_history: ContextContent = Field(..., description="历史对话信息")
    create_time: datetime = Field(..., description="创建时间")
    update_time: datetime = Field(..., description="更新时间")
    session_ended: bool = Field(..., description="会话是否结束")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "session_id": "session-123e4567-e89b-12d3-a456-426614174000",
                "agent_ids": ["agent-001", "agent-002"],
                "user_ids": ["user-12345", "user-67890"],
                "task_ids": ["task-1", "task-2"],
                "conversation_history": {"context":[{"type":"user","content":"请评估风险"},{"type":"assistant","content":"无风险"}]},
                "create_time": "2023-10-01T12:00:00Z",
                "update_time": "2023-10-01T12:00:00Z",
                "session_ended": False
            }
        }
    )
