"""
Agent Engine Service 主入口
使用 Uvicorn 运行 FastAPI 应用
"""


import sys
import asyncio
import uvicorn
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

from src.config import get_settings
from openjiuwen.core.foundation.llm.model import _CLIENT_TYPE_REGISTRY
from src.core.custom_auth_model import CustomAuthModel
from src.skills.skillmgr import init_skill_manager


def register_custom_models() -> None:
    """注册自定义模型"""
    settings = get_settings()
    _CLIENT_TYPE_REGISTRY[settings.custom_auth_provider] = CustomAuthModel
    logger.info(f"已注册 CustomAuthModel 到 openjiuwen _CLIENT_TYPE_REGISTRY，provider='{settings.custom_auth_provider}'")


def setup_logging() -> None:
    """配置日志"""
    settings = get_settings()
    
    # 移除默认的 logger
    logger.remove()
    
    # 添加控制台输出
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
               "<level>{message}</level>"
    )
    
    # 如果配置了日志文件，添加文件输出
    if settings.log_file:
        logger.add(
            settings.log_file,
            level=settings.log_level,
            rotation="100 MB",
            retention="7 days",
            compression="gz"
        )


def main() -> None:
    """主入口函数"""
    # 配置日志
    setup_logging()
    
    settings = get_settings()
    
    logger.info(f"启动 {settings.app_name}...")
    logger.info(f"监听地址: {settings.host}:{settings.port}")
    logger.info(f"调试模式: {settings.debug}")
    logger.info(f"Worker 数量: {settings.workers}")
    
    # 注册自定义模型
    register_custom_models()

    # 初始化 Skill 管理器（扫描并加载可用 skills 索引）
    asyncio.run(init_skill_manager())
    logger.info("SkillMgr 已完成启动初始化")
    
    # 运行服务
    # 注意：reload=True 时不支持多 worker，会自动忽略 workers 参数
    uvicorn.run(
        "src.app:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers if not settings.debug else 1,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )


if __name__ == "__main__":
    main()
