"""
缓存管理器模块
提供统一的缓存管理接口
"""

import asyncio
import random
from typing import Any, Optional, Callable, Type

from redis.exceptions import RedisError
from loguru import logger

from .redis_client import RedisClient
from .serializer import CacheSerializer
from .key_builder import CacheKeyBuilder
from .metrics import CacheMetrics, MetricsContext
from .constants import CacheConfig, CacheTTL


class CacheManager:
    """
    Redis 缓存管理器（无 L1 缓存）
    
    功能：
    1. get/set/delete 基础操作
    2. 序列化/反序列化
    3. 降级逻辑（Redis 故障时回源）
    4. 监控指标采集
    """
    
    def __init__(
        self,
        redis_client: RedisClient,
        serializer: Optional[CacheSerializer] = None,
        key_builder: Optional[CacheKeyBuilder] = None,
        enable_metrics: bool = True
    ):
        """
        初始化缓存管理器
        
        Args:
            redis_client: Redis 客户端
            serializer: 序列化器（默认使用 JSON）
            key_builder: 缓存键构建器
            enable_metrics: 是否启用监控指标
        """
        self.redis_client = redis_client
        self.serializer = serializer or CacheSerializer(use_pickle=False)
        self.key_builder = key_builder or CacheKeyBuilder()
        self.enable_metrics = enable_metrics
        
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
        获取缓存
        
        Args:
            key: 缓存键
            model_class: 可选的 Pydantic 模型类
            cache_type: 缓存类型（用于监控）
            
        Returns:
            缓存值，不存在返回 None
        """
        async with MetricsContext("get", cache_type):
            try:
                # 构建安全键
                safe_key = self.key_builder.build(key)
                
                # 从 Redis 获取
                cached = await self.redis_client.get(safe_key)
                
                if cached is None:
                    # 缓存未命中
                    if self.enable_metrics:
                        CacheMetrics.record_miss(cache_type)
                    return None
                
                # 缓存命中
                if self.enable_metrics:
                    CacheMetrics.record_hit(cache_type)
                
                # 反序列化
                return self.serializer.deserialize(cached, model_class)
                
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
        设置缓存
        
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
            try:
                # 构建安全键
                safe_key = self.key_builder.build(key)
                
                # 序列化
                serialized = self.serializer.serialize(value)
                
                # 添加 TTL 随机偏移（防止雪崩）
                if ttl:
                    ttl = self._add_ttl_jitter(ttl)
                
                # 写入 Redis
                result = await self.redis_client.set(
                    safe_key,
                    serialized,
                    ex=ttl,
                    nx=nx
                )
                
                return result
                
            except RedisError as e:
                # Redis 错误，记录但不抛出异常
                logger.warning(f"Redis SET 失败: {key}, 错误: {e}")
                self.degradation_count += 1
                
                if self.enable_metrics:
                    CacheMetrics.record_degradation("redis_error")
                
                return False
    
    async def delete(
        self,
        key: str,
        cache_type: str = "default"
    ) -> bool:
        """
        删除缓存
        
        Args:
            key: 缓存键
            cache_type: 缓存类型（用于监控）
            
        Returns:
            是否删除成功
        """
        async with MetricsContext("delete", cache_type):
            try:
                # 构建安全键
                safe_key = self.key_builder.build(key)
                
                # 删除
                result = await self.redis_client.delete(safe_key)
                
                return result > 0
                
            except RedisError as e:
                logger.warning(f"Redis DELETE 失败: {key}, 错误: {e}")
                self.degradation_count += 1
                
                if self.enable_metrics:
                    CacheMetrics.record_degradation("redis_error")
                
                return False
    
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
        检查键是否存在
        
        Args:
            key: 缓存键
            
        Returns:
            是否存在
        """
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
        # 1. 尝试从 Redis 读取
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
            
            return {
                "connected": is_connected,
                "keys_count": keys_count,
                "memory_used_mb": memory_info.get("used_memory", 0) / (1024 * 1024),
                "degradation_count": self.degradation_count,
                "fallback_count": self.fallback_count,
            }
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
        健康检查
        
        Returns:
            健康状态字典
        """
        try:
            is_healthy = await self.redis_client.ping()
            return {
                "status": "healthy" if is_healthy else "unhealthy",
                "connected": is_healthy,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(e),
            }


# 全局缓存管理器实例
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> Optional[CacheManager]:
    """获取全局缓存管理器实例"""
    return _cache_manager


def set_cache_manager(manager: CacheManager):
    """设置全局缓存管理器实例"""
    global _cache_manager
    _cache_manager = manager
