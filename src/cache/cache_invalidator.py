"""
缓存失效广播模块
基于 Redis Pub/Sub 实现多实例缓存失效广播
"""

import asyncio
import json
from typing import Optional, Set, Callable, Any
from loguru import logger

# 假设 RedisClient 已经存在
from .redis_client import RedisClient


class CacheInvalidator:
    """
    缓存失效广播器
    
    功能：
    1. 使用 Redis Pub/Sub 实现缓存失效消息广播
    2. 订阅失效消息并删除本地缓存
    3. 支持多实例部署环境
    
    对应需求：[REQ_REDIS_CACHE_001] 缓存一致性保障（增强/修复）
    """
    
    # Pub/Sub 频道名称
    INVALIDATION_CHANNEL = "cache:invalidation"
    
    def __init__(
        self,
        redis_client: RedisClient,
        local_cache_clear_func: Callable[[str], bool],
        instance_id: Optional[str] = None
    ):
        """
        初始化缓存失效广播器
        
        Args:
            redis_client: Redis 客户端
            local_cache_clear_func: 本地缓存清除函数（传入键名）
            instance_id: 实例 ID（可选，用于日志）
        """
        self.redis_client = redis_client
        self.local_cache_clear_func = local_cache_clear_func
        self.instance_id = instance_id or "unknown"
        
        # 订阅管理
        self._pubsub = None
        self._subscriber_task: Optional[asyncio.Task] = None
        self._running = False
        
        # 统计信息
        self._stats = {
            "messages_published": 0,
            "messages_received": 0,
            "invalidations_applied": 0,
            "errors": 0
        }
        
        logger.info(
            f"CacheInvalidator 初始化 - instance_id={instance_id}, "
            f"channel={self.INVALIDATION_CHANNEL}"
        )
    
    async def start(self):
        """
        启动订阅者
        
        Returns:
            是否启动成功
        """
        if self._running:
            logger.warning("CacheInvalidator 已经在运行")
            return True
        
        try:
            # 创建 Pub/Sub 连接
            self._pubsub = self.redis_client.get_connection().pubsub()
            await self._pubsub.subscribe(self.INVALIDATION_CHANNEL)
            
            # 启动后台订阅任务
            self._running = True
            self._subscriber_task = asyncio.create_task(
                self._subscriber_loop()
            )
            
            logger.info(f"CacheInvalidator 订阅已启动 - channel={self.INVALIDATION_CHANNEL}")
            return True
        
        except Exception as e:
            logger.error(f"CacheInvalidator 启动失败: {e}")
            self._stats["errors"] += 1
            return False
    
    async def stop(self):
        """
        停止订阅者
        """
        self._running = False
        
        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass
            self._subscriber_task = None
        
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe(self.INVALIDATION_CHANNEL)
                await self._pubsub.close()
            except Exception as e:
                logger.warning(f"CacheInvalidator 关闭 PubSub 时出错: {e}")
            self._pubsub = None
        
        logger.info("CacheInvalidator 已停止")
    
    async def _subscriber_loop(self):
        """
        订阅者循环（后台任务）
        """
        logger.info("CacheInvalidator 订阅者循环已启动")
        
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
                    break
                except Exception as e:
                    logger.error(f"CacheInvalidator 订阅者循环错误: {e}")
                    self._stats["errors"] += 1
                    await asyncio.sleep(1)  # 错误后等待 1 秒
        
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("CacheInvalidator 订阅者循环已停止")
    
    async def _handle_message(self, message: dict):
        """
        处理接收到的消息
        
        Args:
            message: Pub/Sub 消息
        """
        try:
            if message.get("type") != "message":
                return
            
            self._stats["messages_received"] += 1
            
            # 解析消息
            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            
            payload = json.loads(data)
            
            # 检查是否是自己发送的消息（跳过）
            if payload.get("instance_id") == self.instance_id:
                logger.debug("跳过自己发送的失效消息")
                return
            
            # 提取失效键
            keys = payload.get("keys", [])
            if not keys:
                return
            
            logger.info(
                f"CacheInvalidator 收到失效消息 - keys={len(keys)}, "
                f"from={payload.get('instance_id')}"
            )
            
            # 删除本地缓存
            for key in keys:
                try:
                    self.local_cache_clear_func(key)
                    self._stats["invalidations_applied"] += 1
                except Exception as e:
                    logger.warning(f"删除本地缓存失败: {key}, 错误: {e}")
            
            logger.info(
                f"CacheInvalidator 失效应用完成 - keys={len(keys)}"
            )
        
        except json.JSONDecodeError as e:
            logger.error(f"CacheInvalidator 消息解析失败: {e}")
            self._stats["errors"] += 1
        except Exception as e:
            logger.error(f"CacheInvalidator 消息处理失败: {e}")
            self._stats["errors"] += 1
    
    async def publish_invalidation(self, keys: list):
        """
        发布缓存失效消息
        
        Args:
            keys: 要失效的缓存键列表
            
        Returns:
            是否发布成功
        """
        if not keys:
            return True
        
        try:
            # 构建消息
            payload = {
                "instance_id": self.instance_id,
                "keys": keys,
                "timestamp": asyncio.get_event_loop().time()
            }
            
            message = json.dumps(payload)
            
            # 发布消息
            connection = self.redis_client.get_connection()
            await connection.publish(self.INVALIDATION_CHANNEL, message)
            
            self._stats["messages_published"] += 1
            
            logger.info(
                f"CacheInvalidator 发布失效消息 - keys={len(keys)}"
            )
            
            return True
        
        except Exception as e:
            logger.error(f"CacheInvalidator 发布失败: {e}")
            self._stats["errors"] += 1
            return False
    
    async def invalidate_key(self, key: str) -> bool:
        """
        失效单个缓存键
        
        Args:
            key: 缓存键
            
        Returns:
            是否成功
        """
        return await self.publish_invalidation([key])
    
    async def invalidate_keys(self, keys: list) -> bool:
        """
        失效多个缓存键
        
        Args:
            keys: 缓存键列表
            
        Returns:
            是否成功
        """
        return await self.publish_invalidation(keys)
    
    def get_stats(self) -> dict:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "instance_id": self.instance_id,
            "channel": self.INVALIDATION_CHANNEL,
            "running": self._running,
            **self._stats
        }


# 全局单例（可选）
_cache_invalidator_instance: Optional[CacheInvalidator] = None


async def get_cache_invalidator(
    redis_client: RedisClient,
    local_cache_clear_func: Callable[[str], bool],
    instance_id: Optional[str] = None,
    reset: bool = False
) -> CacheInvalidator:
    """
    获取缓存失效广播器单例
    
    Args:
        redis_client: Redis 客户端
        local_cache_clear_func: 本地缓存清除函数
        instance_id: 实例 ID
        reset: 是否重置单例
        
    Returns:
        CacheInvalidator 实例
    """
    global _cache_invalidator_instance
    
    if _cache_invalidator_instance is None or reset:
        _cache_invalidator_instance = CacheInvalidator(
            redis_client=redis_client,
            local_cache_clear_func=local_cache_clear_func,
            instance_id=instance_id
        )
    
    return _cache_invalidator_instance
