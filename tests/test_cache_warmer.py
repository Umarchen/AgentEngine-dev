"""
CacheWarmer 单元测试
测试预热逻辑、异步执行、取消处理

对应需求：[REQ_REDIS_CACHE_004] 缓存预热功能（新增）
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

# 添加项目路径
import sys
sys.path.insert(0, '/home/ubuntu/vrt-projects/projects/AgentEngine-dev/.staging/src')

# 直接导入模块，避免 Prometheus 指标重复注册
import importlib.util
spec = importlib.util.spec_from_file_location("cache_warmer", "/home/ubuntu/vrt-projects/projects/AgentEngine-dev/.staging/src/cache/cache_warmer.py")
cache_warmer_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache_warmer_module)

CacheWarmer = cache_warmer_module.CacheWarmer
CacheWarmerStats = cache_warmer_module.CacheWarmerStats


class TestCacheWarmerBasic:
    """CacheWarmer 基础功能测试"""
    
    def test_init(self):
        """测试初始化"""
        mock_cache_manager = MagicMock()
        get_top_agents = MagicMock(return_value=[])
        
        warmer = CacheWarmer(
            cache_manager=mock_cache_manager,
            get_top_agents_func=get_top_agents,
            delay_seconds=30,
            top_n=10
        )
        
        assert warmer.delay_seconds == 30
        assert warmer.top_n == 10
    
    @pytest.mark.asyncio
    async def test_warmup_top_agents(self):
        """测试预热高频 Agent"""
        mock_cache_manager = AsyncMock()
        mock_cache_manager.get = AsyncMock(return_value={"data": "test"})
        
        get_top_agents = MagicMock(return_value=["agent1", "agent2", "agent3"])
        
        warmer = CacheWarmer(
            cache_manager=mock_cache_manager,
            get_top_agents_func=get_top_agents,
            top_n=10
        )
        
        result = await warmer.warmup_top_agents()
        
        assert result["total"] == 3
        assert result["success"] == 3
        assert result["failed"] == 0
    
    @pytest.mark.asyncio
    async def test_warmup_with_limit(self):
        """测试预热限制数量"""
        mock_cache_manager = AsyncMock()
        mock_cache_manager.get = AsyncMock(return_value={"data": "test"})
        
        get_top_agents = MagicMock(return_value=["agent1", "agent2", "agent3", "agent4", "agent5"])
        
        warmer = CacheWarmer(
            cache_manager=mock_cache_manager,
            get_top_agents_func=get_top_agents,
            top_n=3  # 只预热前 3 个
        )
        
        result = await warmer.warmup_top_agents()
        
        assert result["total"] == 3  # 应该只有 3 个
        assert mock_cache_manager.get.call_count == 3


class TestCacheWarmerAsync:
    """CacheWarmer 异步执行测试"""
    
    @pytest.mark.asyncio
    async def test_start_background_warmup(self):
        """测试启动后台预热"""
        mock_cache_manager = AsyncMock()
        get_top_agents = MagicMock(return_value=[])
        
        warmer = CacheWarmer(
            cache_manager=mock_cache_manager,
            get_top_agents_func=get_top_agents,
            delay_seconds=1
        )
        
        # 启动后台预热
        await warmer.start_background_warmup()
        
        # 检查任务是否启动
        assert warmer._warmup_task is not None
        assert not warmer._warmup_task.done()
        
        # 等待任务完成
        await asyncio.sleep(1.5)
        
        # 任务应该已完成
        assert warmer._warmup_task.done()
    
    @pytest.mark.asyncio
    async def test_delayed_warmup(self):
        """测试延迟预热"""
        mock_cache_manager = AsyncMock()
        mock_cache_manager.get = AsyncMock(return_value={"data": "test"})
        
        get_top_agents = MagicMock(return_value=["agent1"])
        
        warmer = CacheWarmer(
            cache_manager=mock_cache_manager,
            get_top_agents_func=get_top_agents,
            delay_seconds=2
        )
        
        # 启动后台预热
        start_time = asyncio.get_event_loop().time()
        await warmer.start_background_warmup()
        
        # 等待任务完成
        await asyncio.sleep(2.5)
        
        end_time = asyncio.get_event_loop().time()
        
        # 应该至少延迟了 2 秒
        assert (end_time - start_time) >= 2.0
        
        # 应该调用了 get 方法
        mock_cache_manager.get.assert_called()


class TestCacheWarmerCancel:
    """CacheWarmer 取消处理测试"""
    
    @pytest.mark.asyncio
    async def test_cancel_warmup(self):
        """测试取消预热"""
        mock_cache_manager = AsyncMock()
        get_top_agents = MagicMock(return_value=[])
        
        warmer = CacheWarmer(
            cache_manager=mock_cache_manager,
            get_top_agents_func=get_top_agents,
            delay_seconds=10  # 较长的延迟
        )
        
        # 启动后台预热
        await warmer.start_background_warmup()
        
        # 立即取消
        warmer.cancel()
        
        # 等待一小段时间
        await asyncio.sleep(0.5)
        
        # 任务应该已完成（被取消）
        assert warmer._warmup_task.done()


class TestCacheWarmerStats:
    """CacheWarmer 统计信息测试"""
    
    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """测试统计信息追踪"""
        mock_cache_manager = AsyncMock()
        mock_cache_manager.get = AsyncMock(return_value={"data": "test"})
        
        get_top_agents = MagicMock(return_value=["agent1", "agent2"])
        
        warmer = CacheWarmer(
            cache_manager=mock_cache_manager,
            get_top_agents_func=get_top_agents
        )
        
        # 执行预热
        await warmer.warmup_top_agents()
        
        stats = warmer.get_stats()
        
        assert stats["total_warmups"] == 1
        assert stats["success_count"] == 2
        assert stats["failure_count"] == 0
    
    @pytest.mark.asyncio
    async def test_failure_stats(self):
        """测试失败统计"""
        mock_cache_manager = AsyncMock()
        mock_cache_manager.get = AsyncMock(side_effect=Exception("error"))
        
        get_top_agents = MagicMock(return_value=["agent1"])
        
        warmer = CacheWarmer(
            cache_manager=mock_cache_manager,
            get_top_agents_func=get_top_agents
        )
        
        # 执行预热
        result = await warmer.warmup_top_agents()
        
        assert result["failed"] == 1
        
        stats = warmer.get_stats()
        assert stats["failure_count"] == 1


class TestCacheWarmerManualWarmup:
    """CacheWarmer 手动预热测试"""
    
    @pytest.mark.asyncio
    async def test_warmup_keys(self):
        """测试手动预热指定键"""
        mock_cache_manager = AsyncMock()
        mock_cache_manager.get = AsyncMock(return_value={"data": "test"})
        
        get_top_agents = MagicMock(return_value=[])
        
        warmer = CacheWarmer(
            cache_manager=mock_cache_manager,
            get_top_agents_func=get_top_agents
        )
        
        result = await warmer.warmup_keys(["key1", "key2", "key3"])
        
        assert result["total"] == 3
        assert result["success"] == 3
        assert result["failed"] == 0


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
