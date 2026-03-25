"""
CacheInvalidator 单元测试
测试消息发布/订阅、本地缓存清理回调

对应需求：[REQ_REDIS_CACHE_001] 缓存一致性保障（增强/修复）
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

# 添加项目路径
import sys
sys.path.insert(0, '/home/ubuntu/vrt-projects/projects/AgentEngine-dev/.staging/src')

# 直接导入模块，避免 Prometheus 指标重复注册
import importlib.util
spec = importlib.util.spec_from_file_location("cache_invalidator", "/home/ubuntu/vrt-projects/projects/AgentEngine-dev/.staging/src/cache/cache_invalidator.py")
cache_invalidator_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache_invalidator_module)
CacheInvalidator = cache_invalidator_module.CacheInvalidator


class TestCacheInvalidatorBasic:
    """CacheInvalidator 基础功能测试"""
    
    def test_init(self):
        """测试初始化"""
        mock_redis = MagicMock()
        clear_func = MagicMock(return_value=True)
        
        invalidator = CacheInvalidator(
            redis_client=mock_redis,
            local_cache_clear_func=clear_func,
            instance_id="test-instance"
        )
        
        assert invalidator.instance_id == "test-instance"
        assert invalidator.INVALIDATION_CHANNEL == "cache:invalidation"
    
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        """测试启动和停止"""
        mock_redis = MagicMock()
        mock_pubsub = AsyncMock()
        mock_redis.get_connection.return_value.pubsub.return_value = mock_pubsub
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()
        
        clear_func = MagicMock(return_value=True)
        
        invalidator = CacheInvalidator(
            redis_client=mock_redis,
            local_cache_clear_func=clear_func,
            instance_id="test-instance"
        )
        
        # 启动
        result = await invalidator.start()
        assert result is True
        assert invalidator._running is True
        
        # 停止
        await invalidator.stop()
        assert invalidator._running is False


class TestCacheInvalidatorPublish:
    """CacheInvalidator 消息发布测试"""
    
    @pytest.mark.asyncio
    async def test_publish_invalidation(self):
        """测试发布失效消息"""
        mock_redis = MagicMock()
        mock_connection = AsyncMock()
        mock_redis.get_connection.return_value = mock_connection
        mock_connection.publish = AsyncMock()
        
        clear_func = MagicMock(return_value=True)
        
        invalidator = CacheInvalidator(
            redis_client=mock_redis,
            local_cache_clear_func=clear_func,
            instance_id="test-instance"
        )
        
        # 发布失效消息
        result = await invalidator.publish_invalidation(["key1", "key2"])
        
        assert result is True
        mock_connection.publish.assert_called_once()
        
        stats = invalidator.get_stats()
        assert stats["messages_published"] == 1
    
    @pytest.mark.asyncio
    async def test_invalidate_key(self):
        """测试失效单个键"""
        mock_redis = MagicMock()
        mock_connection = AsyncMock()
        mock_redis.get_connection.return_value = mock_connection
        mock_connection.publish = AsyncMock()
        
        clear_func = MagicMock(return_value=True)
        
        invalidator = CacheInvalidator(
            redis_client=mock_redis,
            local_cache_clear_func=clear_func
        )
        
        result = await invalidator.invalidate_key("test_key")
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_invalidate_keys(self):
        """测试失效多个键"""
        mock_redis = MagicMock()
        mock_connection = AsyncMock()
        mock_redis.get_connection.return_value = mock_connection
        mock_connection.publish = AsyncMock()
        
        clear_func = MagicMock(return_value=True)
        
        invalidator = CacheInvalidator(
            redis_client=mock_redis,
            local_cache_clear_func=clear_func
        )
        
        result = await invalidator.invalidate_keys(["key1", "key2", "key3"])
        
        assert result is True


class TestCacheInvalidatorSubscribe:
    """CacheInvalidator 消息订阅测试"""
    
    @pytest.mark.asyncio
    async def test_handle_message(self):
        """测试处理接收到的消息"""
        mock_redis = MagicMock()
        clear_func = MagicMock(return_value=True)
        
        invalidator = CacheInvalidator(
            redis_client=mock_redis,
            local_cache_clear_func=clear_func,
            instance_id="instance-1"
        )
        
        # 模拟消息（来自其他实例）
        message = {
            "type": "message",
            "data": json.dumps({
                "instance_id": "instance-2",
                "keys": ["key1", "key2"]
            }).encode("utf-8")
        }
        
        await invalidator._handle_message(message)
        
        # 应该调用清理函数
        assert clear_func.call_count == 2
        
        stats = invalidator.get_stats()
        assert stats["messages_received"] == 1
        assert stats["invalidations_applied"] == 2
    
    @pytest.mark.asyncio
    async def test_skip_own_messages(self):
        """测试跳过自己发送的消息"""
        mock_redis = MagicMock()
        clear_func = MagicMock(return_value=True)
        
        invalidator = CacheInvalidator(
            redis_client=mock_redis,
            local_cache_clear_func=clear_func,
            instance_id="instance-1"
        )
        
        # 模拟自己的消息
        message = {
            "type": "message",
            "data": json.dumps({
                "instance_id": "instance-1",  # 同一个实例
                "keys": ["key1", "key2"]
            }).encode("utf-8")
        }
        
        await invalidator._handle_message(message)
        
        # 不应该调用清理函数
        assert clear_func.call_count == 0
    
    @pytest.mark.asyncio
    async def test_handle_invalid_message(self):
        """测试处理无效消息"""
        mock_redis = MagicMock()
        clear_func = MagicMock(return_value=True)
        
        invalidator = CacheInvalidator(
            redis_client=mock_redis,
            local_cache_clear_func=clear_func
        )
        
        # 无效的 JSON
        message = {
            "type": "message",
            "data": b"invalid json"
        }
        
        # 不应该抛出异常
        await invalidator._handle_message(message)
        
        stats = invalidator.get_stats()
        assert stats["errors"] == 1


class TestCacheInvalidatorStats:
    """CacheInvalidator 统计信息测试"""
    
    def test_get_stats(self):
        """测试获取统计信息"""
        mock_redis = MagicMock()
        clear_func = MagicMock(return_value=True)
        
        invalidator = CacheInvalidator(
            redis_client=mock_redis,
            local_cache_clear_func=clear_func,
            instance_id="test-instance"
        )
        
        stats = invalidator.get_stats()
        
        assert stats["instance_id"] == "test-instance"
        assert stats["channel"] == "cache:invalidation"
        assert stats["running"] is False
        assert stats["messages_published"] == 0
        assert stats["messages_received"] == 0
        assert stats["invalidations_applied"] == 0
        assert stats["errors"] == 0


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
