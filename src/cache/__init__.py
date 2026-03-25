"""
缓存模块（增强版）
导出所有缓存相关的类和函数
"""

# 现有模块
from src.cache.redis_client import RedisClient
from src.cache.serializer import CacheSerializer
from src.cache.key_builder import CacheKeyBuilder
from src.cache.metrics import CacheMetrics, MetricsContext
from src.cache.constants import CacheConfig, CacheTTL

# 新增模块（增强版）
from .local_cache import LocalCache, LocalCacheStats, get_local_cache
from .circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpenError,
    CircuitBreakerStats
)
from .cache_invalidator import CacheInvalidator, get_cache_invalidator
from .cache_warmer import CacheWarmer, CacheWarmerStats, get_cache_warmer

# 增强版缓存管理器
from .cache_manager import CacheManager, get_cache_manager, set_cache_manager

__all__ = [
    # 现有模块
    "RedisClient",
    "CacheSerializer",
    "CacheKeyBuilder",
    "CacheMetrics",
    "MetricsContext",
    "CacheConfig",
    "CacheTTL",
    
    # 新增模块
    "LocalCache",
    "LocalCacheStats",
    "get_local_cache",
    
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerOpenError",
    "CircuitBreakerStats",
    
    "CacheInvalidator",
    "get_cache_invalidator",
    
    "CacheWarmer",
    "CacheWarmerStats",
    "get_cache_warmer",
    
    # 增强版
    "CacheManager",
    "get_cache_manager",
    "set_cache_manager",
]
