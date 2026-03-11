"""
FastAPI 路由定义
"""

from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from loguru import logger
import uuid

from src.models.schemas import (
    AgentConfig,
    AgentTaskRequest,
    AgentTaskResponse,
    AgentHealthStatus,
    AgentTrajectory,
)
from src.models.evaluation_schemas import (
    EvaluationRequest,
    EvaluationResponse,
    TrajectoryEvaluationRecord,
)
from src.core.agent_manager import get_agent_manager
from src.core.config_manager import get_config_manager
from src.database.database import get_database_manager
from src.services.health_reporter import get_health_reporter
from src.services.evaluation import get_trajectory_evaluator
from src.skills.skillmgr import get_skill_manager


# 创建主路由
api_router = APIRouter()


# ==================== Agent 任务执行接口 ====================

@api_router.post(
    "/agent/execute",
    summary="执行 Agent 任务",
    description="执行 Agent 任务，支持普通返回和流式返回。通过 stream 参数控制：stream=false 返回 JSON，stream=true 返回 SSE 流",
    responses={
        200: {
            "description": "成功响应",
            "content": {
                "application/json": {
                    "description": "stream=false 时返回 JSON"
                },
                "text/event-stream": {
                    "description": "stream=true 时返回 SSE 流"
                }
            }
        }
    }
)
async def execute_agent_task(request: AgentTaskRequest):
    """
    执行 Agent 任务
    
    - stream=false (默认): 返回完整的 JSON 响应
    - stream=true: 返回 Server-Sent Events (SSE) 流式响应
    """
    logger.info(f"收到 Agent 任务请求: agent_id={request.agent_id}, user_id={request.user_id}, stream={request.stream}, session_ended={request.session_ended}")
    # 如果请求中没有 session_id，则在接收时生成一个 UUID 并写入到请求对象中，
    # 以便后续处理/日志/流式响应可以统一使用同一 session_id。
    if not getattr(request, "session_id", None):
        new_sid = str(uuid.uuid4())
        request.session_id = new_sid
    
    agent_manager = get_agent_manager()
    
    # 根据 stream 参数决定返回方式
    if request.stream:
        # 流式返回
        async def generate():
            async for chunk in agent_manager.execute_task_stream(request):
                yield chunk.to_sse()
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    else:
        # 普通返回
        response = await agent_manager.execute_task(request)
        
        if not response.success:
            logger.warning(f"Agent 任务执行失败: {response.error}")
        else:
            logger.info(f"Agent 任务执行成功: agent_id={request.agent_id}")
        
        return response


# ==================== Agent 配置管理接口 ====================

@api_router.get(
    "/agent/configs",
    response_model=List[AgentConfig],
    summary="获取所有 Agent 配置",
    description="获取所有已加载的 Agent 配置信息"
)
async def get_all_configs() -> List[AgentConfig]:
    """获取所有 Agent 配置"""
    config_manager = get_config_manager()
    return await config_manager.get_all_configs()


@api_router.get(
    "/agent/config/{agent_id}",
    response_model=AgentConfig,
    summary="获取指定 Agent 配置",
    description="根据 agent_id 获取指定的 Agent 配置信息"
)
async def get_config(agent_id: str) -> AgentConfig:
    """获取指定 Agent 配置"""
    config_manager = get_config_manager()
    config = await config_manager.get_config(agent_id)
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"配置不存在: {agent_id}"
        )
    
    return config


@api_router.post(
    "/agent/config",
    response_model=Dict[str, Any],
    summary="添加 Agent 配置",
    description="添加或更新 Agent 配置信息"
)
async def add_config(config: AgentConfig) -> Dict[str, Any]:
    """添加或更新 Agent 配置"""
    config_manager = get_config_manager()
    success = await config_manager.add_config(config)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="添加配置失败"
        )
    
    return {"success": True, "message": f"配置已添加: {config.agent_id}"}


@api_router.delete(
    "/agent/config/{agent_id}",
    response_model=Dict[str, Any],
    summary="删除 Agent 配置",
    description="删除指定的 Agent 配置信息"
)
async def remove_config(agent_id: str) -> Dict[str, Any]:
    """删除 Agent 配置"""
    config_manager = get_config_manager()
    success = await config_manager.remove_config(agent_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除配置失败"
        )
    
    return {"success": True, "message": f"配置已删除: {agent_id}"}


# ==================== Agent 健康状态接口 ====================

@api_router.get(
    "/agent/health",
    response_model=List[AgentHealthStatus],
    summary="获取所有 Agent 健康状态",
    description="获取所有活跃 Agent 的健康状态信息"
)
async def get_all_agents_health() -> List[AgentHealthStatus]:
    """获取所有 Agent 健康状态"""
    agent_manager = get_agent_manager()
    return await agent_manager.get_all_agents_health()


@api_router.get(
    "/agent/health/{agent_id}",
    response_model=AgentHealthStatus,
    summary="获取指定 Agent 健康状态",
    description="根据 agent_id 获取指定 Agent 的健康状态"
)
async def get_agent_health(agent_id: str) -> AgentHealthStatus:
    """获取指定 Agent 健康状态"""
    agent_manager = get_agent_manager()
    health = await agent_manager.get_agent_health(agent_id)
    
    if not health:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent 不存在: {agent_id}"
        )
    
    return health


# ==================== Agent 管理接口 ====================

@api_router.get(
    "/agent/list",
    response_model=List[str],
    summary="获取活跃 Agent 列表",
    description="获取所有已创建的 Agent 的 agent_id 列表"
)
async def get_agent_list() -> List[str]:
    """获取活跃 Agent 列表"""
    agent_manager = get_agent_manager()
    return agent_manager.get_all_agent_ids()


@api_router.post(
    "/agent/stop/{agent_id}",
    response_model=Dict[str, Any],
    summary="停止指定 Agent",
    description="停止并移除指定的 Agent"
)
async def stop_agent(agent_id: str) -> Dict[str, Any]:
    """停止指定 Agent"""
    agent_manager = get_agent_manager()
    success = await agent_manager.stop_agent(agent_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent 不存在或停止失败: {agent_id}"
        )
    
    return {"success": True, "message": f"Agent 已停止: {agent_id}"}


@api_router.post(
    "/agent/restart/{agent_id}",
    response_model=Dict[str, Any],
    summary="重启指定 Agent",
    description="重启指定的 Agent"
)
async def restart_agent(agent_id: str) -> Dict[str, Any]:
    """重启指定 Agent"""
    agent_manager = get_agent_manager()
    agent = await agent_manager.restart_agent(agent_id)
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent 重启失败: {agent_id}"
        )
    
    return {"success": True, "message": f"Agent 已重启: {agent_id}"}


# ==================== 轨迹查询接口 ====================

@api_router.get(
    "/agent/trajectories",
    response_model=List[AgentTrajectory],
    summary="获取 Agent 轨迹历史",
    description="获取 Agent 运行轨迹历史记录"
)
async def get_trajectories(
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 100
) -> List[AgentTrajectory]:
    """获取 Agent 轨迹历史"""
    db_manager = get_database_manager()
    return await db_manager.get_trajectory_history(
        agent_id=agent_id,
        session_id=session_id,
        limit=limit
    )


# ==================== 服务状态接口 ====================

@api_router.get(
    "/service/status",
    response_model=Dict[str, Any],
    summary="获取服务状态",
    description="获取服务整体运行状态"
)
async def get_service_status() -> Dict[str, Any]:
    """获取服务状态"""
    agent_manager = get_agent_manager()
    config_manager = get_config_manager()
    health_reporter = get_health_reporter()
    db_manager = get_database_manager()
    
    return {
        "status": "running",
        "agent_count": agent_manager.get_agent_count(),
        "config_count": config_manager.get_config_count(),
        "health_reporter_running": health_reporter.is_running,
        "database_connected": db_manager.is_connected
    }


@api_router.post(
    "/service/health-report",
    response_model=Dict[str, Any],
    summary="触发健康状态上报",
    description="立即触发一次健康状态上报"
)
async def trigger_health_report() -> Dict[str, Any]:
    """触发健康状态上报"""
    health_reporter = get_health_reporter()
    await health_reporter.report_now()
    return {"success": True, "message": "健康状态上报已触发"}


@api_router.post(
    "/service/skills-refresh",
    response_model=Dict[str, Any],
    summary="手工触发 Skill 增量刷新",
    description="立即触发一次 Skill 增量刷新（内存、registry.json、t_skill_exe_info 同步）"
)
async def trigger_skills_refresh() -> Dict[str, Any]:
    """手工触发 Skill 增量刷新"""
    skill_manager = get_skill_manager()
    stats = await skill_manager.refresh_skills_incremental()
    return {
        "success": True,
        "message": "Skill 增量刷新已触发",
        "stats": stats,
    }


# ==================== 轨迹评估接口 ====================

@api_router.post(
    "/evaluation/notify",
    response_model=Dict[str, Any],
    summary="通知轨迹已就绪（异步）",
    description="通知评估器轨迹已写入数据库，触发后台评估任务。接口立即返回，评估在后台进行。"
)
async def notify_trajectory_ready(request: EvaluationRequest) -> Dict[str, Any]:
    """
    通知轨迹已就绪（推荐接口）
    
    这是提供给其他组件调用的通知接口。
    其他组件在轨迹写入数据库完成后，调用此接口通知评估器。
    
    接口特点：
    1. 立即返回，不等待评估完成
    2. 评估在后台异步进行
    3. 评估结果写入 T_AGENT_TRAJECTORY_EVALUATION 表
    4. 其他组件通过查询该表获取评估结果
    """
    logger.info(
        f"收到轨迹就绪通知 - agent_id: {request.agent_id}, "
        f"user_id: {request.user_id}, session_id: {request.session_id}"
    )
    
    evaluator = get_trajectory_evaluator()
    
    response = await evaluator.notify_trajectory_ready(
        agent_id=request.agent_id,
        user_id=request.user_id,
        session_id=request.session_id,
        force_reevaluate=request.force_reevaluate
    )
    
    return response


@api_router.post(
    "/evaluation/evaluate",
    response_model=EvaluationResponse,
    summary="评估智能体轨迹（同步）",
    description="对指定的智能体轨迹进行评估和打分，等待评估完成后返回结果"
)
async def evaluate_trajectory(request: EvaluationRequest) -> EvaluationResponse:
    """
    评估智能体轨迹（同步接口）
    
    此接口会等待评估完成后返回结果。
    如果只需要通知评估器开始评估，推荐使用 /evaluation/notify 接口。
    """
    logger.info(
        f"收到轨迹评估请求 - agent_id: {request.agent_id}, "
        f"user_id: {request.user_id}, session_id: {request.session_id}"
    )
    
    evaluator = get_trajectory_evaluator()
    
    response = await evaluator.evaluate_trajectory(
        agent_id=request.agent_id,
        user_id=request.user_id,
        session_id=request.session_id,
        force_reevaluate=request.force_reevaluate
    )
    
    return response


@api_router.get(
    "/evaluation/result/{evaluation_id}",
    response_model=TrajectoryEvaluationRecord,
    summary="获取评估结果",
    description="根据评估记录 ID 获取评估结果"
)
async def get_evaluation_result(evaluation_id: int) -> TrajectoryEvaluationRecord:
    """获取指定的评估结果"""
    db_manager = get_database_manager()
    
    result = await db_manager.get_trajectory_evaluation(evaluation_id=evaluation_id)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"评估结果不存在: {evaluation_id}"
        )
    
    return result


@api_router.get(
    "/evaluation/results",
    response_model=List[TrajectoryEvaluationRecord],
    summary="查询评估结果列表",
    description="根据条件查询评估结果列表"
)
async def get_evaluation_results(
    agent_id: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 100
) -> List[TrajectoryEvaluationRecord]:
    """查询评估结果列表"""
    db_manager = get_database_manager()
    
    results = await db_manager.get_trajectory_evaluations(
        agent_id=agent_id,
        user_id=user_id,
        session_id=session_id,
        limit=limit
    )
    
    return results
