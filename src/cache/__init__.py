"""
缓存模块
提供 Redis 缓存功能
"""

from .constants import (
    CacheKeys,
    CacheTTL,
    CacheConfig,
    CACHE_NAMESPACES,
)
from .key_builder import CacheKeyBuilder
from .serializer import CacheSerializer, default_serializer
from .redis_client import (
    RedisClient,
    RedisConfig,
    get_redis_client,
    close_redis_client,
)
from .cache_manager import (
    CacheManager,
    get_cache_manager,
    set_cache_manager,
)
from .metrics import (
    CacheMetrics,
    MetricsContext,
)


__all__ = [
    # 常量
    "CacheKeys",
    "CacheTTL",
    "CacheConfig",
    "CACHE_NAMESPACES",
    
    # 键构建器
    "CacheKeyBuilder",
    
    # 序列化器
    "CacheSerializer",
    "default_serializer",
    
    # Redis 客户端
    "RedisClient",
    "RedisConfig",
    "get_redis_client",
    "close_redis_client",
    
    # 缓存管理器
    "CacheManager",
    "get_cache_manager",
    "set_cache_manager",
    
    # 监控指标
    "CacheMetrics",
    "MetricsContext",
]
