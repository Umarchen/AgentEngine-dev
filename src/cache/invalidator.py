"""
缓存失效广播模块
使用 Redis Pub/Sub 实现多实例间的缓存失效通知

对应需求：
- [REQ_REDIS_CACHE_001] 缓存一致性保障
"""

import asyncio
import json
import time
from typing import Callable, Optional

from loguru import logger


class CacheInvalidator:
    """
    缓存失效广播器
    
    功能：
    1. 发布缓存失效消息到 Redis Pub/Sub
    2. 订阅并处理失效消息
    3. 管理本地缓存清理
    4. 支持自定义失效回调
    
    使用场景：
    - 多实例部署时保持缓存一致性
    - 配置更新时通知所有实例失效本地缓存
    
    Example:
        >>> invalidator = CacheInvalidator(redis_client, local_cache)
        >>> await invalidator.start()
        >>> await invalidator.publish_invalidation("agent:config:123")
    """
    
    # Pub/Sub 通道名称
    CHANNEL_NAME = "agent_engine:cache:invalidate"
    
    def __init__(
        self,
        redis_client,
        local_cache,
        on_invalidate: Optional[Callable[[str], None]] = None
    ):
        """
        初始化缓存失效器
        
        Args:
            redis_client: Redis 异步客户端（redis.asyncio.Redis）
            local_cache: 本地缓存实例（LocalCache）
            on_invalidate: 自定义失效回调函数
        """
        self.redis_client = redis_client
        self.local_cache = local_cache
        self.on_invalidate = on_invalidate
        
        self._pubsub = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # 统计信息
        self._published_count = 0
        self._received_count = 0
        self._error_count = 0
    
    async def start(self) -> None:
        """启动订阅监听"""
        if self._running:
            logger.warning("缓存失效订阅已在运行中")
            return
        
        try:
            self._running = True
            self._pubsub = self.redis_client.pubsub()
            await self._pubsub.subscribe(self.CHANNEL_NAME)
            
            # 启动监听任务
            self._task = asyncio.create_task(self._listen_loop())
            logger.info(f"缓存失效订阅已启动，通道: {self.CHANNEL_NAME}")
            
        except Exception as e:
            self._running = False
            logger.error(f"启动缓存失效订阅失败: {e}")
            raise
    
    async def stop(self) -> None:
        """停止订阅监听"""
        self._running = False
        
        try:
            if self._pubsub:
                await self._pubsub.unsubscribe(self.CHANNEL_NAME)
                await self._pubsub.close()
                self._pubsub = None
            
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None
            
            logger.info("缓存失效订阅已停止")
            
        except Exception as e:
            logger.error(f"停止缓存失效订阅失败: {e}")
    
    async def publish_invalidation(self, cache_key: str) -> bool:
        """
        发布缓存失效消息
        
        Args:
            cache_key: 需要失效的缓存键
            
        Returns:
            是否发布成功
        """
        try:
            message = json.dumps({
                "key": cache_key,
                "timestamp": time.time()
            })
            
            result = await self.redis_client.publish(
                self.CHANNEL_NAME,
                message
            )
            
            self._published_count += 1
            logger.info(f"发布缓存失效消息: {cache_key}, 接收实例数: {result}")
            return True
            
        except Exception as e:
            self._error_count += 1
            logger.error(f"发布缓存失效消息失败: {e}")
            return False
    
    async def publish_batch_invalidation(self, cache_keys: list) -> int:
        """
        批量发布缓存失效消息
        
        Args:
            cache_keys: 需要失效的缓存键列表
            
        Returns:
            成功发布的数量
        """
        success_count = 0
        
        for key in cache_keys:
            if await self.publish_invalidation(key):
                success_count += 1
        
        return success_count
    
    async def _listen_loop(self) -> None:
        """监听循环"""
        logger.info("缓存失效监听循环已启动")
        
        try:
            while self._running:
                try:
                    message = await self._pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0
                    )
                    
                    if message:
                        await self._handle_message(message)
                        
                except asyncio.CancelledError:
                    logger.info("监听任务被取消")
                    break
                except Exception as e:
                    self._error_count += 1
                    logger.error(f"监听异常: {e}")
                    # 短暂等待后重试
                    await asyncio.sleep(1.0)
                    
        except Exception as e:
            logger.error(f"监听循环异常退出: {e}")
        finally:
            logger.info("缓存失效监听循环已退出")
    
    async def _handle_message(self, message: dict) -> None:
        """
        处理失效消息
        
        Args:
            message: Redis 消息
        """
        try:
            data = json.loads(message["data"])
            cache_key = data["key"]
            timestamp = data.get("timestamp", 0)
            
            self._received_count += 1
            logger.info(
                f"收到缓存失效消息: {cache_key}, "
                f"时间戳: {timestamp}, 延迟: {time.time() - timestamp:.3f}s"
            )
            
            # 删除本地缓存
            if self.local_cache:
                deleted = self.local_cache.delete(cache_key)
                if deleted:
                    logger.debug(f"本地缓存已删除: {cache_key}")
            
            # 触发自定义回调
            if self.on_invalidate:
                try:
                    if asyncio.iscoroutinefunction(self.on_invalidate):
                        await self.on_invalidate(cache_key)
                    else:
                        self.on_invalidate(cache_key)
                except Exception as e:
                    logger.error(f"失效回调执行失败: {e}")
                    
        except json.JSONDecodeError as e:
            logger.error(f"解析失效消息失败: {e}")
        except Exception as e:
            self._error_count += 1
            logger.error(f"处理失效消息失败: {e}")
    
    def get_stats(self) -> dict:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "running": self._running,
            "channel": self.CHANNEL_NAME,
            "published_count": self._published_count,
            "received_count": self._received_count,
            "error_count": self._error_count,
        }
    
    @property
    def is_running(self) -> bool:
        """检查订阅是否在运行"""
        return self._running


class CacheInvalidatorSync:
    """
    同步版本的缓存失效广播器
    
    用于不支持异步的场景
    """
    
    CHANNEL_NAME = "agent_engine:cache:invalidate"
    
    def __init__(
        self,
        redis_client,
        local_cache,
        on_invalidate: Optional[Callable[[str], None]] = None
    ):
        """
        初始化同步缓存失效器
        
        Args:
            redis_client: Redis 同步客户端
            local_cache: 本地缓存实例
            on_invalidate: 自定义失效回调函数
        """
        self.redis_client = redis_client
        self.local_cache = local_cache
        self.on_invalidate = on_invalidate
        self._running = False
    
    def publish_invalidation(self, cache_key: str) -> bool:
        """
        发布缓存失效消息（同步）
        
        Args:
            cache_key: 需要失效的缓存键
            
        Returns:
            是否发布成功
        """
        try:
            import json
            import time
            
            message = json.dumps({
                "key": cache_key,
                "timestamp": time.time()
            })
            
            result = self.redis_client.publish(self.CHANNEL_NAME, message)
            logger.info(f"发布缓存失效消息: {cache_key}, 接收实例数: {result}")
            return True
            
        except Exception as e:
            logger.error(f"发布缓存失效消息失败: {e}")
            return False
    
    def handle_invalidation(self, cache_key: str) -> None:
        """
        处理失效消息（同步）
        
        Args:
            cache_key: 需要失效的缓存键
        """
        try:
            # 删除本地缓存
            if self.local_cache:
                self.local_cache.delete(cache_key)
            
            # 触发回调
            if self.on_invalidate:
                self.on_invalidate(cache_key)
                
        except Exception as e:
            logger.error(f"处理失效消息失败: {e}")
