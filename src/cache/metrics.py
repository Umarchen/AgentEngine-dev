"""
缓存监控指标模块
采集和暴露 Prometheus 监控指标
"""

import time
from typing import Optional

from prometheus_client import Counter, Histogram, Gauge, Info
from loguru import logger


class CacheMetrics:
    """
    缓存监控指标采集器
    
    功能：
    1. Prometheus 指标采集
    2. 命中/未命中计数
    3. 延迟分布
    4. 错误计数
    """
    
    # ==================== 基础性能指标 ====================
    
    # 缓存命中次数
    cache_hits_total = Counter(
        'cache_hits_total',
        '缓存命中总次数',
        ['cache_type']
    )
    
    # 缓存未命中次数
    cache_misses_total = Counter(
        'cache_misses_total',
        '缓存未命中总次数',
        ['cache_type']
    )
    
    # 缓存操作延迟
    cache_latency_seconds = Histogram(
        'cache_latency_seconds',
        '缓存操作延迟（秒）',
        ['operation', 'cache_type'],
        buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
    )
    
    # ==================== 预热指标 ====================
    
    # 预热进度
    cache_warmup_progress = Gauge(
        'cache_warmup_progress',
        '缓存预热进度（百分比）',
        ['cache_type']
    )
    
    # 预热总数
    cache_warmup_total = Gauge(
        'cache_warmup_total',
        '预热总数',
        ['cache_type']
    )
    
    # 已预热数量
    cache_warmup_warmed = Gauge(
        'cache_warmup_warmed',
        '已预热数量',
        ['cache_type']
    )
    
    # ==================== 降级指标 ====================
    
    # 降级事件计数
    cache_degradation_total = Counter(
        'cache_degradation_total',
        '缓存降级事件总次数',
        ['reason']
    )
    
    # 回源事件计数
    cache_fallback_total = Counter(
        'cache_fallback_total',
        '数据库回源事件总次数',
        ['cache_type']
    )
    
    # ==================== 键空间指标 ====================
    
    # 按类型统计键数量
    cache_keys_by_type = Gauge(
        'cache_keys_by_type',
        '按类型统计的缓存键数量',
        ['cache_type']
    )
    
    # 按类型统计内存使用
    cache_memory_bytes_by_type = Gauge(
        'cache_memory_bytes_by_type',
        '按类型统计的内存使用（字节）',
        ['cache_type']
    )
    
    # ==================== Redis 连接池指标 ====================
    
    # 活跃连接数
    redis_connections_active = Gauge(
        'redis_connections_active',
        '活跃的 Redis 连接数'
    )
    
    # 空闲连接数
    redis_connections_idle = Gauge(
        'redis_connections_idle',
        '空闲的 Redis 连接数'
    )
    
    # Redis 错误次数
    redis_errors_total = Counter(
        'redis_errors_total',
        'Redis 错误总次数',
        ['error_type']
    )
    
    # Redis 信息
    redis_info = Info(
        'redis',
        'Redis 版本信息'
    )
    
    # ==================== 记录方法 ====================
    
    @staticmethod
    def record_hit(cache_type: str):
        """
        记录缓存命中
        
        Args:
            cache_type: 缓存类型
        """
        CacheMetrics.cache_hits_total.labels(cache_type=cache_type).inc()
    
    @staticmethod
    def record_miss(cache_type: str):
        """
        记录缓存未命中
        
        Args:
            cache_type: 缓存类型
        """
        CacheMetrics.cache_misses_total.labels(cache_type=cache_type).inc()
    
    @staticmethod
    def record_latency(
        operation: str,
        cache_type: str,
        duration: float
    ):
        """
        记录延迟
        
        Args:
            operation: 操作类型（get/set/delete）
            cache_type: 缓存类型
            duration: 延迟时间（秒）
        """
        CacheMetrics.cache_latency_seconds.labels(
            operation=operation,
            cache_type=cache_type
        ).observe(duration)
    
    @staticmethod
    def record_warmup_progress(
        cache_type: str,
        warmed: int,
        total: int
    ):
        """
        记录预热进度
        
        Args:
            cache_type: 缓存类型
            warmed: 已预热数量
            total: 总数
        """
        CacheMetrics.cache_warmup_warmed.labels(
            cache_type=cache_type
        ).set(warmed)
        
        CacheMetrics.cache_warmup_total.labels(
            cache_type=cache_type
        ).set(total)
        
        if total > 0:
            progress = (warmed / total) * 100
            CacheMetrics.cache_warmup_progress.labels(
                cache_type=cache_type
            ).set(progress)
    
    @staticmethod
    def record_degradation(reason: str):
        """
        记录降级事件
        
        Args:
            reason: 降级原因
        """
        CacheMetrics.cache_degradation_total.labels(reason=reason).inc()
        logger.warning(f"缓存降级: {reason}")
    
    @staticmethod
    def record_fallback(cache_type: str):
        """
        记录回源事件
        
        Args:
            cache_type: 缓存类型
        """
        CacheMetrics.cache_fallback_total.labels(cache_type=cache_type).inc()
    
    @staticmethod
    def record_error(error_type: str):
        """
        记录 Redis 错误
        
        Args:
            error_type: 错误类型
        """
        CacheMetrics.redis_errors_total.labels(error_type=error_type).inc()
    
    @staticmethod
    def update_keys_count(cache_type: str, count: int):
        """
        更新键数量
        
        Args:
            cache_type: 缓存类型
            count: 键数量
        """
        CacheMetrics.cache_keys_by_type.labels(cache_type=cache_type).set(count)
    
    @staticmethod
    def update_memory_usage(cache_type: str, bytes_count: int):
        """
        更新内存使用
        
        Args:
            cache_type: 缓存类型
            bytes_count: 内存使用（字节）
        """
        CacheMetrics.cache_memory_bytes_by_type.labels(
            cache_type=cache_type
        ).set(bytes_count)
    
    @staticmethod
    def update_connections(active: int, idle: int):
        """
        更新连接数
        
        Args:
            active: 活跃连接数
            idle: 空闲连接数
        """
        CacheMetrics.redis_connections_active.set(active)
        CacheMetrics.redis_connections_idle.set(idle)
    
    @staticmethod
    def set_redis_info(version: str):
        """
        设置 Redis 版本信息
        
        Args:
            version: Redis 版本
        """
        CacheMetrics.redis_info.info({'version': version})


class MetricsContext:
    """
    指标上下文管理器
    用于自动记录延迟
    """
    
    def __init__(
        self,
        operation: str,
        cache_type: str = "default"
    ):
        """
        初始化上下文
        
        Args:
            operation: 操作类型
            cache_type: 缓存类型
        """
        self.operation = operation
        self.cache_type = cache_type
        self.start_time: Optional[float] = None
    
    def __enter__(self):
        """进入上下文"""
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        if self.start_time:
            duration = time.time() - self.start_time
            CacheMetrics.record_latency(
                operation=self.operation,
                cache_type=self.cache_type,
                duration=duration
            )
        
        # 如果有异常，记录错误
        if exc_type:
            error_type = exc_type.__name__
            CacheMetrics.record_error(error_type)
        
        return False  # 不抑制异常
    
    async def __aenter__(self):
        """异步进入上下文"""
        self.start_time = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步退出上下文"""
        if self.start_time:
            duration = time.time() - self.start_time
            CacheMetrics.record_latency(
                operation=self.operation,
                cache_type=self.cache_type,
                duration=duration
            )
        
        # 如果有异常，记录错误
        if exc_type:
            error_type = exc_type.__name__
            CacheMetrics.record_error(error_type)
        
        return False  # 不抑制异常
