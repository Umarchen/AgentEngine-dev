"""
增强版缓存监控指标模块
扩展 CacheMetrics，新增熔断器和本地缓存指标

对应需求：
- [REQ_REDIS_CACHE_003] 监控告警体系
"""

import time
from typing import Optional

from prometheus_client import Counter, Histogram, Gauge, Info
from loguru import logger


class CacheMetricsV2:
    """
    增强版缓存监控指标采集器
    
    新增指标：
    1. 熔断器状态指标
    2. 本地缓存（L1）指标
    3. 批量操作指标
    4. 更细粒度的延迟分布
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
    
    # ==================== 熔断器指标（新增）====================
    
    # 熔断器状态
    circuit_breaker_state = Gauge(
        'circuit_breaker_state',
        '熔断器状态（0=closed, 1=open, 2=half_open）',
        ['name']
    )
    
    # 熔断器错误率
    circuit_breaker_error_rate = Gauge(
        'circuit_breaker_error_rate',
        '熔断器错误率',
        ['name']
    )
    
    # 熔断器状态变化次数
    circuit_breaker_state_changes_total = Counter(
        'circuit_breaker_state_changes_total',
        '熔断器状态变化总次数',
        ['name', 'from_state', 'to_state']
    )
    
    # 熔断器打开总次数
    circuit_breaker_opened_total = Counter(
        'circuit_breaker_opened_total',
        '熔断器打开总次数',
        ['name']
    )
    
    # ==================== 本地缓存指标（新增）====================
    
    # 本地缓存大小
    local_cache_size = Gauge(
        'local_cache_size',
        '本地缓存当前大小',
        ['cache_type']
    )
    
    # 本地缓存容量
    local_cache_maxsize = Gauge(
        'local_cache_maxsize',
        '本地缓存最大容量',
        ['cache_type']
    )
    
    # 本地缓存命中率
    local_cache_hit_rate = Gauge(
        'local_cache_hit_rate',
        '本地缓存命中率',
        ['cache_type']
    )
    
    # ==================== 批量操作指标（新增）====================
    
    # 批量操作次数
    cache_batch_operations_total = Counter(
        'cache_batch_operations_total',
        '批量操作总次数',
        ['operation', 'cache_type']
    )
    
    # 批量操作延迟
    cache_batch_latency_seconds = Histogram(
        'cache_batch_latency_seconds',
        '批量操作延迟（秒）',
        ['operation', 'cache_type'],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
    )
    
    # ==================== 预热指标 ====================
    
    cache_warmup_progress = Gauge(
        'cache_warmup_progress',
        '缓存预热进度（百分比）',
        ['cache_type']
    )
    
    cache_warmup_total = Gauge(
        'cache_warmup_total',
        '预热总数',
        ['cache_type']
    )
    
    cache_warmup_warmed = Gauge(
        'cache_warmup_warmed',
        '已预热数量',
        ['cache_type']
    )
    
    # ==================== 降级指标 ====================
    
    cache_degradation_total = Counter(
        'cache_degradation_total',
        '缓存降级事件总次数',
        ['reason']
    )
    
    cache_fallback_total = Counter(
        'cache_fallback_total',
        '数据库回源事件总次数',
        ['cache_type']
    )
    
    # ==================== 键空间指标 ====================
    
    cache_keys_by_type = Gauge(
        'cache_keys_by_type',
        '按类型统计的缓存键数量',
        ['cache_type']
    )
    
    cache_memory_bytes_by_type = Gauge(
        'cache_memory_bytes_by_type',
        '按类型统计的内存使用（字节）',
        ['cache_type']
    )
    
    # ==================== Redis 连接池指标 ====================
    
    redis_connections_active = Gauge(
        'redis_connections_active',
        '活跃的 Redis 连接数'
    )
    
    redis_connections_idle = Gauge(
        'redis_connections_idle',
        '空闲的 Redis 连接数'
    )
    
    redis_errors_total = Counter(
        'redis_errors_total',
        'Redis 错误总次数',
        ['error_type']
    )
    
    redis_info = Info(
        'redis',
        'Redis 版本信息'
    )
    
    # ==================== 记录方法 ====================
    
    @staticmethod
    def record_hit(cache_type: str):
        """记录缓存命中"""
        CacheMetricsV2.cache_hits_total.labels(cache_type=cache_type).inc()
    
    @staticmethod
    def record_miss(cache_type: str):
        """记录缓存未命中"""
        CacheMetricsV2.cache_misses_total.labels(cache_type=cache_type).inc()
    
    @staticmethod
    def record_latency(
        operation: str,
        cache_type: str,
        duration: float
    ):
        """记录延迟"""
        CacheMetricsV2.cache_latency_seconds.labels(
            operation=operation,
            cache_type=cache_type
        ).observe(duration)
    
    @staticmethod
    def record_circuit_breaker_state(
        name: str,
        state: str,
        error_rate: float
    ):
        """
        记录熔断器状态
        
        Args:
            name: 熔断器名称
            state: 状态（closed/open/half_open）
            error_rate: 错误率
        """
        state_map = {"closed": 0, "open": 1, "half_open": 2}
        state_value = state_map.get(state, 0)
        
        CacheMetricsV2.circuit_breaker_state.labels(name=name).set(state_value)
        CacheMetricsV2.circuit_breaker_error_rate.labels(name=name).set(error_rate)
    
    @staticmethod
    def record_circuit_breaker_change(
        name: str,
        from_state: str,
        to_state: str
    ):
        """
        记录熔断器状态变化
        
        Args:
            name: 熔断器名称
            from_state: 原状态
            to_state: 新状态
        """
        CacheMetricsV2.circuit_breaker_state_changes_total.labels(
            name=name,
            from_state=from_state,
            to_state=to_state
        ).inc()
        
        if to_state == "open":
            CacheMetricsV2.circuit_breaker_opened_total.labels(name=name).inc()
    
    @staticmethod
    def record_local_cache_stats(
        cache_type: str,
        size: int,
        maxsize: int,
        hit_rate: float
    ):
        """
        记录本地缓存统计
        
        Args:
            cache_type: 缓存类型
            size: 当前大小
            maxsize: 最大容量
            hit_rate: 命中率
        """
        CacheMetricsV2.local_cache_size.labels(cache_type=cache_type).set(size)
        CacheMetricsV2.local_cache_maxsize.labels(cache_type=cache_type).set(maxsize)
        CacheMetricsV2.local_cache_hit_rate.labels(cache_type=cache_type).set(hit_rate)
    
    @staticmethod
    def record_batch_operation(
        operation: str,
        cache_type: str,
        count: int,
        duration: float
    ):
        """
        记录批量操作
        
        Args:
            operation: 操作类型（mget/delete_batch）
            cache_type: 缓存类型
            count: 操作数量
            duration: 耗时
        """
        CacheMetricsV2.cache_batch_operations_total.labels(
            operation=operation,
            cache_type=cache_type
        ).inc()
        
        CacheMetricsV2.cache_batch_latency_seconds.labels(
            operation=operation,
            cache_type=cache_type
        ).observe(duration)
    
    @staticmethod
    def record_warmup_progress(
        cache_type: str,
        warmed: int,
        total: int
    ):
        """记录预热进度"""
        CacheMetricsV2.cache_warmup_warmed.labels(
            cache_type=cache_type
        ).set(warmed)
        
        CacheMetricsV2.cache_warmup_total.labels(
            cache_type=cache_type
        ).set(total)
        
        if total > 0:
            progress = (warmed / total) * 100
            CacheMetricsV2.cache_warmup_progress.labels(
                cache_type=cache_type
            ).set(progress)
    
    @staticmethod
    def record_degradation(reason: str):
        """记录降级事件"""
        CacheMetricsV2.cache_degradation_total.labels(reason=reason).inc()
        logger.warning(f"缓存降级: {reason}")
    
    @staticmethod
    def record_fallback(cache_type: str):
        """记录回源事件"""
        CacheMetricsV2.cache_fallback_total.labels(cache_type=cache_type).inc()
    
    @staticmethod
    def record_error(error_type: str):
        """记录 Redis 错误"""
        CacheMetricsV2.redis_errors_total.labels(error_type=error_type).inc()
    
    @staticmethod
    def update_keys_count(cache_type: str, count: int):
        """更新键数量"""
        CacheMetricsV2.cache_keys_by_type.labels(cache_type=cache_type).set(count)
    
    @staticmethod
    def update_memory_usage(cache_type: str, bytes_count: int):
        """更新内存使用"""
        CacheMetricsV2.cache_memory_bytes_by_type.labels(
            cache_type=cache_type
        ).set(bytes_count)
    
    @staticmethod
    def update_connections(active: int, idle: int):
        """更新连接数"""
        CacheMetricsV2.redis_connections_active.set(active)
        CacheMetricsV2.redis_connections_idle.set(idle)
    
    @staticmethod
    def set_redis_info(version: str):
        """设置 Redis 版本信息"""
        CacheMetricsV2.redis_info.info({'version': version})


class MetricsContextV2:
    """
    增强版指标上下文管理器
    """
    
    def __init__(
        self,
        operation: str,
        cache_type: str = "default"
    ):
        self.operation = operation
        self.cache_type = cache_type
        self.start_time: Optional[float] = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            CacheMetricsV2.record_latency(
                operation=self.operation,
                cache_type=self.cache_type,
                duration=duration
            )
        
        if exc_type:
            error_type = exc_type.__name__
            CacheMetricsV2.record_error(error_type)
        
        return False
    
    async def __aenter__(self):
        self.start_time = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            CacheMetricsV2.record_latency(
                operation=self.operation,
                cache_type=self.cache_type,
                duration=duration
            )
        
        if exc_type:
            error_type = exc_type.__name__
            CacheMetricsV2.record_error(error_type)
        
        return False


class BatchMetricsContext:
    """批量操作指标上下文"""
    
    def __init__(
        self,
        operation: str,
        cache_type: str = "default"
    ):
        self.operation = operation
        self.cache_type = cache_type
        self.start_time: Optional[float] = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            CacheMetricsV2.record_batch_operation(
                operation=self.operation,
                cache_type=self.cache_type,
                count=1,
                duration=duration
            )
        
        return False
    
    async def __aenter__(self):
        self.start_time = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            CacheMetricsV2.record_batch_operation(
                operation=self.operation,
                cache_type=self.cache_type,
                count=1,
                duration=duration
            )
        
        return False
