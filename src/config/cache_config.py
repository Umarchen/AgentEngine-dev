"""
Redis 缓存配置模块
定义缓存相关的配置参数

对应需求：
- [REQ_REDIS_CACHE_002] 熔断器机制
- [REQ_REDIS_CACHE_004] 缓存预热功能
- [REQ_REDIS_CACHE_005] 本地缓存优化
"""

from typing import Optional
from pydantic import BaseModel, Field


class LocalCacheConfig(BaseModel):
    """
    本地缓存配置
    
    对应需求：[REQ_REDIS_CACHE_005]
    """
    
    # 是否启用本地缓存
    enabled: bool = Field(
        default=True,
        description="是否启用本地缓存（L1）"
    )
    
    # 最大容量
    maxsize: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="本地缓存最大容量（LRU 淘汰）"
    )
    
    # 过期时间（秒）
    ttl: float = Field(
        default=300.0,
        ge=60.0,
        le=3600.0,
        description="本地缓存 TTL（秒）"
    )


class CircuitBreakerConfig(BaseModel):
    """
    熔断器配置
    
    对应需求：[REQ_REDIS_CACHE_002]
    """
    
    # 错误率阈值（%）
    error_threshold_percent: float = Field(
        default=50.0,
        ge=10.0,
        le=90.0,
        description="错误率阈值，超过此值触发熔断"
    )
    
    # 统计时间窗口（秒）
    time_window_seconds: float = Field(
        default=10.0,
        ge=5.0,
        le=60.0,
        description="统计时间窗口大小"
    )
    
    # 恢复超时（秒）
    recovery_timeout_seconds: float = Field(
        default=30.0,
        ge=10.0,
        le=120.0,
        description="熔断后多久尝试恢复"
    )
    
    # 半开状态最大试探次数
    half_open_max_calls: int = Field(
        default=3,
        ge=1,
        le=10,
        description="半开状态最大试探次数"
    )


class WarmupConfig(BaseModel):
    """
    缓存预热配置
    
    对应需求：[REQ_REDIS_CACHE_004]
    """
    
    # 是否启用预热
    enabled: bool = Field(
        default=True,
        description="是否启用启动时自动预热"
    )
    
    # 预热延迟（秒）
    delay_seconds: int = Field(
        default=30,
        ge=0,
        le=300,
        description="启动后延迟多久开始预热"
    )
    
    # 预热 Top N
    top_n: int = Field(
        default=10,
        ge=1,
        le=100,
        description="预热 Top N 高频 Agent"
    )


class BatchOperationConfig(BaseModel):
    """
    批量操作配置
    
    对应需求：[REQ_REDIS_CACHE_006]
    """
    
    # 批量操作最大大小
    max_batch_size: int = Field(
        default=100,
        ge=10,
        le=500,
        description="单次批量操作最大数量"
    )


class RedisCacheConfig(BaseModel):
    """
    Redis 缓存总配置
    """
    
    # 本地缓存配置
    local_cache: LocalCacheConfig = Field(
        default_factory=LocalCacheConfig
    )
    
    # 熔断器配置
    circuit_breaker: CircuitBreakerConfig = Field(
        default_factory=CircuitBreakerConfig
    )
    
    # 预热配置
    warmup: WarmupConfig = Field(
        default_factory=WarmupConfig
    )
    
    # 批量操作配置
    batch: BatchOperationConfig = Field(
        default_factory=BatchOperationConfig
    )
    
    # Redis TTL（秒）
    redis_ttl: int = Field(
        default=3600,
        ge=300,
        le=86400,
        description="Redis 缓存默认 TTL"
    )
    
    # 是否启用监控指标
    enable_metrics: bool = Field(
        default=True,
        description="是否启用 Prometheus 监控指标"
    )


# ==================== 环境变量映射 ====================

# 这些配置可以通过环境变量覆盖
ENV_VAR_MAPPING = {
    # 本地缓存
    "CACHE_L1_ENABLED": ("local_cache", "enabled"),
    "CACHE_L1_MAXSIZE": ("local_cache", "maxsize"),
    "CACHE_L1_TTL": ("local_cache", "ttl"),
    
    # 熔断器
    "CIRCUIT_BREAKER_ERROR_THRESHOLD": ("circuit_breaker", "error_threshold_percent"),
    "CIRCUIT_BREAKER_TIME_WINDOW": ("circuit_breaker", "time_window_seconds"),
    "CIRCUIT_BREAKER_RECOVERY_TIMEOUT": ("circuit_breaker", "recovery_timeout_seconds"),
    
    # 预热
    "CACHE_WARMUP_ENABLED": ("warmup", "enabled"),
    "CACHE_WARMUP_DELAY": ("warmup", "delay_seconds"),
    "CACHE_WARMUP_TOP_N": ("warmup", "top_n"),
    
    # 批量操作
    "CACHE_BATCH_SIZE": ("batch", "max_batch_size"),
    
    # 通用
    "CACHE_REDIS_TTL": ("redis_ttl",),
    "CACHE_ENABLE_METRICS": ("enable_metrics",),
}


def load_config_from_env() -> RedisCacheConfig:
    """
    从环境变量加载配置
    
    Returns:
        配置对象
    """
    import os
    
    config_dict = RedisCacheConfig().model_dump()
    
    for env_var, path in ENV_VAR_MAPPING.items():
        value = os.environ.get(env_var)
        if value is not None:
            # 导航到配置层级
            current = config_dict
            for key in path[:-1]:
                current = current.get(key, {})
            
            # 类型转换
            key = path[-1]
            if isinstance(current.get(key), bool):
                current[key] = value.lower() in ("true", "1", "yes")
            elif isinstance(current.get(key), int):
                current[key] = int(value)
            elif isinstance(current.get(key), float):
                current[key] = float(value)
            else:
                current[key] = value
    
    return RedisCacheConfig(**config_dict)


# 默认配置实例
default_config = RedisCacheConfig()
