"""
缓存管理器测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from src.cache.cache_manager import CacheManager
from src.cache.redis_client import RedisClient
from src.cache.serializer import CacheSerializer
from src.cache.key_builder import CacheKeyBuilder


class TestModel(BaseModel):
    """测试模型"""
    id: str
    name: str


class TestCacheManager:
    """缓存管理器测试类"""
    
    @pytest.fixture
    def mock_redis_client(self):
        """创建 Mock Redis 客户端"""
        client = MagicMock(spec=RedisClient)
        client.is_connected = True
        client.get = AsyncMock()
        client.set = AsyncMock()
        client.delete = AsyncMock()
        client.exists = AsyncMock()
        client.scan_iter = AsyncMock()
        client.ping = AsyncMock(return_value=True)
        client.get_memory_usage = AsyncMock(return_value={
            "used_memory": 1024000,
            "used_memory_human": "1.0M",
        })
        client.get_keys_count = AsyncMock(return_value=100)
        return client
    
    @pytest.fixture
    def cache_manager(self, mock_redis_client):
        """创建缓存管理器"""
        return CacheManager(
            redis_client=mock_redis_client,
            serializer=CacheSerializer(),
            key_builder=CacheKeyBuilder(),
            enable_metrics=False  # 测试时禁用指标
        )
    
    @pytest.mark.asyncio
    async def test_get_success(self, cache_manager, mock_redis_client):
        """测试 GET 操作成功"""
        # Mock Redis 返回
        mock_redis_client.get.return_value = '{"id": "test", "name": "Test"}'
        
        result = await cache_manager.get("agent:config:test_agent")
        
        # 验证结果
        assert result is not None
        assert result["id"] == "test"
        assert result["name"] == "Test"
        
        # 验证调用
        mock_redis_client.get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_not_found(self, cache_manager, mock_redis_client):
        """测试 GET 操作未找到"""
        # Mock Redis 返回 None
        mock_redis_client.get.return_value = None
        
        result = await cache_manager.get("agent:config:nonexistent")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_with_model(self, cache_manager, mock_redis_client):
        """测试 GET 操作并反序列化为模型"""
        # Mock Redis 返回
        mock_redis_client.get.return_value = '{"id": "test", "name": "Test"}'
        
        result = await cache_manager.get(
            "agent:config:test",
            model_class=TestModel
        )
        
        assert isinstance(result, TestModel)
        assert result.id == "test"
        assert result.name == "Test"
    
    @pytest.mark.asyncio
    async def test_get_degradation(self, cache_manager, mock_redis_client):
        """测试 GET 操作降级（Redis 错误）"""
        from redis.exceptions import RedisError
        
        # Mock Redis 错误
        mock_redis_client.get.side_effect = RedisError("Connection error")
        
        result = await cache_manager.get("agent:config:test")
        
        # 应该返回 None（降级）
        assert result is None
        assert cache_manager.degradation_count == 1
    
    @pytest.mark.asyncio
    async def test_set_success(self, cache_manager, mock_redis_client):
        """测试 SET 操作成功"""
        mock_redis_client.set.return_value = True
        
        result = await cache_manager.set(
            "agent:config:test",
            {"id": "test", "name": "Test"},
            ttl=3600
        )
        
        assert result is True
        mock_redis_client.set.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_set_without_ttl(self, cache_manager, mock_redis_client):
        """测试 SET 操作无 TTL"""
        mock_redis_client.set.return_value = True
        
        result = await cache_manager.set(
            "agent:config:test",
            {"id": "test"}
        )
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_set_with_nx(self, cache_manager, mock_redis_client):
        """测试 SET NX 操作"""
        mock_redis_client.set.return_value = True
        
        result = await cache_manager.set(
            "agent:config:test",
            {"id": "test"},
            ttl=3600,
            nx=True
        )
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_delete_success(self, cache_manager, mock_redis_client):
        """测试 DELETE 操作成功"""
        mock_redis_client.delete.return_value = 1
        
        result = await cache_manager.delete("agent:config:test")
        
        assert result is True
        mock_redis_client.delete.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_delete_not_found(self, cache_manager, mock_redis_client):
        """测试 DELETE 操作键不存在"""
        mock_redis_client.delete.return_value = 0
        
        result = await cache_manager.delete("agent:config:nonexistent")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_delete_pattern(self, cache_manager, mock_redis_client):
        """测试批量删除"""
        # Mock scan_iter 返回
        async def mock_scan(*args, **kwargs):
            for key in ["agent_engine:agent:config:1", "agent_engine:agent:config:2"]:
                yield key
        
        mock_redis_client.scan_iter.return_value = mock_scan()
        mock_redis_client.delete.return_value = 2
        
        result = await cache_manager.delete_pattern("agent:config:*")
        
        assert result == 2
    
    @pytest.mark.asyncio
    async def test_exists_true(self, cache_manager, mock_redis_client):
        """测试 EXISTS 操作键存在"""
        mock_redis_client.exists.return_value = 1
        
        result = await cache_manager.exists("agent:config:test")
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_exists_false(self, cache_manager, mock_redis_client):
        """测试 EXISTS 操作键不存在"""
        mock_redis_client.exists.return_value = 0
        
        result = await cache_manager.exists("agent:config:nonexistent")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_get_with_fallback_cache_hit(self, cache_manager, mock_redis_client):
        """测试带降级的读取（缓存命中）"""
        mock_redis_client.get.return_value = '{"id": "test", "name": "Test"}'
        
        loader = AsyncMock(return_value={"id": "db", "name": "DB"})
        
        result = await cache_manager.get_with_fallback(
            "agent:config:test",
            loader=loader,
            ttl=3600
        )
        
        # 应该返回缓存值
        assert result["id"] == "test"
        # loader 不应该被调用
        loader.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_with_fallback_cache_miss(self, cache_manager, mock_redis_client):
        """测试带降级的读取（缓存未命中）"""
        # 缓存未命中
        mock_redis_client.get.return_value = None
        
        loader = AsyncMock(return_value={"id": "db", "name": "DB"})
        
        result = await cache_manager.get_with_fallback(
            "agent:config:test",
            loader=loader,
            ttl=3600
        )
        
        # 应该返回数据库值
        assert result["id"] == "db"
        # loader 应该被调用
        loader.assert_called_once()
        # fallback_count 应该增加
        assert cache_manager.fallback_count == 1
    
    @pytest.mark.asyncio
    async def test_get_with_fallback_none_result(self, cache_manager, mock_redis_client):
        """测试带降级的读取（数据库返回 None）"""
        # 缓存未命中
        mock_redis_client.get.return_value = None
        
        loader = AsyncMock(return_value=None)
        
        result = await cache_manager.get_with_fallback(
            "agent:config:nonexistent",
            loader=loader,
            ttl=3600
        )
        
        # 应该返回 None
        assert result is None
        # 不应该写入缓存
        mock_redis_client.set.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_stats(self, cache_manager, mock_redis_client):
        """测试获取统计信息"""
        stats = await cache_manager.get_stats()
        
        assert stats["connected"] is True
        assert stats["keys_count"] == 100
        assert "memory_used_mb" in stats
        assert stats["degradation_count"] == 0
    
    @pytest.mark.asyncio
    async def test_health_check_healthy(self, cache_manager, mock_redis_client):
        """测试健康检查（健康）"""
        mock_redis_client.ping.return_value = True
        
        health = await cache_manager.health_check()
        
        assert health["status"] == "healthy"
        assert health["connected"] is True
    
    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, cache_manager, mock_redis_client):
        """测试健康检查（不健康）"""
        mock_redis_client.ping.side_effect = Exception("Connection lost")
        
        health = await cache_manager.health_check()
        
        assert health["status"] == "unhealthy"
        assert health["connected"] is False
    
    def test_ttl_jitter(self, cache_manager):
        """测试 TTL 随机偏移"""
        base_ttl = 100
        
        # 多次调用，应该有不同的偏移
        ttls = [cache_manager._add_ttl_jitter(base_ttl) for _ in range(10)]
        
        # 应该有偏移（但不一定每次都不同）
        # 检查是否在合理范围内
        for ttl in ttls:
            assert 90 <= ttl <= 110  # ±10%
    
    @pytest.mark.asyncio
    async def test_metrics_disabled(self, mock_redis_client):
        """测试禁用指标"""
        manager = CacheManager(
            redis_client=mock_redis_client,
            enable_metrics=False
        )
        
        mock_redis_client.get.return_value = '{"id": "test"}'
        
        # 应该正常工作，不抛出异常
        result = await manager.get("test_key")
        
        assert result is not None
