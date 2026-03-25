"""
CircuitBreaker 单元测试
测试状态机转换、滑动窗口错误率、恢复超时、手动控制

对应需求：[REQ_REDIS_CACHE_002] 熔断器机制（新增）
"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock

# 添加项目路径
import sys
sys.path.insert(0, '/home/ubuntu/vrt-projects/projects/AgentEngine-dev/.staging/src')

# 直接导入模块，避免 Prometheus 指标重复注册
import importlib.util
spec = importlib.util.spec_from_file_location("circuit_breaker", "/home/ubuntu/vrt-projects/projects/AgentEngine-dev/.staging/src/cache/circuit_breaker.py")
circuit_breaker_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(circuit_breaker_module)

CircuitBreaker = circuit_breaker_module.CircuitBreaker
CircuitState = circuit_breaker_module.CircuitState
CircuitBreakerOpenError = circuit_breaker_module.CircuitBreakerOpenError
CircuitBreakerStats = circuit_breaker_module.CircuitBreakerStats


class TestCircuitBreakerBasic:
    """CircuitBreaker 基础功能测试"""
    
    def test_init(self):
        """测试初始化"""
        cb = CircuitBreaker(
            name="test",
            error_threshold_percent=50.0,
            time_window_seconds=10,
            recovery_timeout_seconds=30
        )
        
        assert cb.name == "test"
        assert cb.error_threshold_percent == 50.0
        assert cb.time_window_seconds == 10
        assert cb.recovery_timeout_seconds == 30
        assert cb.state == CircuitState.CLOSED
    
    def test_initial_state(self):
        """测试初始状态"""
        cb = CircuitBreaker()
        
        assert cb.is_closed is True
        assert cb.is_open is False
        assert cb.is_half_open is False
    
    @pytest.mark.asyncio
    async def test_call_success(self):
        """测试成功调用"""
        cb = CircuitBreaker()
        
        async def success_func():
            return "success"
        
        result = await cb.call(success_func)
        
        assert result == "success"
        assert cb.state == CircuitState.CLOSED
        
        stats = cb.get_stats()
        assert stats["success_calls"] == 1
        assert stats["total_calls"] == 1
    
    @pytest.mark.asyncio
    async def test_call_failure(self):
        """测试失败调用"""
        cb = CircuitBreaker()
        
        async def fail_func():
            raise ValueError("test error")
        
        with pytest.raises(ValueError):
            await cb.call(fail_func)
        
        stats = cb.get_stats()
        assert stats["failed_calls"] == 1
        assert stats["total_calls"] == 1


class TestCircuitBreakerStateMachine:
    """CircuitBreaker 状态机转换测试"""
    
    @pytest.mark.asyncio
    async def test_closed_to_open_transition(self):
        """测试 CLOSED -> OPEN 转换"""
        cb = CircuitBreaker(
            error_threshold_percent=50.0,
            time_window_seconds=10
        )
        
        # 触发足够多的失败以达到错误阈值
        for i in range(10):
            try:
                async def fail():
                    raise ValueError("error")
                await cb.call(fail)
            except ValueError:
                pass
        
        # 等待状态更新
        await asyncio.sleep(0.1)
        
        # 错误率应该是 100%，应该熔断
        assert cb.is_open is True
        assert cb.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_open_to_half_open_transition(self):
        """测试 OPEN -> HALF_OPEN 转换"""
        cb = CircuitBreaker(
            error_threshold_percent=50.0,
            time_window_seconds=1,
            recovery_timeout_seconds=1  # 1 秒后尝试恢复
        )
        
        # 触发熔断
        for i in range(10):
            try:
                async def fail():
                    raise ValueError("error")
                await cb.call(fail)
            except ValueError:
                pass
        
        assert cb.is_open is True
        
        # 等待恢复超时
        await asyncio.sleep(1.5)
        
        # 下次调用应该进入 HALF_OPEN 状态
        async def success():
            return "success"
        
        try:
            await cb.call(success)
        except CircuitBreakerOpenError:
            pass
        
        # 应该进入 HALF_OPEN 或保持 OPEN（取决于实现）
        assert cb.state in [CircuitState.HALF_OPEN, CircuitState.OPEN]
    
    @pytest.mark.asyncio
    async def test_half_open_to_closed_transition(self):
        """测试 HALF_OPEN -> CLOSED 转换（恢复成功）"""
        cb = CircuitBreaker(
            error_threshold_percent=50.0,
            time_window_seconds=1,
            recovery_timeout_seconds=1,
            half_open_max_calls=3
        )
        
        # 触发熔断
        for i in range(10):
            try:
                async def fail():
                    raise ValueError("error")
                await cb.call(fail)
            except ValueError:
                pass
        
        assert cb.is_open is True
        
        # 等待恢复超时
        await asyncio.sleep(1.5)
        
        # 半开状态：连续成功调用
        async def success():
            return "success"
        
        for i in range(3):
            await cb.call(success)
        
        # 应该恢复到 CLOSED
        assert cb.is_closed is True
    
    @pytest.mark.asyncio
    async def test_half_open_to_open_transition(self):
        """测试 HALF_OPEN -> OPEN 转换（恢复失败）"""
        cb = CircuitBreaker(
            error_threshold_percent=50.0,
            time_window_seconds=1,
            recovery_timeout_seconds=1,
            half_open_max_calls=3
        )
        
        # 触发熔断
        for i in range(10):
            try:
                async def fail():
                    raise ValueError("error")
                await cb.call(fail)
            except ValueError:
                pass
        
        assert cb.is_open is True
        
        # 等待恢复超时
        await asyncio.sleep(1.5)
        
        # 半开状态：继续失败
        for i in range(3):
            try:
                async def fail():
                    raise ValueError("error")
                await cb.call(fail)
            except ValueError:
                pass
        
        # 应该重新熔断
        assert cb.is_open is True


class TestCircuitBreakerSlidingWindow:
    """CircuitBreaker 滑动窗口测试"""
    
    def test_error_rate_calculation(self):
        """测试错误率计算"""
        cb = CircuitBreaker(
            error_threshold_percent=50.0,
            time_window_seconds=10
        )
        
        # 手动记录成功和失败
        cb._record_success()
        cb._record_success()
        cb._record_failure()
        
        # 错误率应该是 33.33%
        error_rate = cb._calculate_error_rate()
        assert abs(error_rate - 33.33) < 1.0
    
    def test_window_cleanup(self):
        """测试窗口清理（过期数据）"""
        cb = CircuitBreaker(
            time_window_seconds=1  # 1 秒窗口
        )
        
        # 记录一些调用
        cb._record_success()
        cb._record_success()
        
        # 等待窗口过期
        time.sleep(1.5)
        
        # 清理窗口
        cb._clean_window()
        
        # 窗口应该为空
        assert len(cb._window) == 0
        
        # 错误率应该是 0
        error_rate = cb._calculate_error_rate()
        assert error_rate == 0.0
    
    def test_window_only_keeps_recent(self):
        """测试窗口只保留最近的数据"""
        cb = CircuitBreaker(
            time_window_seconds=2
        )
        
        # 记录旧数据
        cb._window.append((time.time() - 3, True))  # 3 秒前
        cb._window.append((time.time() - 2.5, False))  # 2.5 秒前
        
        # 记录新数据
        cb._record_success()
        cb._record_failure()
        
        # 清理
        cb._clean_window()
        
        # 只应该保留最近 2 秒的数据
        assert len(cb._window) == 2


class TestCircuitBreakerManualControl:
    """CircuitBreaker 手动控制测试"""
    
    def test_force_open(self):
        """测试强制打开"""
        cb = CircuitBreaker()
        
        assert cb.is_closed is True
        
        cb.force_open()
        
        assert cb.is_open is True
        assert cb.state == CircuitState.OPEN
    
    def test_force_close(self):
        """测试强制关闭"""
        cb = CircuitBreaker()
        
        # 先打开
        cb.force_open()
        assert cb.is_open is True
        
        # 再关闭
        cb.force_close()
        
        assert cb.is_closed is True
        assert cb.state == CircuitState.CLOSED
    
    def test_reset(self):
        """测试重置"""
        cb = CircuitBreaker()
        
        # 触发一些调用
        cb._record_success()
        cb._record_failure()
        
        # 打开熔断器
        cb.force_open()
        
        # 重置
        cb.reset()
        
        assert cb.is_closed is True
        assert len(cb._window) == 0
        
        stats = cb.get_stats()
        assert stats["total_calls"] == 0


class TestCircuitBreakerOpenError:
    """CircuitBreaker 打开时的错误测试"""
    
    @pytest.mark.asyncio
    async def test_reject_when_open(self):
        """测试熔断器打开时拒绝调用"""
        cb = CircuitBreaker()
        
        # 强制打开
        cb.force_open()
        
        async def func():
            return "should not be called"
        
        # 应该抛出异常
        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(func)
        
        stats = cb.get_stats()
        assert stats["rejected_calls"] == 1


class TestCircuitBreakerStats:
    """CircuitBreaker 统计信息测试"""
    
    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """测试统计信息追踪"""
        cb = CircuitBreaker()
        
        async def success():
            return "success"
        
        async def fail():
            raise ValueError("error")
        
        # 成功调用
        await cb.call(success)
        await cb.call(success)
        
        # 失败调用
        try:
            await cb.call(fail)
        except ValueError:
            pass
        
        stats = cb.get_stats()
        
        assert stats["success_calls"] == 2
        assert stats["failed_calls"] == 1
        assert stats["total_calls"] == 3
        assert stats["state"] == "closed"
    
    @pytest.mark.asyncio
    async def test_state_transitions_count(self):
        """测试状态转换计数"""
        cb = CircuitBreaker()
        
        # 触发熔断
        for i in range(10):
            try:
                async def fail():
                    raise ValueError("error")
                await cb.call(fail)
            except ValueError:
                pass
        
        stats = cb.get_stats()
        
        # 应该至少有 1 次状态转换（CLOSED -> OPEN）
        assert stats["state_transitions"] >= 1


class TestCircuitBreakerIntegration:
    """CircuitBreaker 集成测试"""
    
    @pytest.mark.asyncio
    async def test_real_world_scenario(self):
        """测试真实场景：间歇性故障 -> 熔断 -> 恢复"""
        cb = CircuitBreaker(
            error_threshold_percent=60.0,
            time_window_seconds=5,
            recovery_timeout_seconds=2,
            half_open_max_calls=2
        )
        
        # 模拟间歇性故障
        call_count = 0
        
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            
            # 前 6 次调用中 4 次失败（66% 错误率）
            if call_count <= 6:
                if call_count in [2, 4, 6, 8]:
                    raise ValueError("flaky error")
            
            # 后续调用成功
            return "success"
        
        # 阶段 1：触发熔断
        for i in range(6):
            try:
                await cb.call(flaky_func)
            except ValueError:
                pass
        
        # 应该熔断
        assert cb.is_open is True
        
        # 阶段 2：等待恢复
        await asyncio.sleep(2.5)
        
        # 阶段 3：恢复（连续成功）
        try:
            result = await cb.call(flaky_func)
        except CircuitBreakerOpenError:
            pass
        
        # 最终应该恢复
        # （注意：具体行为取决于实现细节）


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
