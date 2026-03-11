"""
应用配置
使用 Pydantic Settings 管理配置
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    """应用配置"""
    
    # 服务配置
    app_name: str = "Agent Engine Service"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1  # worker 进程数量，生产环境建议设置为 CPU 核心数
    
    # 数据库配置
    database_url: str = "sqlite+aiosqlite:///:memory:"
    
    # 健康状态上报配置
    health_report_interval: int = 60  # 秒
    # 健康状态上报开关（默认关闭）
    health_reporter_enabled: bool = False
    
    # 自定义模型配置--用token和userid进行鉴权的模型--管理面界面上配置的时候当选择鉴权方式为userid的时候，model provider要配置成“userid”才能使用这个模型
    custom_auth_provider: str = "userid"

    # 日志配置
    log_level: str = "INFO"
    log_file: Optional[str] = None

    # LLM SSL 配置
    llm_ssl_verify: bool = False
    llm_ssl_cert: Optional[str] = None

    # LLM 代理配置
    llm_disable_proxy: bool = False
    llm_no_proxy: Optional[str] = None
    
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
