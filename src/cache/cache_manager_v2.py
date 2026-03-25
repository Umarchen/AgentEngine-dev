"""
增强版缓存管理器模块
集成熔断器、本地缓存、批量操作等功能

对应需求：
- [REQ_REDIS_CACHE_002] 熔断器机制
- [REQ_REDIS_CACHE_005] 本地缓存优化
- [REQ_REDIS_CACHE_006] 批量操作优化
"""

import asyncio
import random
from typing import Any, Callable, List, Optional, Tuple, Type

from redis.exceptions import RedisError
from loguru import logger

from .redis_client import RedisClient
from .serializer import CacheSerializer
from .key_builder import CacheKeyBuilder
from .metrics import CacheMetrics, MetricsContext
from .constants import CacheConfig, CacheTTL
from .circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from .local_cache import LocalCache


class CacheManagerV2:
    """
    增强版缓存管理器
    
    集成组件：
    1. LocalCache（L1 缓存）
    2. CircuitBreaker（熔断器）
    3. CacheInvalidator（失效广播）
    4. RedisClient（L2 缓存）
    
    功能特性：
    - 多级缓存（L1 本地 + L2 Redis）
    - 熔断器保护
    - 批量操作优化
    - 降级逻辑
    - 监控指标采集
    
    Example:
        >>> manager = CacheManagerV2(
        ...     redis_client,
        ...     enable_local_cache=True,
        ...     local_cache_maxsize=1000,
        ...     local_cache_ttl=300
        ... )
        >>> await manager.initialize()
        >>> value = await manager.get("key")
    """
    
    def __init__(
        self,
        redis_client: RedisClient,
        serializer: Optional[CacheSerializer] = None,
        key_builder: Optional[CacheKeyBuilder] = None,
        enable_metrics: bool = True,
        enable_local_cache: bool = True,
        local_cache_maxsize: int = 1000,
        local_cache_ttl: float = 300.0,
        circuit_breaker_config: Optional[dict] = None
    ):
        """
        初始化缓存管理器
        
        Args:
            redis_client: Redis 客户端
            serializer: 序列化器
            key_builder: 缓存键构建器
            enable_metrics: 是否启用监控
            enable_local_cache: 是否启用本地缓存
            local_cache_maxsize: 本地缓存容量
            local_cache_ttl: 本地缓存 TTL
            circuit_breaker_config: 熔断器配置
        """
        self.redis_client = redis_client
        self.serializer = serializer or CacheSerializer(use_pickle=False)
        self.key_builder = key_builder or CacheKeyBuilder()
        self.enable_metrics = enable_metrics
        
        # 本地缓存（L1）
        self.local_cache: Optional[LocalCache] = None
        if enable_local_cache:
            self.local_cache = LocalCache(
                maxsize=local_cache_maxsize,
                ttl=local_cache_ttl
            )
        
        # 熔断器
        cb_config = circuit_breaker_config or {}
        self.circuit_breaker = CircuitBreaker(**cb_config)
        
        # 缓存失效器（延迟初始化）
        self.invalidator = None
        
        # 降级统计
        self.degradation_count = 0
        self.fallback_count = 0
    
    async def initialize(self) -> None:
        """初始化缓存管理器（启动订阅等）"""
        if self.local_cache:
            # 初始化失效广播器
            from .invalidator import CacheInvalidator
            self.invalidator = CacheInvalidator(
                redis_client=self.redis_client.client,
                local_cache=self.local_cache
            )
            await self.invalidator.start()
            logger.info("缓存管理器初始化完成，失效广播已启动")
    
    async def shutdown(self) -> None:
        """关闭缓存管理器"""
        if self.invalidator:
            await self.invalidator.stop()
        logger.info("缓存管理器已关闭")
    
    # ==================== 基础操作 ====================
    
    async def get(
        self,
        key: str,
        model_class: Optional[Type] = None,
        cache_type: str = "default"
    ) -> Optional[Any]:
        """
        获取缓存（增强版，支持 L1）
        
        流程：
        1. 查询 L1 本地缓存
        2. 通过熔断器查询 L2 Redis
        3. 返回结果（并回填 L1）
        
        Args:
            key: 缓存键
            model_class: 可选的 Pydantic 模型类
            cache_type: 缓存类型（用于监控）
            
        Returns:
            缓存值，不存在返回 None
        """
        async with MetricsContext("get", cache_type):
            # 1. 查询本地缓存
            if self.local_cache:
                local_value = self.local_cache.get(key)
                if local_value is not None:
                    logger.debug(f"L1 缓存命中: {key}")
                    if self.enable_metrics:
                        CacheMetrics.record_hit(cache_type + "_l1")
                    return local_value
            
            # 2. 通过熔断器查询 Redis
            try:
                async def _redis_get():
                    return await self._get_from_redis(key, model_class, cache_type)
                
                cached = await self.circuit_breaker.call(_redis_get)
                
                # 3. 回填本地缓存
                if cached is not None and self.local_cache:
                    self.local_cache.set(key, cached)
                
                return cached
                
            except CircuitBreakerOpen:
                logger.warning(f"熔断器打开，跳过 Redis: {key}")
                return None
            except Exception as e:
                logger.warning(f"获取缓存失败: {key}, 错误: {e}")
                return None
    
    async def _get_from_redis(
        self,
        key: str,
        model_class: Optional[Type],
        cache_type: str
    ) -> Optional[Any]:
        """从 Redis 获取缓存"""
        try:
            safe_key = self.key_builder.build(key)
            cached = await self.redis_client.get(safe_key)
            
            if cached is None:
                if self.enable_metrics:
                    CacheMetrics.record_miss(cache_type)
                return None
            
            if self.enable_metrics:
                CacheMetrics.record_hit(cache_type)
            
            return self.serializer.deserialize(cached, model_class)
            
        except RedisError as e:
            logger.warning(f"Redis GET 失败: {key}, 错误: {e}")
            self.degradation_count += 1
            if self.enable_metrics:
                CacheMetrics.record_degradation("redis_error")
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        nx: bool = False,
        cache_type: str = "default"
    ) -> bool:
        """
        设置缓存（增强版，支持 L1）
        
        流程：
        1. 写入 L1 本地缓存
        2. 通过熔断器写入 L2 Redis
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）
            nx: 仅当键不存在时设置
            cache_type: 缓存类型
            
        Returns:
            是否设置成功
        """
        async with MetricsContext("set", cache_type):
            # 1. 写入本地缓存
            if self.local_cache:
                self.local_cache.set(key, value)
            
            # 2. 通过熔断器写入 Redis
            try:
                async def _redis_set():
                    return await self._set_to_redis(key, value, ttl, nx, cache_type)
                
                return await self.circuit_breaker.call(_redis_set)
                
            except CircuitBreakerOpen:
                logger.warning(f"熔断器打开，跳过 Redis 写入: {key}")
                return False
            except Exception as e:
                logger.warning(f"设置缓存失败: {key}, 错误: {e}")
                return False
    
    async def _set_to_redis(
        self,
        key: str,
        value: Any,
        ttl: Optional[int],
        nx: bool,
        cache_type: str
    ) -> bool:
        """写入 Redis"""
        try:
            safe_key = self.key_builder.build(key)
            serialized = self.serializer.serialize(value)
            
            if ttl:
                ttl = self._add_ttl_jitter(ttl)
            
            result = await self.redis_client.set(
                safe_key,
                serialized,
                ex=ttl,
                nx=nx
            )
            return result
            
        except RedisError as e:
            logger.warning(f"Redis SET 失败: {key}, 错误: {e}")
            self.degradation_count += 1
            if self.enable_metrics:
                CacheMetrics.record_degradation("redis_error")
            return False
    
    async def delete(
        self,
        key: str,
        cache_type: str = "default",
        broadcast: bool = True
    ) -> bool:
        """
        删除缓存（增强版，支持广播）
        
        流程：
        1. 删除 L1 本地缓存
        2. 通过熔断器删除 L2 Redis
        3. 广播缓存失效消息
        
        Args:
            key: 缓存键
            cache_type: 缓存类型
            broadcast: 是否广播失效消息
            
        Returns:
            是否删除成功
        """
        async with MetricsContext("delete", cache_type):
            # 1. 删除本地缓存
            if self.local_cache:
                self.local_cache.delete(key)
            
            # 2. 通过熔断器删除 Redis
            try:
                async def _redis_delete():
                    return await self._delete_from_redis(key, cache_type)
                
                result = await self.circuit_breaker.call(_redis_delete)
                
                # 3. 广播失效消息
                if broadcast and self.invalidator:
                    await self.invalidator.publish_invalidation(key)
                
                return result
                
            except CircuitBreakerOpen:
                logger.warning(f"熔断器打开，跳过 Redis 删除: {key}")
                return False
            except Exception as e:
                logger.warning(f"删除缓存失败: {key}, 错误: {e}")
                return False
    
    async def _delete_from_redis(self, key: str, cache_type: str) -> bool:
        """从 Redis 删除缓存"""
        try:
            safe_key = self.key_builder.build(key)
            result = await self.redis_client.delete(safe_key)
            return result > 0
        except RedisError as e:
            logger.warning(f"Redis DELETE 失败: {key}, 错误: {e}")
            self.degradation_count += 1
            if self.enable_metrics:
                CacheMetrics.record_degradation("redis_error")
            return False
    
    # ==================== 批量操作（新增）====================
    
    async def mget(
        self,
        keys: List[str],
        model_class: Optional[Type] = None,
        cache_type: str = "default"
    ) -> List[Optional[Any]]:
        """
        批量获取缓存
        
        Args:
            keys: 缓存键列表
            model_class: 可选的 Pydantic 模型类
            cache_type: 缓存类型
            
        Returns:
            缓存值列表
        """
        if not keys:
            return []
        
        results = [None] * len(keys)
        
        # 1. 从本地缓存获取
        if self.local_cache:
            for i, key in enumerate(keys):
                local_value = self.local_cache.get(key)
                if local_value is not None:
                    results[i] = local_value
        
        # 2. 对本地缓存未命中的，从 Redis 批量获取
        miss_indices = [i for i, v in enumerate(results) if v is None]
        miss_keys = [keys[i] for i in miss_indices]
        
        if miss_keys:
            try:
                # 使用 Redis MGET
                safe_keys = [self.key_builder.build(k) for k in miss_keys]
                redis_values = await self.redis_client.client.mget(*safe_keys)
                
                # 反序列化并填充结果
                for idx, key, redis_val in zip(miss_indices, miss_keys, redis_values):
                    if redis_val:
                        value = self.serializer.deserialize(redis_val, model_class)
                        results[idx] = value
                        
                        # 回填本地缓存
                        if self.local_cache:
                            self.local_cache.set(key, value)
                
                if self.enable_metrics:
                    CacheMetrics.record_hit(cache_type)
                
            except Exception as e:
                logger.error(f"批量获取失败: {e}")
                if self.enable_metrics:
                    CacheMetrics.record_degradation("batch_error")
        
        return results
    
    async def delete_batch(
        self,
        keys: List[str],
        cache_type: str = "default",
        broadcast: bool = True
    ) -> Tuple[int, List[str]]:
        """
        批量删除缓存
        
        Args:
            keys: 缓存键列表
            cache_type: 缓存类型
            broadcast: 是否广播失效消息
            
        Returns:
            (成功删除数量, 失败的键列表)
        """
        if not keys:
            return 0, []
        
        success_count = 0
        failed_keys = []
        
        # 1. 删除本地缓存
        if self.local_cache:
            for key in keys:
                self.local_cache.delete(key)
        
        # 2. 批量删除 Redis
        try:
            safe_keys = [self.key_builder.build(k) for k in keys]
            deleted_count = await self.redis_client.client.delete(*safe_keys)
            success_count = deleted_count
            
        except Exception as e:
            logger.error(f"批量删除失败: {e}")
            failed_keys = keys
            if self.enable_metrics:
                CacheMetrics.record_degradation("batch_error")
        
        # 3. 广播失效消息
        if broadcast and self.invalidator:
            for key in keys:
                await self.invalidator.publish_invalidation(key)
        
        return success_count, failed_keys
    
    # ==================== 高级操作 ====================
    
    async def get_with_fallback(
        self,
        key: str,
        loader: Callable[[], Any],
        ttl: int,
        model_class: Optional[Type] = None,
        cache_type: str = "default"
    ) -> Any:
        """
        带降级的缓存读取（Cache-Aside 模式）
        
        Args:
            key: 缓存键
            loader: 数据加载函数（回源数据库）
            ttl: 过期时间（秒）
            model_class: 可选的 Pydantic 模型类
            cache_type: 缓存类型（用于监控）
            
        Returns:
            缓存数据或从数据库加载的数据
        """
        # 1. 尝试从缓存读取
        cached = await self.get(key, model_class, cache_type)
        if cached is not None:
            return cached
        
        # 2. 缓存未命中，回源数据库
        logger.info(f"缓存未命中，回源数据库: {key}")
        self.fallback_count += 1
        
        if self.enable_metrics:
            CacheMetrics.record_fallback(cache_type)
        
        # 执行加载函数
        data = await loader() if asyncio.iscoroutinefunction(loader) else loader()
        
        # 3. 异步写入缓存（不阻塞）
        if data is not None:
            asyncio.create_task(
                self.set(key, data, ttl=ttl, cache_type=cache_type)
            )
        
        return data
    
    async def delete_pattern(
        self,
        pattern: str,
        cache_type: str = "default"
    ) -> int:
        """
        批量删除缓存（按模式）
        
        Args:
            pattern: 匹配模式（如 agent:config:*）
            cache_type: 缓存类型
            
        Returns:
            删除的键数量
        """
        async with MetricsContext("delete_pattern", cache_type):
            try:
                safe_pattern = self.key_builder.build_pattern(pattern)
                
                keys = []
                async for key in self.redis_client.scan_iter(match=safe_pattern):
                    keys.append(key)
                
                if keys:
                    await self.redis_client.delete(*keys)
                    return len(keys)
                
                return 0
                
            except RedisError as e:
                logger.warning(f"Redis 批量删除失败: {pattern}, 错误: {e}")
                self.degradation_count += 1
                
                if self.enable_metrics:
                    CacheMetrics.record_degradation("redis_error")
                
                return 0
    
    # ==================== 工具方法 ====================
    
    def _add_ttl_jitter(self, ttl: int) -> int:
        """添加 TTL 随机偏移"""
        jitter_percent = CacheConfig.TTL_JITTER_PERCENT
        jitter = int(ttl * jitter_percent / 100)
        return ttl + random.randint(-jitter, jitter)
    
    async def get_stats(self) -> dict:
        """获取缓存统计信息"""
        try:
            memory_info = await self.redis_client.get_memory_usage()
            keys_count = await self.redis_client.get_keys_count()
            is_connected = self.redis_client.is_connected
            
            # 本地缓存统计
            local_stats = {}
            if self.local_cache:
                local_stats = self.local_cache.get_stats()
            
            # 熔断器统计
            cb_stats = self.circuit_breaker.get_stats()
            
            return {
                "connected": is_connected,
                "keys_count": keys_count,
                "memory_used_mb": memory_info.get("used_memory", 0) / (1024 * 1024),
                "degradation_count": self.degradation_count,
                "fallback_count": self.fallback_count,
                "local_cache": local_stats,
                "circuit_breaker": cb_stats,
            }
        except Exception as e:
            logger.error(f"获取缓存统计信息失败: {e}")
            return {
                "connected": False,
                "error": str(e),
            }
    
    async def health_check(self) -> dict:
        """健康检查"""
        try:
            is_healthy = await self.redis_client.ping()
            cb_state = self.circuit_breaker.state.value
            
            return {
                "status": "healthy" if is_healthy else "unhealthy",
                "connected": is_healthy,
                "circuit_breaker_state": cb_state,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(e),
            }


# 全局缓存管理器实例
_cache_manager_v2: Optional[CacheManagerV2] = None


def get_cache_manager_v2() -> Optional[CacheManagerV2]:
    """获取全局缓存管理器实例"""
    return _cache_manager_v2


def set_cache_manager_v2(manager: CacheManagerV2):
    """设置全局缓存管理器实例"""
    global _cache_manager_v2
    _cache_manager_v2 = manager
