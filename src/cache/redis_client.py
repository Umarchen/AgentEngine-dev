"""
Redis 客户端模块
负责 Redis 连接池管理和基础操作
"""

import asyncio
from typing import Optional, List, Any

from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.sentinel import Sentinel
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from loguru import logger
from pydantic import BaseModel

from .constants import CacheConfig


class RedisConfig(BaseModel):
    """Redis 配置模型"""
    
    # 单机模式配置
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    
    # 连接池配置
    max_connections: int = CacheConfig.MAX_CONNECTIONS
    socket_timeout: int = CacheConfig.SOCKET_TIMEOUT
    socket_connect_timeout: int = CacheConfig.SOCKET_CONNECT_TIMEOUT
    retry_on_timeout: bool = True
    decode_responses: bool = True
    
    # 哨兵模式配置
    sentinel_enabled: bool = False
    sentinel_master_name: str = "mymaster"
    sentinel_hosts: Optional[List[str]] = None


class RedisClient:
    """
    Redis 客户端
    
    功能：
    1. 连接池管理
    2. 重试机制（tenacity）
    3. 健康检查
    4. 单机模式和哨兵模式支持
    """
    
    def __init__(self, config: RedisConfig):
        """
        初始化 Redis 客户端
        
        Args:
            config: Redis 配置
        """
        self.config = config
        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[Redis] = None
        self._sentinel: Optional[Sentinel] = None
        self._is_connected = False
    
    async def connect(self) -> bool:
        """
        连接 Redis
        
        Returns:
            是否连接成功
        """
        try:
            if self.config.sentinel_enabled:
                # 哨兵模式
                await self._connect_sentinel()
            else:
                # 单机模式
                await self._connect_standalone()
            
            self._is_connected = True
            logger.info(
                f"Redis 连接成功: "
                f"{'哨兵模式' if self.config.sentinel_enabled else '单机模式'}"
            )
            return True
            
        except Exception as e:
            logger.error(f"Redis 连接失败: {e}")
            self._is_connected = False
            return False
    
    async def _connect_standalone(self):
        """连接单机模式 Redis"""
        self._pool = ConnectionPool(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            password=self.config.password,
            max_connections=self.config.max_connections,
            socket_timeout=self.config.socket_timeout,
            socket_connect_timeout=self.config.socket_connect_timeout,
            retry_on_timeout=self.config.retry_on_timeout,
            decode_responses=self.config.decode_responses,
        )
        self._client = Redis(connection_pool=self._pool)
    
    async def _connect_sentinel(self):
        """连接哨兵模式 Redis"""
        if not self.config.sentinel_hosts:
            raise ValueError("哨兵模式需要配置 sentinel_hosts")
        
        # 解析哨兵地址
        sentinel_list = []
        for host_str in self.config.sentinel_hosts:
            parts = host_str.split(':')
            host = parts[0]
            port = int(parts[1]) if len(parts) > 1 else 26379
            sentinel_list.append((host, port))
        
        # 创建 Sentinel 客户端
        self._sentinel = Sentinel(
            sentinel_list,
            socket_timeout=self.config.socket_timeout,
            password=self.config.password,
            decode_responses=self.config.decode_responses,
        )
        
        # 获取 Master 连接
        self._client = self._sentinel.master_for(
            self.config.sentinel_master_name,
            socket_timeout=self.config.socket_timeout,
        )
    
    async def disconnect(self) -> bool:
        """
        断开 Redis 连接
        
        Returns:
            是否断开成功
        """
        try:
            if self._client:
                await self._client.close()
            
            if self._pool:
                await self._pool.disconnect()
            
            self._is_connected = False
            logger.info("Redis 连接已断开")
            return True
            
        except Exception as e:
            logger.error(f"Redis 断开连接失败: {e}")
            return False
    
    @property
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._is_connected
    
    @property
    def client(self) -> Redis:
        """获取 Redis 客户端"""
        if not self._client:
            raise RuntimeError("Redis 客户端未初始化，请先调用 connect()")
        return self._client
    
    # ==================== 基础操作 ====================
    
    @retry(
        stop=stop_after_attempt(CacheConfig.MAX_RETRIES),
        wait=wait_exponential(
            multiplier=CacheConfig.RETRY_WAIT_BASE,
            max=CacheConfig.RETRY_WAIT_MAX
        ),
        retry=retry_if_exception_type((RedisError, RedisTimeoutError)),
        reraise=True
    )
    async def get(self, key: str) -> Optional[str]:
        """
        获取缓存（带重试）
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，不存在返回 None
        """
        try:
            return await self.client.get(key)
        except (RedisError, RedisTimeoutError) as e:
            logger.warning(f"Redis GET 失败: {key}, 错误: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(CacheConfig.MAX_RETRIES),
        wait=wait_exponential(
            multiplier=CacheConfig.RETRY_WAIT_BASE,
            max=CacheConfig.RETRY_WAIT_MAX
        ),
        retry=retry_if_exception_type((RedisError, RedisTimeoutError)),
        reraise=True
    )
    async def set(
        self,
        key: str,
        value: str,
        ex: Optional[int] = None,
        nx: bool = False
    ) -> bool:
        """
        设置缓存（带重试）
        
        Args:
            key: 缓存键
            value: 缓存值
            ex: 过期时间（秒）
            nx: 仅当键不存在时设置
            
        Returns:
            是否设置成功
        """
        try:
            if nx:
                result = await self.client.set(key, value, ex=ex, nx=True)
                return result is not None
            else:
                await self.client.set(key, value, ex=ex)
                return True
        except (RedisError, RedisTimeoutError) as e:
            logger.warning(f"Redis SET 失败: {key}, 错误: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(CacheConfig.MAX_RETRIES),
        wait=wait_exponential(
            multiplier=CacheConfig.RETRY_WAIT_BASE,
            max=CacheConfig.RETRY_WAIT_MAX
        ),
        retry=retry_if_exception_type((RedisError, RedisTimeoutError)),
        reraise=True
    )
    async def delete(self, *keys: str) -> int:
        """
        删除缓存（带重试）
        
        Args:
            keys: 缓存键列表
            
        Returns:
            删除的键数量
        """
        try:
            return await self.client.delete(*keys)
        except (RedisError, RedisTimeoutError) as e:
            logger.warning(f"Redis DELETE 失败: {keys}, 错误: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(CacheConfig.MAX_RETRIES),
        wait=wait_exponential(
            multiplier=CacheConfig.RETRY_WAIT_BASE,
            max=CacheConfig.RETRY_WAIT_MAX
        ),
        retry=retry_if_exception_type((RedisError, RedisTimeoutError)),
        reraise=True
    )
    async def exists(self, *keys: str) -> int:
        """
        检查键是否存在（带重试）
        
        Args:
            keys: 缓存键列表
            
        Returns:
            存在的键数量
        """
        try:
            return await self.client.exists(*keys)
        except (RedisError, RedisTimeoutError) as e:
            logger.warning(f"Redis EXISTS 失败: {keys}, 错误: {e}")
            raise
    
    async def scan_iter(self, match: str, count: int = 100):
        """
        迭代扫描键（用于批量操作）
        
        Args:
            match: 匹配模式
            count: 每次扫描数量
            
        Yields:
            匹配的键
        """
        async for key in self.client.scan_iter(match=match, count=count):
            yield key
    
    # ==================== 健康检查 ====================
    
    async def ping(self) -> bool:
        """
        健康检查
        
        Returns:
            是否健康
        """
        try:
            result = await self.client.ping()
            return result is True
        except Exception as e:
            logger.error(f"Redis 健康检查失败: {e}")
            return False
    
    async def get_info(self) -> dict:
        """
        获取 Redis 信息
        
        Returns:
            Redis 信息字典
        """
        try:
            info = await self.client.info()
            return info
        except Exception as e:
            logger.error(f"获取 Redis 信息失败: {e}")
            return {}
    
    async def get_memory_usage(self) -> dict:
        """
        获取内存使用情况
        
        Returns:
            内存使用信息
        """
        try:
            info = await self.client.info("memory")
            return {
                "used_memory": info.get("used_memory", 0),
                "used_memory_human": info.get("used_memory_human", "0B"),
                "used_memory_peak": info.get("used_memory_peak", 0),
                "used_memory_peak_human": info.get("used_memory_peak_human", "0B"),
            }
        except Exception as e:
            logger.error(f"获取内存使用失败: {e}")
            return {}
    
    async def get_keys_count(self) -> int:
        """
        获取键数量
        
        Returns:
            键数量
        """
        try:
            return await self.client.dbsize()
        except Exception as e:
            logger.error(f"获取键数量失败: {e}")
            return 0


# 全局 Redis 客户端实例
_redis_client: Optional[RedisClient] = None


async def get_redis_client(config: Optional[RedisConfig] = None) -> RedisClient:
    """
    获取全局 Redis 客户端实例
    
    Args:
        config: Redis 配置（首次调用时需要）
        
    Returns:
        Redis 客户端实例
    """
    global _redis_client
    
    if _redis_client is None:
        if config is None:
            config = RedisConfig()
        _redis_client = RedisClient(config)
        await _redis_client.connect()
    
    return _redis_client


async def close_redis_client():
    """关闭全局 Redis 客户端"""
    global _redis_client
    
    if _redis_client:
        await _redis_client.disconnect()
        _redis_client = None
