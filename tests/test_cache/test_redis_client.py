"""
Redis 客户端测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError

from src.cache.redis_client import RedisClient, RedisConfig


class TestRedisClient:
    """Redis 客户端测试类"""
    
    @pytest.fixture
    def redis_config(self):
        """创建 Redis 配置"""
        return RedisConfig(
            host="127.0.0.1",
            port=6379,
            db=0,
            max_connections=50,
        )
    
    @pytest.fixture
    def redis_client(self, redis_config):
        """创建 Redis 客户端"""
        return RedisClient(redis_config)
    
    @pytest.mark.asyncio
    async def test_connect_standalone(self, redis_client):
        """测试单机模式连接"""
        # Mock Redis 连接
        with patch('src.cache.redis_client.ConnectionPool') as mock_pool, \
             patch('src.cache.redis_client.Redis') as mock_redis:
            
            mock_redis_instance = AsyncMock()
            mock_redis.return_value = mock_redis_instance
            
            result = await redis_client.connect()
            
            assert result is True
            assert redis_client.is_connected is True
    
    @pytest.mark.asyncio
    async def test_connect_failure(self, redis_client):
        """测试连接失败"""
        with patch('src.cache.redis_client.ConnectionPool') as mock_pool:
            mock_pool.side_effect = Exception("Connection failed")
            
            result = await redis_client.connect()
            
            assert result is False
            assert redis_client.is_connected is False
    
    @pytest.mark.asyncio
    async def test_disconnect(self, redis_client):
        """测试断开连接"""
        # 先连接
        with patch('src.cache.redis_client.ConnectionPool') as mock_pool, \
             patch('src.cache.redis_client.Redis') as mock_redis:
            
            mock_redis_instance = AsyncMock()
            mock_redis.return_value = mock_redis_instance
            await redis_client.connect()
            
            # 断开连接
            result = await redis_client.disconnect()
            
            assert result is True
            assert redis_client.is_connected is False
    
    @pytest.mark.asyncio
    async def test_get_success(self, redis_client):
        """测试 GET 操作成功"""
        # Mock Redis 客户端
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value="cached_value")
        redis_client._client = mock_client
        redis_client._is_connected = True
        
        result = await redis_client.get("test_key")
        
        assert result == "cached_value"
        mock_client.get.assert_called_once_with("test_key")
    
    @pytest.mark.asyncio
    async def test_get_not_found(self, redis_client):
        """测试 GET 操作未找到"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)
        redis_client._client = mock_client
        redis_client._is_connected = True
        
        result = await redis_client.get("nonexistent_key")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_with_retry(self, redis_client):
        """测试 GET 操作重试"""
        mock_client = AsyncMock()
        # 第一次失败，第二次成功
        mock_client.get = AsyncMock(
            side_effect=[
                RedisError("Connection error"),
                "cached_value"
            ]
        )
        redis_client._client = mock_client
        redis_client._is_connected = True
        
        result = await redis_client.get("test_key")
        
        # 重试后成功
        assert result == "cached_value"
        assert mock_client.get.call_count == 2
    
    @pytest.mark.asyncio
    async def test_set_success(self, redis_client):
        """测试 SET 操作成功"""
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(return_value=True)
        redis_client._client = mock_client
        redis_client._is_connected = True
        
        result = await redis_client.set("test_key", "test_value", ex=3600)
        
        assert result is True
        mock_client.set.assert_called_once_with(
            "test_key", "test_value", ex=3600, nx=False
        )
    
    @pytest.mark.asyncio
    async def test_set_with_nx(self, redis_client):
        """测试 SET NX 操作"""
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(return_value=True)
        redis_client._client = mock_client
        redis_client._is_connected = True
        
        result = await redis_client.set("test_key", "test_value", ex=3600, nx=True)
        
        assert result is True
        mock_client.set.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_delete_success(self, redis_client):
        """测试 DELETE 操作成功"""
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=2)
        redis_client._client = mock_client
        redis_client._is_connected = True
        
        result = await redis_client.delete("key1", "key2")
        
        assert result == 2
        mock_client.delete.assert_called_once_with("key1", "key2")
    
    @pytest.mark.asyncio
    async def test_exists_success(self, redis_client):
        """测试 EXISTS 操作成功"""
        mock_client = AsyncMock()
        mock_client.exists = AsyncMock(return_value=1)
        redis_client._client = mock_client
        redis_client._is_connected = True
        
        result = await redis_client.exists("test_key")
        
        assert result == 1
    
    @pytest.mark.asyncio
    async def test_ping_success(self, redis_client):
        """测试健康检查成功"""
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        redis_client._client = mock_client
        redis_client._is_connected = True
        
        result = await redis_client.ping()
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_ping_failure(self, redis_client):
        """测试健康检查失败"""
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(side_effect=Exception("Connection lost"))
        redis_client._client = mock_client
        redis_client._is_connected = True
        
        result = await redis_client.ping()
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_get_info(self, redis_client):
        """测试获取 Redis 信息"""
        mock_client = AsyncMock()
        mock_client.info = AsyncMock(return_value={
            "redis_version": "7.0.5",
            "connected_clients": 10,
        })
        redis_client._client = mock_client
        redis_client._is_connected = True
        
        info = await redis_client.get_info()
        
        assert info["redis_version"] == "7.0.5"
        assert info["connected_clients"] == 10
    
    @pytest.mark.asyncio
    async def test_get_memory_usage(self, redis_client):
        """测试获取内存使用"""
        mock_client = AsyncMock()
        mock_client.info = AsyncMock(return_value={
            "used_memory": 1024000,
            "used_memory_human": "1.0M",
        })
        redis_client._client = mock_client
        redis_client._is_connected = True
        
        memory = await redis_client.get_memory_usage()
        
        assert memory["used_memory"] == 1024000
        assert memory["used_memory_human"] == "1.0M"


class TestRedisConfig:
    """Redis 配置测试类"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = RedisConfig()
        
        assert config.host == "127.0.0.1"
        assert config.port == 6379
        assert config.db == 0
        assert config.max_connections == 50
    
    def test_custom_config(self):
        """测试自定义配置"""
        config = RedisConfig(
            host="192.168.1.100",
            port=6380,
            db=1,
            password="secret",
            max_connections=100,
        )
        
        assert config.host == "192.168.1.100"
        assert config.port == 6380
        assert config.db == 1
        assert config.password == "secret"
        assert config.max_connections == 100
    
    def test_sentinel_config(self):
        """测试哨兵模式配置"""
        config = RedisConfig(
            sentinel_enabled=True,
            sentinel_master_name="mymaster",
            sentinel_hosts=[
                "redis-sentinel-1:26379",
                "redis-sentinel-2:26379",
            ]
        )
        
        assert config.sentinel_enabled is True
        assert config.sentinel_master_name == "mymaster"
        assert len(config.sentinel_hosts) == 2
