"""
集成测试
测试多级缓存一致性、熔断器集成、批量操作集成

对应需求：多个需求的集成验证
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

# 添加项目路径
import sys
sys.path.insert(0, '/home/ubuntu/vrt-projects/projects/AgentEngine-dev/.staging/src')

# 直接导入模块，避免 Prometheus 指标重复注册
import importlib.util

# LocalCache
spec = importlib.util.spec_from_file_location("local_cache", "/home/ubuntu/vrt-projects/projects/AgentEngine-dev/.staging/src/cache/local_cache.py")
local_cache_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local_cache_module)
LocalCache = local_cache_module.LocalCache

# CircuitBreaker
spec = importlib.util.spec_from_file_location("circuit_breaker", "/home/ubuntu/vrt-projects/projects/AgentEngine-dev/.staging/src/cache/circuit_breaker.py")
circuit_breaker_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(circuit_breaker_module)
CircuitBreaker = circuit_breaker_module.CircuitBreaker
CircuitState = circuit_breaker_module.CircuitState


class TestCircuitBreakerIntegration:
    """熔断器集成测试"""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_with_local_cache(self):
        """测试熔断器与本地缓存集成"""
        # 创建本地缓存
        local_cache = LocalCache(maxsize=100, ttl=60.0)
        
        # 创建熔断器
        circuit_breaker = CircuitBreaker(
            name="test",
            error_threshold_percent=50.0,
            time_window_seconds=5,
            recovery_timeout_seconds=2
        )
        
        # 预热本地缓存
        local_cache.set("key1", {"data": "cached"})
        
        # 模拟失败的远程调用
        call_count = 0
        
        async def flaky_remote_call(key):
            nonlocal call_count
            call_count += 1
            if call_count <= 6:
                raise Exception("Remote error")
            return {"data": "remote"}
        
        # 触发熔断
        for i in range(6):
            try:
                await circuit_breaker.call(flaky_remote_call, "key1")
            except Exception:
                pass
        
        # 熔断器应该打开
        assert circuit_breaker.is_open
        
        # 降级：从本地缓存获取
        value = local_cache.get("key1")
        assert value == {"data": "cached"}
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery_flow(self):
        """测试熔断器恢复流程"""
        circuit_breaker = CircuitBreaker(
            error_threshold_percent=50.0,
            time_window_seconds=1,
            recovery_timeout_seconds=1,
            half_open_max_calls=2
        )
        
        # 阶段 1：触发熔断
        for i in range(10):
            try:
                async def fail():
                    raise ValueError("error")
                await circuit_breaker.call(fail)
            except ValueError:
                pass
        
        assert circuit_breaker.is_open
        
        # 阶段 2：等待恢复
        await asyncio.sleep(1.5)
        
        # 阶段 3：恢复（连续成功）
        async def success():
            return "ok"
        
        for i in range(2):
            result = await circuit_breaker.call(success)
            assert result == "ok"
        
        # 应该恢复
        assert circuit_breaker.is_closed


class TestLocalCacheIntegration:
    """本地缓存集成测试"""
    
    def test_cache_eviction_with_access_pattern(self):
        """测试基于访问模式的淘汰"""
        cache = LocalCache(maxsize=3, ttl=300.0)
        
        # 填充缓存
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        
        # 访问 key1（使其变为最近使用）
        cache.get("key1")
        
        # 添加新键
        cache.set("key4", "value4")
        
        # key2 应该被淘汰（key1 被访问过，key3 是最近添加的）
        assert cache.get("key1") == "value1"
        assert cache.get("key2") is None  # 被淘汰
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"
    
    @pytest.mark.asyncio
    async def test_concurrent_cache_operations(self):
        """测试并发缓存操作"""
        cache = LocalCache(maxsize=100, ttl=60.0)
        
        async def writer(start_idx):
            for i in range(start_idx, start_idx + 10):
                cache.set(f"key{i}", f"value{i}")
                await asyncio.sleep(0.001)
        
        async def reader():
            for i in range(50):
                cache.get(f"key{i}")
                await asyncio.sleep(0.001)
        
        # 并发执行
        tasks = [
            writer(0),
            writer(10),
            writer(20),
            reader()
        ]
        
        await asyncio.gather(*tasks)
        
        # 检查缓存大小
        assert cache.get_size() <= 100  # 不应该超过容量


class TestPerformanceIntegration:
    """性能集成测试"""
    
    @pytest.mark.asyncio
    async def test_high_throughput_operations(self):
        """测试高吞吐量操作"""
        cache = LocalCache(maxsize=1000, ttl=60.0)
        
        # 写入大量数据
        for i in range(500):
            cache.set(f"key{i}", {"data": f"value{i}"})
        
        # 并发读取
        async def read_batch(start, end):
            for i in range(start, end):
                cache.get(f"key{i}")
        
        tasks = [
            read_batch(0, 100),
            read_batch(100, 200),
            read_batch(200, 300),
            read_batch(300, 400)
        ]
        
        await asyncio.gather(*tasks)
        
        # 检查统计
        stats = cache.get_stats()
        assert stats["hits"] >= 300  # 至少 300 次命中
        assert stats["current_size"] <= 1000


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
