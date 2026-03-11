"""
FastAPI 应用实例
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from loguru import logger

from src.api.router import api_router
from src.config import Settings, get_settings

# 导入 agents 模块以触发 Agent 类的注册
import src.agents
from src.database.database import init_database, close_database
from src.core.config_manager import init_config_manager
from src.core.agent_manager import init_agent_manager
from src.services.health_reporter import init_health_reporter, stop_health_reporter
from src.services.skill_refresh_timer import init_skill_refresh_timer, stop_skill_refresh_timer
from src.skills.skillmgr import get_skill_manager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    应用生命周期管理
    处理启动和关闭事件
    """
    settings = get_settings()
    
    # ==================== 启动事件 ====================
    logger.info("正在启动 Agent Engine 服务...")
    
    try:
        # 1. 初始化数据库连接
        logger.info("初始化数据库连接...")
        db_manager = await init_database(settings.database_url)
        
        # 2. 初始化配置管理器
        logger.info("初始化配置管理器...")
        config_manager = await init_config_manager(db_manager)

        # 2.1 同步 Skill 可执行信息到数据库（t_skill_exe_info）
        skill_manager = get_skill_manager()
        await skill_manager.initialize()
        await skill_manager.sync_skill_execution_info()

        # 2.2 启动 Skill 增量刷新定时器（定期接收外部新增 skill）
        await init_skill_refresh_timer(skill_manager=skill_manager)
        
        # 3. 初始化 Agent 管理器
        logger.info("初始化 Agent 管理器...")
        agent_manager = await init_agent_manager(config_manager, db_manager)
        
        # 4. 启动健康状态上报服务（可通过配置关闭）
        health_reporter_started = False
        if getattr(settings, "health_reporter_enabled", False):
            logger.info("启动健康状态上报服务...")
            await init_health_reporter(
                agent_manager,
                db_manager,
                settings.health_report_interval
            )
            health_reporter_started = True
        else:
            logger.info("健康状态上报被配置为禁用，跳过启动")
        
        logger.info("Agent Engine 服务启动完成!")
        
    except Exception as e:
        logger.error(f"服务启动失败: {e}")
        raise
    
    yield
    
    # ==================== 关闭事件 ====================
    logger.info("正在关闭 Agent Engine 服务...")
    
    try:
        # 1. 停止健康状态上报服务（如果已启动）
        if getattr(settings, "health_reporter_enabled", False) and health_reporter_started:
            await stop_health_reporter()

        # 1.1 停止 Skill 增量刷新定时器
        await stop_skill_refresh_timer()
        
        # 2. 停止所有 Agent
        from src.core.agent_manager import get_agent_manager
        agent_manager = get_agent_manager()
        await agent_manager.stop_all_agents()
        
        # 3. 关闭数据库连接
        await close_database()
        
        logger.info("Agent Engine 服务已关闭")
        
    except Exception as e:
        logger.error(f"服务关闭时出错: {e}")


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用实例
    
    Returns:
        FastAPI 应用实例
    """
    settings = get_settings()
    
    app = FastAPI(
        title="Agent Engine Service",
        description="基于 FastAPI + Uvicorn 的 Agent 运行服务",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan
    )
    
    # 注册路由
    app.include_router(api_router, prefix="/api/v1", tags=["Agent API"])
    
    # 健康检查端点
    @app.get("/health", tags=["Health"])
    async def health_check():
        """服务健康检查"""
        return {"status": "healthy", "service": "Agent Engine"}
    
    # 根路径
    @app.get("/", tags=["Root"])
    async def root():
        """服务根路径"""
        return {
            "service": "Agent Engine Service",
            "version": "1.0.0",
            "docs": "/docs",
            "api": "/api/v1"
        }
    
    return app


# 创建应用实例
app = create_app()
