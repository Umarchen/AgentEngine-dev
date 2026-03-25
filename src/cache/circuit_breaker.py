"""
熔断器模块
基于滑动窗口的熔断器实现，参考 Hystrix 设计
"""

import time
from enum import Enum
from typing import Optional, Callable, Any, Deque
from collections import deque
from loguru import logger


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 关闭（正常）
    OPEN = "open"          # 打开（熔断）
    HALF_OPEN = "half_open"  # 半开（尝试恢复）


class CircuitBreakerStats:
    """熔断器统计信息"""
    
    def __init__(self):
        self.total_calls = 0  # 总调用次数
        self.success_calls = 0  # 成功次数
        self.failed_calls = 0  # 失败次数
        self.rejected_calls = 0  # 拒绝次数（熔断时）
        self.state_transitions = 0  # 状态转换次数
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "total_calls": self.total_calls,
            "success_calls": self.success_calls,
            "failed_calls": self.failed_calls,
            "rejected_calls": self.rejected_calls,
            "state_transitions": self.state_transitions
        }


class CircuitBreaker:
    """
    熔断器
    
    特性：
    - 基于滑动窗口统计错误率
    - 三种状态：CLOSED（关闭）、OPEN（打开）、HALF_OPEN（半开）
    - 错误率达到阈值时自动熔断
    - 半开状态尝试恢复
    - 提供手动控制接口
    
    对应需求：[REQ_REDIS_CACHE_002] 熔断器机制（新增）
    """
    
    def __init__(
        self,
        name: str = "default",
        error_threshold_percent: float = 50.0,
        time_window_seconds: int = 10,
        recovery_timeout_seconds: int = 30,
        half_open_max_calls: int = 3
    ):
        """
        初始化熔断器
        
        Args:
            name: 熔断器名称（用于日志和监控）
            error_threshold_percent: 错误率阈值（默认 50%）
            time_window_seconds: 滑动窗口时间（秒，默认 10s）
            recovery_timeout_seconds: 恢复超时时间（秒，默认 30s）
            half_open_max_calls: 半开状态最大尝试次数（默认 3）
        """
        self.name = name
        self.error_threshold_percent = error_threshold_percent
        self.time_window_seconds = time_window_seconds
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.half_open_max_calls = half_open_max_calls
        
        # 状态管理
        self._state = CircuitState.CLOSED
        self._last_failure_time: Optional[float] = None
        self._opened_at: Optional[float] = None
        
        # 滑动窗口（记录最近 N 秒的调用结果）
        self._window: Deque[Tuple[float, bool]] = deque()  # (timestamp, is_success)
        
        # 统计信息
        self._stats = CircuitBreakerStats()
        
        logger.info(
            f"CircuitBreaker[{name}] 初始化 - "
            f"错误阈值: {error_threshold_percent}%, "
            f"时间窗口: {time_window_seconds}s, "
            f"恢复超时: {recovery_timeout_seconds}s"
        )
    
    @property
    def state(self) -> CircuitState:
        """获取当前状态"""
        return self._state
    
    @property
    def is_open(self) -> bool:
        """熔断器是否打开"""
        return self._state == CircuitState.OPEN
    
    @property
    def is_closed(self) -> bool:
        """熔断器是否关闭"""
        return self._state == CircuitState.CLOSED
    
    @property
    def is_half_open(self) -> bool:
        """熔断器是否半开"""
        return self._state == CircuitState.HALF_OPEN
    
    def _clean_window(self):
        """清理过期的滑动窗口数据"""
        cutoff = time.time() - self.time_window_seconds
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()
    
    def _calculate_error_rate(self) -> float:
        """
        计算当前错误率
        
        Returns:
            错误率百分比（0-100）
        """
        self._clean_window()
        
        if not self._window:
            return 0.0
        
        total = len(self._window)
        failures = sum(1 for _, is_success in self._window if not is_success)
        
        return (failures / total) * 100.0
    
    def _record_success(self):
        """记录成功调用"""
        self._window.append((time.time(), True))
        self._stats.success_calls += 1
        self._stats.total_calls += 1
    
    def _record_failure(self):
        """记录失败调用"""
        self._window.append((time.time(), False))
        self._stats.failed_calls += 1
        self._stats.total_calls += 1
        self._last_failure_time = time.time()
    
    def _transition_to(self, new_state: CircuitState):
        """
        状态转换
        
        Args:
            new_state: 新状态
        """
        old_state = self._state
        self._state = new_state
        self._stats.state_transitions += 1
        
        logger.warning(
            f"CircuitBreaker[{self.name}] 状态转换: "
            f"{old_state.value} -> {new_state.value}"
        )
        
        # TODO: 触发告警
        # AlertManager.send_alert(...)
    
    def _update_state(self):
        """更新熔断器状态"""
        error_rate = self._calculate_error_rate()
        
        if self._state == CircuitState.CLOSED:
            # 关闭状态：检查是否需要熔断
            if error_rate >= self.error_threshold_percent:
                self._transition_to(CircuitState.OPEN)
                self._opened_at = time.time()
                logger.error(
                    f"CircuitBreaker[{self.name}] 熔断触发 - "
                    f"错误率: {error_rate:.2f}%, 阈值: {self.error_threshold_percent}%"
                )
        
        elif self._state == CircuitState.OPEN:
            # 打开状态：检查是否可以尝试恢复
            if self._opened_at and (time.time() - self._opened_at >= self.recovery_timeout_seconds):
                self._transition_to(CircuitState.HALF_OPEN)
                logger.info(f"CircuitBreaker[{self.name}] 进入半开状态，尝试恢复")
        
        elif self._state == CircuitState.HALF_OPEN:
            # 半开状态：检查是否恢复成功或失败
            half_open_calls = len([t for t, _ in self._window if self._opened_at and t >= self._opened_at])
            
            if half_open_calls >= self.half_open_max_calls:
                # 达到最大尝试次数，重新计算错误率
                if error_rate < self.error_threshold_percent:
                    # 恢复成功
                    self._transition_to(CircuitState.CLOSED)
                    self._opened_at = None
                    logger.info(f"CircuitBreaker[{self.name}] 恢复成功，熔断器关闭")
                else:
                    # 恢复失败，重新熔断
                    self._transition_to(CircuitState.OPEN)
                    self._opened_at = time.time()
                    logger.error(f"CircuitBreaker[{self.name}] 恢复失败，重新熔断")
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        通过熔断器调用函数
        
        Args:
            func: 要调用的异步函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            函数返回值
            
        Raises:
            CircuitBreakerOpenError: 熔断器打开时抛出
        """
        # 更新状态
        self._update_state()
        
        # 检查熔断状态
        if self._state == CircuitState.OPEN:
            self._stats.rejected_calls += 1
            logger.warning(f"CircuitBreaker[{self.name}] 熔断器打开，拒绝调用")
            raise CircuitBreakerOpenError(
                f"CircuitBreaker[{self.name}] is OPEN, rejecting call"
            )
        
        # 执行调用
        try:
            result = await func(*args, **kwargs)
            self._record_success()
            
            # 半开状态成功调用后检查恢复
            if self._state == CircuitState.HALF_OPEN:
                self._update_state()
            
            return result
        
        except Exception as e:
            self._record_failure()
            self._update_state()
            raise
    
    def force_open(self):
        """强制打开熔断器"""
        self._transition_to(CircuitState.OPEN)
        self._opened_at = time.time()
        logger.warning(f"CircuitBreaker[{self.name}] 强制打开")
    
    def force_close(self):
        """强制关闭熔断器"""
        self._transition_to(CircuitState.CLOSED)
        self._opened_at = None
        self._window.clear()
        logger.info(f"CircuitBreaker[{self.name}] 强制关闭")
    
    def get_stats(self) -> dict:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        stats = self._stats.to_dict()
        stats.update({
            "name": self.name,
            "state": self._state.value,
            "error_rate": round(self._calculate_error_rate(), 2),
            "error_threshold": self.error_threshold_percent,
            "time_window_seconds": self.time_window_seconds,
            "recovery_timeout_seconds": self.recovery_timeout_seconds
        })
        return stats
    
    def reset(self):
        """重置熔断器"""
        self._state = CircuitState.CLOSED
        self._opened_at = None
        self._window.clear()
        self._stats = CircuitBreakerStats()
        logger.info(f"CircuitBreaker[{self.name}] 已重置")


class CircuitBreakerOpenError(Exception):
    """熔断器打开异常"""
    pass


# 导入 Tuple 用于类型注解
Tuple = tuple
