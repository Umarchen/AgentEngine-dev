"""
缓存管理器模块（增强版）
提供统一的缓存管理接口，集成 L1 本地缓存和熔断器
"""

import asyncio
import random
from typing import Any, Optional, Callable, Type, List, Dict, Tuple

from redis.exceptions import RedisError
from loguru import logger

from .redis_client import RedisClient
from .serializer import CacheSerializer
from .key_builder import CacheKeyBuilder
from .metrics import CacheMetrics, MetricsContext
from .constants import CacheConfig, CacheTTL
from .local_cache import LocalCache, get_local_cache
from .circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


class CacheManager:
    """
    Redis 缓存管理器（增强版 - 集成 L1 缓存 + 熔断器）
    
    功能：
    1. get/set/delete 基础操作
    2. L1 本地缓存（TTLCache，容量 1000，TTL 300s）
    3. 熔断器机制（滑动窗口，50% 错误率触发，30s 半开）
    4. 批量操作（mget, delete_batch）
    5. 序列化/反序列化
    6. 降级逻辑（Redis 故障时回源）
    7. 监控指标采集
    
    对应需求：
    - [REQ_REDIS_CACHE_002] 熔断器机制（新增）
    - [REQ_REDIS_CACHE_005] 本地缓存优化（增强）
    - [REQ_REDIS_CACHE_006] 批量操作优化（新增）
    """
    
    def __init__(
        self,
        redis_client: RedisClient,
        serializer: Optional[CacheSerializer] = None,
        key_builder: Optional[CacheKeyBuilder] = None,
        enable_metrics: bool = True,
        # L1 本地缓存配置
        enable_l1_cache: bool = True,
        l1_maxsize: int = 1000,
        l1_ttl: float = 300.0,
        # 熔断器配置
        enable_circuit_breaker: bool = True,
        circuit_breaker_error_threshold: float = 50.0,
        circuit_breaker_time_window: int = 10,
        circuit_breaker_recovery_timeout: int = 30
    ):
        """
        初始化缓存管理器
        
        Args:
            redis_client: Redis 客户端
            serializer: 序列化器（默认使用 JSON）
            key_builder: 缓存键构建器
            enable_metrics: 是否启用监控指标
            enable_l1_cache: 是否启用 L1 本地缓存
            l1_maxsize: L1 缓存最大容量
            l1_ttl: L1 缓存 TTL（秒）
            enable_circuit_breaker: 是否启用熔断器
            circuit_breaker_error_threshold: 熔断器错误率阈值（%）
            circuit_breaker_time_window: 熔断器时间窗口（秒）
            circuit_breaker_recovery_timeout: 熔断器恢复超时（秒）
        """
        self.redis_client = redis_client
        self.serializer = serializer or CacheSerializer(use_pickle=False)
        self.key_builder = key_builder or CacheKeyBuilder()
        self.enable_metrics = enable_metrics
        
        # L1 本地缓存
        self.enable_l1_cache = enable_l1_cache
        if enable_l1_cache:
            self.local_cache = LocalCache(maxsize=l1_maxsize, ttl=l1_ttl)
            logger.info(
                f"L1 本地缓存已启用 - maxsize={l1_maxsize}, ttl={l1_ttl}s"
            )
        else:
            self.local_cache = None
        
        # 熔断器
        self.enable_circuit_breaker = enable_circuit_breaker
        if enable_circuit_breaker:
            self.circuit_breaker = CircuitBreaker(
                name="redis_cache",
                error_threshold_percent=circuit_breaker_error_threshold,
                time_window_seconds=circuit_breaker_time_window,
                recovery_timeout_seconds=circuit_breaker_recovery_timeout
            )
            logger.info(
                f"熔断器已启用 - 错误阈值={circuit_breaker_error_threshold}%, "
                f"时间窗口={circuit_breaker_time_window}s, "
                f"恢复超时={circuit_breaker_recovery_timeout}s"
            )
        else:
            self.circuit_breaker = None
        
        # 降级统计
        self.degradation_count = 0
        self.fallback_count = 0
    
    # ==================== 基础操作 ====================
    
    async def get(
        self,
        key: str,
        model_class: Optional[Type] = None,
        cache_type: str = "default"
    ) -> Optional[Any]:
        """
        获取缓存（优先从 L1 本地缓存获取）
        
        Args:
            key: 缓存键
            model_class: 可选的 Pydantic 模型类
            cache_type: 缓存类型（用于监控）
            
        Returns:
            缓存值，不存在返回 None
        """
        async with MetricsContext("get", cache_type):
            # 1. 先尝试从 L1 本地缓存获取
            if self.enable_l1_cache and self.local_cache:
                l1_value = self.local_cache.get(key)
                if l1_value is not None:
                    logger.debug(f"L1 缓存命中: {key}")
                    if self.enable_metrics:
                        CacheMetrics.record_hit(cache_type, source="l1")
                    return l1_value
            
            # 2. 熔断器检查
            if self.enable_circuit_breaker and self.circuit_breaker:
                if self.circuit_breaker.is_open:
                    logger.warning(f"熔断器打开，跳过 Redis 查询: {key}")
                    self.degradation_count += 1
                    if self.enable_metrics:
                        CacheMetrics.record_degradation("circuit_breaker_open")
                    return None
            
            # 3. 从 Redis 获取
            try:
                # 构建安全键
                safe_key = self.key_builder.build(key)
                
                # 如果启用熔断器，通过熔断器调用
                if self.enable_circuit_breaker and self.circuit_breaker:
                    cached = await self.circuit_breaker.call(
                        self.redis_client.get, safe_key
                    )
                else:
                    cached = await self.redis_client.get(safe_key)
                
                if cached is None:
                    # 缓存未命中
                    if self.enable_metrics:
                        CacheMetrics.record_miss(cache_type)
                    return None
                
                # 缓存命中
                if self.enable_metrics:
                    CacheMetrics.record_hit(cache_type, source="redis")
                
                # 反序列化
                value = self.serializer.deserialize(cached, model_class)
                
                # 4. 写入 L1 本地缓存
                if self.enable_l1_cache and self.local_cache and value is not None:
                    self.local_cache.set(key, value)
                    logger.debug(f"已写入 L1 缓存: {key}")
                
                return value
                
            except CircuitBreakerOpenError:
                # 熔断器打开
                logger.warning(f"熔断器打开，跳过 Redis 查询: {key}")
                self.degradation_count += 1
                if self.enable_metrics:
                    CacheMetrics.record_degradation("circuit_breaker_open")
                return None
                
            except RedisError as e:
                # Redis 错误，降级处理
                logger.warning(f"Redis GET 失败，降级处理: {key}, 错误: {e}")
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
        设置缓存（同时写入 L1 和 Redis）
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None 表示永不过期
            nx: 仅当键不存在时设置
            cache_type: 缓存类型（用于监控）
            
        Returns:
            是否设置成功
        """
        async with MetricsContext("set", cache_type):
            # 1. 写入 L1 本地缓存
            if self.enable_l1_cache and self.local_cache:
                self.local_cache.set(key, value)
                logger.debug(f"已写入 L1 缓存: {key}")
            
            # 2. 熔断器检查
            if self.enable_circuit_breaker and self.circuit_breaker:
                if self.circuit_breaker.is_open:
                    logger.warning(f"熔断器打开，跳过 Redis 写入: {key}")
                    # L1 已写入，返回 True（降级但成功）
                    return True
            
            # 3. 写入 Redis
            try:
                # 构建安全键
                safe_key = self.key_builder.build(key)
                
                # 序列化
                serialized = self.serializer.serialize(value)
                
                # 添加 TTL 随机偏移（防止雪崩）
                if ttl:
                    ttl = self._add_ttl_jitter(ttl)
                
                # 如果启用熔断器，通过熔断器调用
                if self.enable_circuit_breaker and self.circuit_breaker:
                    result = await self.circuit_breaker.call(
                        self.redis_client.set,
                        safe_key, serialized, ex=ttl, nx=nx
                    )
                else:
                    result = await self.redis_client.set(
                        safe_key, serialized, ex=ttl, nx=nx
                    )
                
                return result
                
            except CircuitBreakerOpenError:
                # 熔断器打开，L1 已写入，返回 True（降级但成功）
                logger.warning(f"熔断器打开，仅写入 L1 缓存: {key}")
                return True
                
            except RedisError as e:
                # Redis 错误，记录但不抛出异常（L1 已写入）
                logger.warning(f"Redis SET 失败: {key}, 错误: {e}")
                self.degradation_count += 1
                
                if self.enable_metrics:
                    CacheMetrics.record_degradation("redis_error")
                
                # L1 已写入，返回 True（降级但成功）
                return True
    
    async def delete(
        self,
        key: str,
        cache_type: str = "default"
    ) -> bool:
        """
        删除缓存（同时删除 L1 和 Redis）
        
        Args:
            key: 缓存键
            cache_type: 缓存类型（用于监控）
            
        Returns:
            是否删除成功
        """
        async with MetricsContext("delete", cache_type):
            # 1. 删除 L1 本地缓存
            if self.enable_l1_cache and self.local_cache:
                self.local_cache.delete(key)
                logger.debug(f"已删除 L1 缓存: {key}")
            
            # 2. 删除 Redis 缓存
            try:
                # 构建安全键
                safe_key = self.key_builder.build(key)
                
                # 如果启用熔断器，通过熔断器调用
                if self.enable_circuit_breaker and self.circuit_breaker:
                    result = await self.circuit_breaker.call(
                        self.redis_client.delete, safe_key
                    )
                else:
                    result = await self.redis_client.delete(safe_key)
                
                return result > 0
                
            except CircuitBreakerOpenError:
                # 熔断器打开，L1 已删除，返回 True
                logger.warning(f"熔断器打开，仅删除 L1 缓存: {key}")
                return True
                
            except RedisError as e:
                logger.warning(f"Redis DELETE 失败: {key}, 错误: {e}")
                self.degradation_count += 1
                
                if self.enable_metrics:
                    CacheMetrics.record_degradation("redis_error")
                
                # L1 已删除，返回 True
                return True
    
    # ==================== 批量操作（新增）====================
    
    async def mget(
        self,
        keys: List[str],
        model_class: Optional[Type] = None,
        cache_type: str = "default"
    ) -> Dict[str, Any]:
        """
        批量获取缓存（Redis MGET + L1 缓存）
        
        Args:
            keys: 缓存键列表
            model_class: 可选的 Pydantic 模型类
            cache_type: 缓存类型（用于监控）
            
        Returns:
            键值对字典（不存在的键不会出现在结果中）
            
        对应需求：[REQ_REDIS_CACHE_006] 批量操作优化（新增）
        """
        async with MetricsContext("mget", cache_type):
            result = {}
            l1_miss_keys = []
            
            # 1. 先从 L1 本地缓存获取
            if self.enable_l1_cache and self.local_cache:
                for key in keys:
                    l1_value = self.local_cache.get(key)
                    if l1_value is not None:
                        result[key] = l1_value
                        logger.debug(f"L1 缓存命中（批量）: {key}")
                    else:
                        l1_miss_keys.append(key)
            else:
                l1_miss_keys = keys
            
            # 如果所有键都在 L1 命中，直接返回
            if not l1_miss_keys:
                logger.debug(f"批量获取全部从 L1 命中 - 总数: {len(keys)}")
                return result
            
            # 2. 熔断器检查
            if self.enable_circuit_breaker and self.circuit_breaker:
                if self.circuit_breaker.is_open:
                    logger.warning(f"熔断器打开，跳过 Redis 批量查询")
                    return result
            
            # 3. 从 Redis 批量获取未命中的键
            try:
                # 构建安全键
                safe_keys = [self.key_builder.build(key) for key in l1_miss_keys]
                
                # 使用 MGET 命令
                if self.enable_circuit_breaker and self.circuit_breaker:
                    cached_values = await self.circuit_breaker.call(
                        self.redis_client.mget, safe_keys
                    )
                else:
                    cached_values = await self.redis_client.mget(*safe_keys)
                
                # 处理结果
                for i, (key, cached) in enumerate(zip(l1_miss_keys, cached_values)):
                    if cached is not None:
                        value = self.serializer.deserialize(cached, model_class)
                        result[key] = value
                        
                        # 写入 L1 本地缓存
                        if self.enable_l1_cache and self.local_cache:
                            self.local_cache.set(key, value)
                        
                        logger.debug(f"Redis 批量命中: {key}")
                
                logger.info(
                    f"批量获取完成 - 总数: {len(keys)}, "
                    f"L1 命中: {len(keys) - len(l1_miss_keys)}, "
                    f"Redis 命中: {len(result) - (len(keys) - len(l1_miss_keys))}"
                )
                
                return result
                
            except CircuitBreakerOpenError:
                logger.warning(f"熔断器打开，跳过 Redis 批量查询")
                return result
                
            except RedisError as e:
                logger.warning(f"Redis MGET 失败: {e}")
                self.degradation_count += 1
                return result
    
    async def delete_batch(
        self,
        keys: List[str],
        cache_type: str = "default"
    ) -> Tuple[int, int]:
        """
        批量删除缓存（同时删除 L1 和 Redis）
        
        Args:
            keys: 缓存键列表
            cache_type: 缓存类型（用于监控）
            
        Returns:
            (成功数量, 失败数量)
            
        对应需求：[REQ_REDIS_CACHE_006] 批量操作优化（新增）
        """
        async with MetricsContext("delete_batch", cache_type):
            success_count = 0
            fail_count = 0
            
            # 1. 批量删除 L1 本地缓存
            if self.enable_l1_cache and self.local_cache:
                l1_success, l1_fail = self.local_cache.delete_batch(keys)
                logger.debug(
                    f"L1 批量删除完成 - 成功: {l1_success}, 失败: {l1_fail}"
                )
            
            # 2. 熔断器检查
            if self.enable_circuit_breaker and self.circuit_breaker:
                if self.circuit_breaker.is_open:
                    logger.warning(f"熔断器打开，跳过 Redis 批量删除")
                    return len(keys), 0
            
            # 3. 使用 Pipeline 批量删除 Redis
            try:
                # 构建安全键
                safe_keys = [self.key_builder.build(key) for key in keys]
                
                # 使用 Pipeline
                if self.enable_circuit_breaker and self.circuit_breaker:
                    deleted = await self.circuit_breaker.call(
                        self._delete_batch_pipeline, safe_keys
                    )
                else:
                    deleted = await self._delete_batch_pipeline(safe_keys)
                
                success_count = deleted
                fail_count = len(keys) - deleted
                
                logger.info(
                    f"批量删除完成 - 总数: {len(keys)}, "
                    f"成功: {success_count}, 失败: {fail_count}"
                )
                
                return success_count, fail_count
                
            except CircuitBreakerOpenError:
                logger.warning(f"熔断器打开，跳过 Redis 批量删除")
                return len(keys), 0
                
            except RedisError as e:
                logger.warning(f"Redis 批量删除失败: {e}")
                self.degradation_count += 1
                return 0, len(keys)
    
    async def _delete_batch_pipeline(self, safe_keys: List[str]) -> int:
        """
        使用 Pipeline 批量删除 Redis 键
        
        Args:
            safe_keys: 安全键列表
            
        Returns:
            删除的键数量
        """
        # 使用 Redis Pipeline
        pipe = self.redis_client.get_connection().pipeline()
        for key in safe_keys:
            pipe.delete(key)
        results = await pipe.execute()
        return sum(1 for r in results if r > 0)
    
    async def delete_pattern(
        self,
        pattern: str,
        cache_type: str = "default"
    ) -> int:
        """
        批量删除缓存（按模式）
        
        Args:
            pattern: 匹配模式（如 agent:config:*）
            cache_type: 缓存类型（用于监控）
            
        Returns:
            删除的键数量
        """
        async with MetricsContext("delete_pattern", cache_type):
            # 1. 清空匹配的 L1 缓存（暴力清空）
            if self.enable_l1_cache and self.local_cache:
                # 简单实现：清空所有 L1 缓存
                # 更好的实现需要维护键模式索引
                self.local_cache.clear()
                logger.debug(f"已清空 L1 缓存（模式: {pattern}）")
            
            # 2. 从 Redis 批量删除
            try:
                # 构建安全模式
                safe_pattern = self.key_builder.build_pattern(pattern)
                
                # 使用 SCAN 避免阻塞
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
    
    async def exists(self, key: str) -> bool:
        """
        检查键是否存在（优先检查 L1）
        
        Args:
            key: 缓存键
            
        Returns:
            是否存在
        """
        # 1. 检查 L1 缓存
        if self.enable_l1_cache and self.local_cache:
            if self.local_cache.exists(key):
                return True
        
        # 2. 检查 Redis
        try:
            safe_key = self.key_builder.build(key)
            result = await self.redis_client.exists(safe_key)
            return result > 0
        except RedisError as e:
            logger.warning(f"Redis EXISTS 失败: {key}, 错误: {e}")
            return False
    
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
    
    async def get_or_set(
        self,
        key: str,
        loader: Callable[[], Any],
        ttl: int,
        model_class: Optional[Type] = None,
        cache_type: str = "default"
    ) -> Any:
        """
        获取或设置缓存（Read-Through 模式）
        
        Args:
            key: 缓存键
            loader: 数据加载函数
            ttl: 过期时间（秒）
            model_class: 可选的 Pydantic 模型类
            cache_type: 缓存类型（用于监控）
            
        Returns:
            缓存数据或从数据库加载的数据
        """
        return await self.get_with_fallback(
            key, loader, ttl, model_class, cache_type
        )
    
    async def warmup(self, key: str) -> bool:
        """
        预热缓存（触发缓存加载）
        
        Args:
            key: 缓存键
            
        Returns:
            是否成功
        """
        # 简单实现：触发 get 操作
        # 实际使用时，应该配合 loader 函数
        value = await self.get(key)
        return value is not None
    
    # ==================== 工具方法 ====================
    
    def _add_ttl_jitter(self, ttl: int) -> int:
        """
        添加 TTL 随机偏移（防止缓存雪崩）
        
        Args:
            ttl: 基础 TTL
            
        Returns:
            添加随机偏移后的 TTL
        """
        jitter_percent = CacheConfig.TTL_JITTER_PERCENT
        jitter = int(ttl * jitter_percent / 100)
        return ttl + random.randint(-jitter, jitter)
    
    async def get_stats(self) -> dict:
        """
        获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        try:
            # 获取 Redis 信息
            memory_info = await self.redis_client.get_memory_usage()
            keys_count = await self.redis_client.get_keys_count()
            is_connected = self.redis_client.is_connected
            
            stats = {
                "connected": is_connected,
                "keys_count": keys_count,
                "memory_used_mb": memory_info.get("used_memory", 0) / (1024 * 1024),
                "degradation_count": self.degradation_count,
                "fallback_count": self.fallback_count,
            }
            
            # L1 缓存统计
            if self.enable_l1_cache and self.local_cache:
                stats["l1_cache"] = self.local_cache.get_stats()
            
            # 熔断器统计
            if self.enable_circuit_breaker and self.circuit_breaker:
                stats["circuit_breaker"] = self.circuit_breaker.get_stats()
            
            return stats
        except Exception as e:
            logger.error(f"获取缓存统计信息失败: {e}")
            return {
                "connected": False,
                "keys_count": 0,
                "memory_used_mb": 0,
                "degradation_count": self.degradation_count,
                "fallback_count": self.fallback_count,
                "error": str(e),
            }
    
    async def health_check(self) -> dict:
        """
        健康检查（增强版）
        
        Returns:
            健康状态字典
            
        对应需求：[REQ_REDIS_CACHE_007] 缓存健康检查增强（增强）
        """
        try:
            is_healthy = await self.redis_client.ping()
            
            health = {
                "status": "healthy" if is_healthy else "unhealthy",
                "connected": is_healthy,
            }
            
            # L1 缓存状态
            if self.enable_l1_cache and self.local_cache:
                health["l1_cache"] = {
                    "enabled": True,
                    "size": self.local_cache.get_size(),
                    "maxsize": self.local_cache.maxsize
                }
            
            # 熔断器状态
            if self.enable_circuit_breaker and self.circuit_breaker:
                health["circuit_breaker"] = {
                    "state": self.circuit_breaker.state.value,
                    "is_open": self.circuit_breaker.is_open
                }
            
            return health
        except Exception as e:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(e),
            }
    
    # ==================== 熔断器手动控制 ====================
    
    def force_open_circuit_breaker(self):
        """强制打开熔断器"""
        if self.enable_circuit_breaker and self.circuit_breaker:
            self.circuit_breaker.force_open()
            logger.warning("熔断器已强制打开")
    
    def force_close_circuit_breaker(self):
        """强制关闭熔断器"""
        if self.enable_circuit_breaker and self.circuit_breaker:
            self.circuit_breaker.force_close()
            logger.info("熔断器已强制关闭")
    
    def reset_circuit_breaker(self):
        """重置熔断器"""
        if self.enable_circuit_breaker and self.circuit_breaker:
            self.circuit_breaker.reset()
            logger.info("熔断器已重置")


# 全局缓存管理器实例
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> Optional[CacheManager]:
    """获取全局缓存管理器实例"""
    return _cache_manager


def set_cache_manager(manager: CacheManager):
    """设置全局缓存管理器实例"""
    global _cache_manager
    _cache_manager = manager
