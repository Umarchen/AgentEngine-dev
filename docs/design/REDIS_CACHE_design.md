# Redis 缓存集成系统设计文档

**项目名称**：AgentEngine-dev  
**文档版本**：v1.0  
**创建时间**：2026-03-24  
**作者**：架构师 Agent (SA)  
**项目模式**：Incremental（增量接管模式）  
**文档状态**：待评审  

---

## 文档修订历史

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|---------|
| 1.0 | 2026-03-24 | SA Agent | 初始版本，基于 PRD 和存量代码解剖报告编写 |

---

## 1. 概述

### 1.1 设计背景

AgentEngine-dev 项目已有完整的 Redis 缓存模块实现（`src/cache/` 目录），但在实际使用中存在以下问题：

1. **缓存一致性风险**：多实例部署时本地缓存和 Redis 缓存可能不一致
2. **降级机制不完善**：缺少熔断器，Redis 故障时可能导致雪崩
3. **监控告警缺失**：虽有 Prometheus 指标，但缺少告警规则
4. **性能优化空间**：缺少缓存预热、批量操作、本地缓存淘汰策略

### 1.2 设计目标

**总体目标**：在现有 Redis 缓存模块基础上，进行增量增强，构建高性能、高可用的分布式缓存体系。

**具体目标**：
1. ✅ 解决多实例部署下的缓存一致性问题（PRD [REQ_REDIS_CACHE_001]）
2. ✅ 实现完善的熔断和降级机制（PRD [REQ_REDIS_CACHE_002]）
3. ✅ 建立完整的监控告警体系（PRD [REQ_REDIS_CACHE_003]）
4. ✅ 优化缓存性能，提升系统吞吐量（PRD [REQ_REDIS_CACHE_004]~[008]）

### 1.3 设计原则

1. **增量增强**：基于现有 `src/cache/` 模块做增强，不推翻重写
2. **最小侵入**：新增模块与现有 CacheManager 的集成方式清晰明确
3. **可落地性**：设计方案包含具体的类/接口定义、数据结构、调用链路
4. **生产就绪**：缓存一致性方案考虑多实例部署场景

---

## 2. 架构设计

### 2.1 多级缓存架构（增强）

#### 2.1.1 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        应用层                                    │
│  (AgentManager, ConfigManager, etc.)                           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                ┌───────────┴──────────┐
                │                      │
                ▼                      ▼
        ┌──────────────┐       ┌──────────────┐
        │   L1 缓存     │       │   L2 缓存     │
        │  本地内存     │       │    Redis     │
        │  (TTLCache)  │       │  (分布式)     │
        │              │       │              │
        │ 容量: 1000   │       │  容量: 无限   │
        │ TTL: 300s    │       │  TTL: 3600s  │
        └──────┬───────┘       └──────┬───────┘
               │ miss                  │ miss
               └──────────┬────────────┘
                          │
                          ▼
                  ┌──────────────┐
                  │   L3 数据库   │
                  │  (PostgreSQL)│
                  └──────────────┘
```

**设计说明**：

- **L1 本地缓存**：使用 `cachetools.TTLCache`，容量 1000 条，TTL 300 秒
- **L2 Redis 缓存**：分布式缓存，TTL 3600 秒 + 随机偏移（防雪崩）
- **L3 数据库**：持久化存储，作为最终数据源

**缓存策略**：
- **Read-Through**：优先读 L1 → L2 → L3，逐级回填
- **Write-Through**：写数据库 → 删 L2 → 广播删除 L1
- **Cache-Aside**：更新时删除缓存，而非更新缓存

#### 2.1.2 类定义

```python
# src/cache/local_cache.py（新增）

from cachetools import TTLCache
from typing import Any, Optional
from threading import RLock
import time

class LocalCache:
    """
    本地内存缓存（L1 缓存）
    
    功能：
    1. LRU 淘汰策略
    2. TTL 自动过期
    3. 线程安全
    """
    
    def __init__(
        self,
        maxsize: int = 1000,
        ttl: float = 300.0
    ):
        """
        初始化本地缓存
        
        Args:
            maxsize: 最大容量（LRU 淘汰）
            ttl: 过期时间（秒）
        """
        self._cache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = RLock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，不存在返回 None
        """
        with self._lock:
            try:
                value = self._cache[key]
                self._hits += 1
                return value
            except KeyError:
                self._misses += 1
                return None
    
    def set(self, key: str, value: Any) -> None:
        """
        设置缓存
        
        Args:
            key: 缓存键
            value: 缓存值
        """
        with self._lock:
            self._cache[key] = value
    
    def delete(self, key: str) -> bool:
        """
        删除缓存
        
        Args:
            key: 缓存键
            
        Returns:
            是否删除成功
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
    
    def get_stats(self) -> dict:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total) if total > 0 else 0.0
            
            return {
                "size": len(self._cache),
                "maxsize": self._cache.maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
            }
```

### 2.2 缓存一致性方案（新增）

#### 2.2.1 方案选择

**方案一：Redis Pub/Sub 广播（推荐）**

```
配置更新流程：
1. 更新数据库
2. 删除 Redis 缓存
3. 发布缓存失效消息到 Redis Channel
4. 所有订阅的实例收到消息后删除本地缓存
```

**方案二：短暂 TTL + 最终一致性**

```
配置更新流程：
1. 更新数据库
2. 删除 Redis 缓存
3. 本地缓存设置较短 TTL（30s）
4. 最多 30s 后自动生效
```

**选择依据**：采用方案一，适用于对一致性要求较高的场景，PRD 要求 5 秒内所有实例生效。

#### 2.2.2 类定义

```python
# src/cache/invalidator.py（新增）

import asyncio
import json
from typing import Callable, Set
from loguru import logger
from redis.asyncio import Redis

class CacheInvalidator:
    """
    缓存失效广播器
    
    功能：
    1. 发布缓存失效消息
    2. 订阅并处理失效消息
    3. 管理本地缓存清理
    """
    
    CHANNEL_NAME = "agent_engine:cache:invalidate"
    
    def __init__(
        self,
        redis_client: Redis,
        local_cache: "LocalCache",
        on_invalidate: Optional[Callable[[str], None]] = None
    ):
        """
        初始化缓存失效器
        
        Args:
            redis_client: Redis 客户端
            local_cache: 本地缓存实例
            on_invalidate: 自定义失效回调
        """
        self.redis_client = redis_client
        self.local_cache = local_cache
        self.on_invalidate = on_invalidate
        self._pubsub = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """启动订阅监听"""
        if self._running:
            return
        
        self._running = True
        self._pubsub = self.redis_client.pubsub()
        await self._pubsub.subscribe(self.CHANNEL_NAME)
        
        # 启动监听任务
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("缓存失效订阅已启动")
    
    async def stop(self) -> None:
        """停止订阅监听"""
        self._running = False
        
        if self._pubsub:
            await self._pubsub.unsubscribe(self.CHANNEL_NAME)
            await self._pubsub.close()
        
        if self._task:
            self._task.cancel()
        
        logger.info("缓存失效订阅已停止")
    
    async def publish_invalidation(self, cache_key: str) -> bool:
        """
        发布缓存失效消息
        
        Args:
            cache_key: 需要失效的缓存键
            
        Returns:
            是否发布成功
        """
        try:
            message = json.dumps({
                "key": cache_key,
                "timestamp": time.time()
            })
            
            result = await self.redis_client.publish(
                self.CHANNEL_NAME,
                message
            )
            
            logger.info(f"发布缓存失效消息: {cache_key}, 接收实例数: {result}")
            return result > 0
            
        except Exception as e:
            logger.error(f"发布缓存失效消息失败: {e}")
            return False
    
    async def _listen_loop(self) -> None:
        """监听循环"""
        try:
            while self._running:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0
                )
                
                if message:
                    await self._handle_message(message)
                    
        except asyncio.CancelledError:
            logger.info("监听任务被取消")
        except Exception as e:
            logger.error(f"监听异常: {e}")
    
    async def _handle_message(self, message: dict) -> None:
        """
        处理失效消息
        
        Args:
            message: Redis 消息
        """
        try:
            data = json.loads(message["data"])
            cache_key = data["key"]
            
            logger.info(f"收到缓存失效消息: {cache_key}")
            
            # 删除本地缓存
            self.local_cache.delete(cache_key)
            
            # 触发自定义回调
            if self.on_invalidate:
                self.on_invalidate(cache_key)
                
        except Exception as e:
            logger.error(f"处理失效消息失败: {e}")
```

### 2.3 熔断器设计（新增）

#### 2.3.1 状态机设计

```
熔断器状态机：
          错误率 > 50%
    ┌─────────────────────┐
    │                     │
    ▼                     │
┌────────┐  30s后    ┌────────┐
│ CLOSED │ ─────────>│  OPEN  │
└────────┘           └────┬───┘
    ▲                     │
    │     试探请求成功     │
    └───────── ┌──────────┘
              ▼
         ┌──────────┐
         │HALF_OPEN │
         └──────────┘
              │
              │ 试探请求失败
              └─────────> OPEN
```

**关键参数**：
- **错误阈值**：50%（可配置）
- **时间窗口**：10 秒（滑动窗口）
- **恢复时间**：30 秒
- **试探请求数**：3 个

#### 2.3.2 类定义

```python
# src/cache/circuit_breaker.py（新增）

import time
from enum import Enum
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
from collections import deque
from loguru import logger

class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 关闭（正常）
    OPEN = "open"          # 打开（熔断）
    HALF_OPEN = "half_open"  # 半开（试探）

@dataclass
class CircuitStats:
    """熔断器统计信息"""
    total_calls: int = 0
    failed_calls: int = 0
    last_failure_time: float = 0.0
    state: CircuitState = CircuitState.CLOSED
    last_state_change: float = field(default_factory=time.time)

class CircuitBreaker:
    """
    熔断器
    
    功能：
    1. 基于滑动窗口的错误率统计
    2. 状态机管理（CLOSED/OPEN/HALF_OPEN）
    3. 自动恢复试探
    4. 手动控制接口
    """
    
    def __init__(
        self,
        error_threshold_percent: float = 50.0,
        time_window_seconds: float = 10.0,
        recovery_timeout_seconds: float = 30.0,
        half_open_max_calls: int = 3
    ):
        """
        初始化熔断器
        
        Args:
            error_threshold_percent: 错误率阈值（%）
            time_window_seconds: 统计时间窗口（秒）
            recovery_timeout_seconds: 恢复超时（秒）
            half_open_max_calls: 半开状态最大试探次数
        """
        self.error_threshold_percent = error_threshold_percent
        self.time_window_seconds = time_window_seconds
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.half_open_max_calls = half_open_max_calls
        
        # 统计信息
        self._stats = CircuitStats()
        self._window = deque()  # 滑动窗口：(timestamp, is_success)
        
        # 半开状态计数器
        self._half_open_calls = 0
    
    @property
    def state(self) -> CircuitState:
        """获取当前状态"""
        return self._stats.state
    
    @property
    def is_open(self) -> bool:
        """熔断器是否打开"""
        return self._stats.state == CircuitState.OPEN
    
    async def call(
        self,
        func: Callable[[], Any],
        fallback: Optional[Callable[[], Any]] = None
    ) -> Any:
        """
        通过熔断器调用函数
        
        Args:
            func: 目标函数
            fallback: 降级函数
            
        Returns:
            函数返回值
            
        Raises:
            CircuitBreakerOpen: 熔断器打开时抛出
        """
        # 1. 检查状态转换
        self._update_state()
        
        # 2. 如果熔断器打开，执行降级或抛出异常
        if self._stats.state == CircuitState.OPEN:
            logger.warning("熔断器已打开，执行降级")
            if fallback:
                return await fallback() if asyncio.iscoroutinefunction(fallback) else fallback()
            raise CircuitBreakerOpen("熔断器已打开")
        
        # 3. 执行调用
        try:
            result = await func() if asyncio.iscoroutinefunction(func) else func()
            self._record_success()
            return result
            
        except Exception as e:
            self._record_failure()
            raise
    
    def _update_state(self) -> None:
        """更新状态机"""
        current_time = time.time()
        
        if self._stats.state == CircuitState.OPEN:
            # 检查是否到达恢复时间
            if current_time - self._stats.last_state_change >= self.recovery_timeout_seconds:
                self._transition_to(CircuitState.HALF_OPEN)
        
        elif self._stats.state == CircuitState.HALF_OPEN:
            # 半开状态：达到最大试探次数后，根据成功率决定状态
            if self._half_open_calls >= self.half_open_max_calls:
                error_rate = self._calculate_error_rate()
                if error_rate < self.error_threshold_percent:
                    self._transition_to(CircuitState.CLOSED)
                else:
                    self._transition_to(CircuitState.OPEN)
    
    def _record_success(self) -> None:
        """记录成功调用"""
        self._window.append((time.time(), True))
        self._clean_window()
        
        if self._stats.state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
    
    def _record_failure(self) -> None:
        """记录失败调用"""
        self._window.append((time.time(), False))
        self._clean_window()
        self._stats.last_failure_time = time.time()
        
        if self._stats.state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
        else:
            # 检查是否需要熔断
            error_rate = self._calculate_error_rate()
            if error_rate >= self.error_threshold_percent:
                self._transition_to(CircuitState.OPEN)
    
    def _calculate_error_rate(self) -> float:
        """计算错误率"""
        self._clean_window()
        
        if not self._window:
            return 0.0
        
        total = len(self._window)
        failures = sum(1 for _, is_success in self._window if not is_success)
        
        return (failures / total) * 100.0
    
    def _clean_window(self) -> None:
        """清理过期的窗口数据"""
        current_time = time.time()
        cutoff_time = current_time - self.time_window_seconds
        
        while self._window and self._window[0][0] < cutoff_time:
            self._window.popleft()
    
    def _transition_to(self, new_state: CircuitState) -> None:
        """
        状态转换
        
        Args:
            new_state: 新状态
        """
        old_state = self._stats.state
        self._stats.state = new_state
        self._stats.last_state_change = time.time()
        
        # 重置半开计数器
        if new_state != CircuitState.HALF_OPEN:
            self._half_open_calls = 0
        
        logger.warning(
            f"熔断器状态转换: {old_state.value} -> {new_state.value}"
        )
        
        # 触发告警（TODO: 集成告警系统）
        if new_state == CircuitState.OPEN:
            self._trigger_alert("熔断器已打开，Redis 可能故障")
        elif old_state == CircuitState.OPEN and new_state == CircuitState.CLOSED:
            self._trigger_alert("熔断器已恢复正常")
    
    def _trigger_alert(self, message: str) -> None:
        """
        触发告警
        
        Args:
            message: 告警消息
        """
        logger.warning(f"[ALERT] {message}")
        # TODO: 集成到告警系统（Prometheus Alertmanager）
    
    # ==================== 手动控制接口 ====================
    
    def force_open(self) -> None:
        """强制打开熔断器"""
        self._transition_to(CircuitState.OPEN)
    
    def force_close(self) -> None:
        """强制关闭熔断器"""
        self._transition_to(CircuitState.CLOSED)
    
    def get_stats(self) -> dict:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "state": self._stats.state.value,
            "error_rate": self._calculate_error_rate(),
            "total_calls": len(self._window),
            "window_seconds": self.time_window_seconds,
            "last_failure_time": self._stats.last_failure_time,
            "last_state_change": self._stats.last_state_change,
        }


class CircuitBreakerOpen(Exception):
    """熔断器打开异常"""
    pass
```

---

## 3. 模块设计

### 3.1 新增模块清单

| 模块名 | 路径 | 职责 | 对应 PRD 需求 |
|--------|------|------|---------------|
| `LocalCache` | `src/cache/local_cache.py` | 本地缓存管理（LRU + TTL） | [REQ_REDIS_CACHE_005] |
| `CircuitBreaker` | `src/cache/circuit_breaker.py` | 熔断器实现 | [REQ_REDIS_CACHE_002] |
| `CacheInvalidator` | `src/cache/invalidator.py` | 缓存失效广播和订阅 | [REQ_REDIS_CACHE_001] |
| `CacheWarmer` | `src/cache/warmer.py` | 缓存预热器 | [REQ_REDIS_CACHE_004] |

### 3.2 增强模块清单

| 模块名 | 路径 | 增强内容 | 对应 PRD 需求 |
|--------|------|---------|---------------|
| `CacheManager` | `src/cache/cache_manager.py` | 集成熔断器、本地缓存、批量操作 | [REQ_REDIS_CACHE_002][005][006] |
| `AgentConfigManager` | `src/core/config_manager.py` | 修复配置删除、优化缓存策略 | [REQ_REDIS_CACHE_001][008] |
| `CacheMetrics` | `src/cache/metrics.py` | 新增告警指标 | [REQ_REDIS_CACHE_003] |

### 3.3 CacheManager 集成设计

#### 3.3.1 集成架构

```python
# src/cache/cache_manager.py（增强版）

class CacheManager:
    """
    增强版缓存管理器
    
    集成组件：
    1. LocalCache（L1 缓存）
    2. CircuitBreaker（熔断器）
    3. CacheInvalidator（失效广播）
    4. RedisClient（L2 缓存）
    """
    
    def __init__(
        self,
        redis_client: RedisClient,
        serializer: Optional[CacheSerializer] = None,
        key_builder: Optional[CacheKeyBuilder] = None,
        enable_metrics: bool = True,
        enable_local_cache: bool = True,
        local_cache_maxsize: int = 1000,
        local_cache_ttl: float = 300.0,
        circuit_breaker_config: Optional[dict] = None
    ):
        """
        初始化缓存管理器
        
        Args:
            redis_client: Redis 客户端
            serializer: 序列化器
            key_builder: 缓存键构建器
            enable_metrics: 是否启用监控
            enable_local_cache: 是否启用本地缓存
            local_cache_maxsize: 本地缓存容量
            local_cache_ttl: 本地缓存 TTL
            circuit_breaker_config: 熔断器配置
        """
        self.redis_client = redis_client
        self.serializer = serializer or CacheSerializer()
        self.key_builder = key_builder or CacheKeyBuilder()
        self.enable_metrics = enable_metrics
        
        # 本地缓存（L1）
        self.local_cache: Optional[LocalCache] = None
        if enable_local_cache:
            self.local_cache = LocalCache(
                maxsize=local_cache_maxsize,
                ttl=local_cache_ttl
            )
        
        # 熔断器
        cb_config = circuit_breaker_config or {}
        self.circuit_breaker = CircuitBreaker(**cb_config)
        
        # 缓存失效器（延迟初始化，需要订阅）
        self.invalidator: Optional[CacheInvalidator] = None
    
    async def initialize(self) -> None:
        """初始化缓存管理器（启动订阅）"""
        if self.local_cache:
            self.invalidator = CacheInvalidator(
                redis_client=self.redis_client.client,
                local_cache=self.local_cache
            )
            await self.invalidator.start()
            logger.info("缓存管理器初始化完成")
    
    async def shutdown(self) -> None:
        """关闭缓存管理器"""
        if self.invalidator:
            await self.invalidator.stop()
        logger.info("缓存管理器已关闭")
    
    async def get(
        self,
        key: str,
        model_class: Optional[Type] = None,
        cache_type: str = "default"
    ) -> Optional[Any]:
        """
        获取缓存（增强版，支持 L1）
        
        流程：
        1. 查询 L1 本地缓存
        2. 查询 L2 Redis 缓存
        3. 返回结果
        
        Args:
            key: 缓存键
            model_class: 可选的 Pydantic 模型类
            cache_type: 缓存类型（用于监控）
            
        Returns:
            缓存值，不存在返回 None
        """
        # 1. 查询本地缓存
        if self.local_cache:
            local_value = self.local_cache.get(key)
            if local_value is not None:
                logger.debug(f"L1 缓存命中: {key}")
                if self.enable_metrics:
                    CacheMetrics.record_hit(cache_type)
                return local_value
        
        # 2. 通过熔断器查询 Redis
        try:
            async def _redis_get():
                return await self._get_from_redis(key, model_class, cache_type)
            
            cached = await self.circuit_breaker.call(_redis_get)
            
            # 3. 回填本地缓存
            if cached is not None and self.local_cache:
                self.local_cache.set(key, cached)
            
            return cached
            
        except CircuitBreakerOpen:
            logger.warning(f"熔断器打开，跳过 Redis: {key}")
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        cache_type: str = "default"
    ) -> bool:
        """
        设置缓存（增强版，支持 L1）
        
        流程：
        1. 写入 L1 本地缓存
        2. 通过熔断器写入 L2 Redis
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）
            cache_type: 缓存类型
            
        Returns:
            是否设置成功
        """
        # 1. 写入本地缓存
        if self.local_cache:
            self.local_cache.set(key, value)
        
        # 2. 通过熔断器写入 Redis
        try:
            async def _redis_set():
                return await self._set_to_redis(key, value, ttl, cache_type)
            
            return await self.circuit_breaker.call(_redis_set)
            
        except CircuitBreakerOpen:
            logger.warning(f"熔断器打开，跳过 Redis 写入: {key}")
            return False
    
    async def delete(
        self,
        key: str,
        cache_type: str = "default",
        broadcast: bool = True
    ) -> bool:
        """
        删除缓存（增强版，支持广播）
        
        流程：
        1. 删除 L1 本地缓存
        2. 通过熔断器删除 L2 Redis
        3. 广播缓存失效消息
        
        Args:
            key: 缓存键
            cache_type: 缓存类型
            broadcast: 是否广播失效消息
            
        Returns:
            是否删除成功
        """
        # 1. 删除本地缓存
        if self.local_cache:
            self.local_cache.delete(key)
        
        # 2. 通过熔断器删除 Redis
        try:
            async def _redis_delete():
                return await self._delete_from_redis(key, cache_type)
            
            result = await self.circuit_breaker.call(_redis_delete)
            
            # 3. 广播失效消息
            if broadcast and self.invalidator:
                await self.invalidator.publish_invalidation(key)
            
            return result
            
        except CircuitBreakerOpen:
            logger.warning(f"熔断器打开，跳过 Redis 删除: {key}")
            return False
    
    # ==================== 批量操作（新增） ====================
    
    async def mget(
        self,
        keys: List[str],
        model_class: Optional[Type] = None,
        cache_type: str = "default"
    ) -> List[Optional[Any]]:
        """
        批量获取缓存（新增）
        
        Args:
            keys: 缓存键列表
            model_class: 可选的 Pydantic 模型类
            cache_type: 缓存类型
            
        Returns:
            缓存值列表
        """
        results = []
        
        # 1. 从本地缓存获取
        if self.local_cache:
            for key in keys:
                local_value = self.local_cache.get(key)
                results.append(local_value)
        else:
            results = [None] * len(keys)
        
        # 2. 对本地缓存未命中的，从 Redis 批量获取
        miss_indices = [i for i, v in enumerate(results) if v is None]
        miss_keys = [keys[i] for i in miss_indices]
        
        if miss_keys:
            try:
                # 使用 Redis MGET
                safe_keys = [self.key_builder.build(k) for k in miss_keys]
                redis_values = await self.redis_client.client.mget(*safe_keys)
                
                # 反序列化并填充结果
                for i, (idx, key, redis_val) in enumerate(zip(miss_indices, miss_keys, redis_values)):
                    if redis_val:
                        value = self.serializer.deserialize(redis_val, model_class)
                        results[idx] = value
                        
                        # 回填本地缓存
                        if self.local_cache:
                            self.local_cache.set(key, value)
                
            except Exception as e:
                logger.error(f"批量获取失败: {e}")
        
        return results
    
    async def delete_batch(
        self,
        keys: List[str],
        cache_type: str = "default",
        broadcast: bool = True
    ) -> Tuple[int, List[str]]:
        """
        批量删除缓存（新增）
        
        Args:
            keys: 缓存键列表
            cache_type: 缓存类型
            broadcast: 是否广播失效消息
            
        Returns:
            (成功删除数量, 失败的键列表)
        """
        success_count = 0
        failed_keys = []
        
        # 1. 删除本地缓存
        if self.local_cache:
            for key in keys:
                self.local_cache.delete(key)
        
        # 2. 批量删除 Redis
        try:
            safe_keys = [self.key_builder.build(k) for k in keys]
            deleted_count = await self.redis_client.client.delete(*safe_keys)
            success_count = deleted_count
            
        except Exception as e:
            logger.error(f"批量删除失败: {e}")
            failed_keys = keys
        
        # 3. 广播失效消息
        if broadcast and self.invalidator:
            for key in keys:
                await self.invalidator.publish_invalidation(key)
        
        return success_count, failed_keys
```

### 3.4 缓存预热设计

```python
# src/cache/warmer.py（新增）

import asyncio
from typing import List, Callable, Optional
from loguru import logger

class CacheWarmer:
    """
    缓存预热器
    
    功能：
    1. 服务启动时预热高频数据
    2. 异步执行，不阻塞启动
    3. 提供手动触发接口
    """
    
    def __init__(
        self,
        cache_manager: "CacheManager",
        db_manager: "DatabaseManager",
        warmup_delay: int = 30
    ):
        """
        初始化预热器
        
        Args:
            cache_manager: 缓存管理器
            db_manager: 数据库管理器
            warmup_delay: 预热延迟（秒）
        """
        self.cache_manager = cache_manager
        self.db_manager = db_manager
        self.warmup_delay = warmup_delay
        self._task: Optional[asyncio.Task] = None
    
    async def start_background_warmup(self) -> None:
        """启动后台预热任务"""
        self._task = asyncio.create_task(self._delayed_warmup())
        logger.info(f"缓存预热任务已调度，将在 {self.warmup_delay} 秒后执行")
    
    async def _delayed_warmup(self) -> None:
        """延迟预热"""
        try:
            await asyncio.sleep(self.warmup_delay)
            await self.warmup_top_agents()
        except asyncio.CancelledError:
            logger.info("预热任务被取消")
        except Exception as e:
            logger.error(f"预热失败: {e}")
    
    async def warmup_top_agents(self, top_n: int = 10) -> int:
        """
        预热 Top N 高频 Agent 配置
        
        Args:
            top_n: 预热数量
            
        Returns:
            实际预热数量
        """
        logger.info(f"开始预热 Top {top_n} Agent 配置")
        
        # 1. 从数据库获取高频 Agent 列表
        top_agents = await self._get_top_agents(top_n)
        
        if not top_agents:
            logger.warning("未找到高频 Agent")
            return 0
        
        # 2. 批量加载到缓存
        warmed_count = 0
        for agent_id in top_agents:
            try:
                # 从数据库加载配置
                config = await self.db_manager.get_agent_config(agent_id)
                
                if config:
                    # 写入缓存
                    cache_key = CacheKeyBuilder.agent_config(agent_id)
                    await self.cache_manager.set(
                        cache_key,
                        config,
                        ttl=CacheTTL.AGENT_CONFIG,
                        cache_type="agent_config"
                    )
                    warmed_count += 1
                    
            except Exception as e:
                logger.error(f"预热 Agent {agent_id} 失败: {e}")
        
        logger.info(f"预热完成: {warmed_count}/{len(top_agents)}")
        
        # 更新预热指标
        CacheMetrics.record_warmup_progress(
            cache_type="agent_config",
            warmed=warmed_count,
            total=len(top_agents)
        )
        
        return warmed_count
    
    async def _get_top_agents(self, top_n: int) -> List[str]:
        """
        获取高频 Agent 列表
        
        Args:
            top_n: 数量
            
        Returns:
            Agent ID 列表
        """
        # TODO: 从数据库统计高频访问的 Agent
        # 临时实现：返回最近更新的 Agent
        sql = """
        SELECT agent_id 
        FROM t_sys_agents_configs 
        ORDER BY update_time DESC 
        LIMIT %s
        """
        
        results = await self.db_manager.fetch_all(sql, top_n)
        return [row["agent_id"] for row in results]
    
    async def manual_warmup(self, agent_ids: List[str]) -> int:
        """
        手动预热指定 Agent
        
        Args:
            agent_ids: Agent ID 列表
            
        Returns:
            实际预热数量
        """
        logger.info(f"手动预热 {len(agent_ids)} 个 Agent")
        
        warmed_count = 0
        for agent_id in agent_ids:
            try:
                config = await self.db_manager.get_agent_config(agent_id)
                if config:
                    cache_key = CacheKeyBuilder.agent_config(agent_id)
                    await self.cache_manager.set(
                        cache_key,
                        config,
                        ttl=CacheTTL.AGENT_CONFIG,
                        cache_type="agent_config"
                    )
                    warmed_count += 1
            except Exception as e:
                logger.error(f"手动预热 Agent {agent_id} 失败: {e}")
        
        return warmed_count
```

---

## 4. 配置管理器增强

### 4.1 配置删除功能修复

```python
# src/core/config_manager.py（增强版）

class AgentConfigManager:
    """配置管理器（增强版）"""
    
    async def remove_config(self, agent_id: str) -> bool:
        """
        删除配置（修复版）
        
        流程：
        1. 删除数据库记录
        2. 删除 Redis 缓存
        3. 删除本地缓存
        4. 广播失效消息
        
        Args:
            agent_id: Agent ID
            
        Returns:
            是否删除成功
        """
        try:
            # 1. 删除数据库记录
            deleted = await self._db_manager.delete_agent_config(agent_id)
            
            if not deleted:
                logger.warning(f"配置不存在: {agent_id}")
                return False
            
            # 2. 删除 Redis 缓存
            cache_key = CacheKeyBuilder.agent_config(agent_id)
            if self._cache_manager:
                await self._cache_manager.delete(
                    cache_key,
                    cache_type="agent_config",
                    broadcast=True  # 广播到其他实例
                )
            
            # 3. 删除本地缓存
            if agent_id in self._config_cache:
                del self._config_cache[agent_id]
            
            logger.info(f"配置已删除: {agent_id}")
            return True
            
        except Exception as e:
            logger.error(f"删除配置失败: {agent_id}, 错误: {e}")
            return False
    
    async def _delete_from_database(self, agent_id: str) -> bool:
        """
        从数据库删除配置
        
        Args:
            agent_id: Agent ID
            
        Returns:
            是否删除成功
        """
        # 使用事务保证原子性
        async with self._db_manager.get_session() as session:
            # 删除配置记录
            sql = text("""
                DELETE FROM t_sys_agents_configs
                WHERE agent_id = :agent_id
            """)
            
            result = await session.execute(sql, {"agent_id": agent_id})
            await session.commit()
            
            return result.rowcount > 0
```

### 4.2 缓存一致性增强

```python
async def get_config(self, agent_id: str) -> Optional[AgentConfig]:
    """
    获取配置（增强版）
    
    流程：
    1. 查询本地缓存
    2. 查询 Redis 缓存
    3. 查询数据库
    4. 回填缓存
    
    Args:
        agent_id: Agent ID
        
    Returns:
        Agent 配置
    """
    # 1. 查询本地缓存
    if agent_id in self._config_cache:
        return self._config_cache[agent_id]
    
    # 2. 查询 Redis 缓存
    if self._cache_manager:
        cache_key = CacheKeyBuilder.agent_config(agent_id)
        cached = await self._cache_manager.get(
            cache_key,
            model_class=AgentConfig,
            cache_type="agent_config"
        )
        
        if cached:
            # 回填本地缓存
            self._config_cache[agent_id] = cached
            return cached
    
    # 3. 查询数据库
    config = await self._db_manager.get_agent_config(agent_id)
    
    if not config:
        return None
    
    # 4. 回填缓存
    if self._cache_manager:
        cache_key = CacheKeyBuilder.agent_config(agent_id)
        await self._cache_manager.set(
            cache_key,
            config,
            ttl=CacheTTL.AGENT_CONFIG,
            cache_type="agent_config"
        )
    
    # 回填本地缓存
    self._config_cache[agent_id] = config
    
    return config

async def save_config(self, config: AgentConfig) -> bool:
    """
    保存配置（增强版）
    
    流程：
    1. 更新数据库
    2. 删除 Redis 缓存
    3. 删除本地缓存
    4. 广播失效消息
    
    Args:
        config: Agent 配置
        
    Returns:
        是否保存成功
    """
    try:
        # 1. 更新数据库
        saved = await self._db_manager.save_agent_config(config)
        
        if not saved:
            return False
        
        # 2. 删除 Redis 缓存（Cache-Aside）
        cache_key = CacheKeyBuilder.agent_config(config.agent_id)
        if self._cache_manager:
            await self._cache_manager.delete(
                cache_key,
                cache_type="agent_config",
                broadcast=True
            )
        
        # 3. 删除本地缓存
        if config.agent_id in self._config_cache:
            del self._config_cache[config.agent_id]
        
        logger.info(f"配置已保存: {config.agent_id}")
        return True
        
    except Exception as e:
        logger.error(f"保存配置失败: {config.agent_id}, 错误: {e}")
        return False
```

---

## 5. API 接口设计

### 5.1 新增接口

| 方法 | 路径 | 描述 | 对应需求 |
|------|------|------|----------|
| GET | `/api/v1/cache/health` | 缓存健康检查 | [REQ_REDIS_CACHE_007] |
| GET | `/api/v1/cache/stats` | 缓存统计信息 | [REQ_REDIS_CACHE_007] |
| POST | `/api/v1/cache/clear` | 清除所有缓存 | [REQ_REDIS_CACHE_001] |
| POST | `/api/v1/cache/warmup` | 手动触发预热 | [REQ_REDIS_CACHE_004] |
| POST | `/api/v1/cache/circuit-breaker/open` | 手动开启熔断 | [REQ_REDIS_CACHE_002] |
| POST | `/api/v1/cache/circuit-breaker/close` | 手动关闭熔断 | [REQ_REDIS_CACHE_002] |

### 5.2 接口实现

```python
# src/api/router.py（新增）

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

class CacheHealthResponse(BaseModel):
    """缓存健康检查响应"""
    status: str
    connected: bool
    memory_used_mb: float
    keys_count: int
    degradation_count: int
    circuit_breaker_state: str
    local_cache_hit_rate: float

class CacheStatsResponse(BaseModel):
    """缓存统计响应"""
    hits_total: int
    misses_total: int
    hit_rate: float
    fallback_count: int
    degradation_count: int
    latency_p50: float
    latency_p99: float

@api_router.get("/cache/health", response_model=CacheHealthResponse)
async def get_cache_health():
    """
    获取缓存健康状态
    
    Returns:
        CacheHealthResponse
    """
    cache_manager = get_cache_manager()
    
    if not cache_manager:
        raise HTTPException(status_code=503, detail="缓存管理器未初始化")
    
    # 获取 Redis 状态
    redis_stats = await cache_manager.get_stats()
    
    # 获取熔断器状态
    cb_stats = cache_manager.circuit_breaker.get_stats()
    
    # 获取本地缓存统计
    local_stats = {}
    if cache_manager.local_cache:
        local_stats = cache_manager.local_cache.get_stats()
    
    return CacheHealthResponse(
        status=redis_stats.get("connected", False) and "healthy" or "unhealthy",
        connected=redis_stats.get("connected", False),
        memory_used_mb=redis_stats.get("memory_used_mb", 0.0),
        keys_count=redis_stats.get("keys_count", 0),
        degradation_count=redis_stats.get("degradation_count", 0),
        circuit_breaker_state=cb_stats["state"],
        local_cache_hit_rate=local_stats.get("hit_rate", 0.0)
    )

@api_router.get("/cache/stats", response_model=CacheStatsResponse)
async def get_cache_stats():
    """
    获取缓存统计信息
    
    Returns:
        CacheStatsResponse
    """
    # 从 Prometheus 指标获取统计数据
    # TODO: 实现从 Prometheus 客户端获取
    pass

@api_router.post("/cache/clear")
async def clear_all_cache():
    """
    清除所有缓存
    
    Returns:
        操作结果
    """
    cache_manager = get_cache_manager()
    
    if not cache_manager:
        raise HTTPException(status_code=503, detail="缓存管理器未初始化")
    
    try:
        # 1. 清除 Redis 缓存
        await cache_manager.delete_pattern("agent:*")
        
        # 2. 清除本地缓存
        if cache_manager.local_cache:
            cache_manager.local_cache.clear()
        
        return {"success": True, "message": "缓存已清除"}
        
    except Exception as e:
        logger.error(f"清除缓存失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/cache/warmup")
async def trigger_cache_warmup(top_n: int = 10):
    """
    手动触发缓存预热
    
    Args:
        top_n: 预热数量
        
    Returns:
        操作结果
    """
    cache_warmer = get_cache_warmer()
    
    if not cache_warmer:
        raise HTTPException(status_code=503, detail="缓存预热器未初始化")
    
    try:
        warmed_count = await cache_warmer.warmup_top_agents(top_n)
        return {
            "success": True,
            "warmed_count": warmed_count,
            "message": f"已预热 {warmed_count} 个配置"
        }
    except Exception as e:
        logger.error(f"手动预热失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/cache/circuit-breaker/open")
async def force_open_circuit_breaker():
    """
    手动打开熔断器
    
    Returns:
        操作结果
    """
    cache_manager = get_cache_manager()
    
    if not cache_manager:
        raise HTTPException(status_code=503, detail="缓存管理器未初始化")
    
    cache_manager.circuit_breaker.force_open()
    return {"success": True, "message": "熔断器已手动打开"}

@api_router.post("/cache/circuit-breaker/close")
async def force_close_circuit_breaker():
    """
    手动关闭熔断器
    
    Returns:
        操作结果
    """
    cache_manager = get_cache_manager()
    
    if not cache_manager:
        raise HTTPException(status_code=503, detail="缓存管理器未初始化")
    
    cache_manager.circuit_breaker.force_close()
    return {"success": True, "message": "熔断器已手动关闭"}
```

---

## 6. 监控告警设计

### 6.1 Prometheus 告警规则

```yaml
# config/prometheus_alerts.yml（新增）

groups:
  - name: cache_alerts
    rules:
      # 告警 1：缓存命中率低于 80%
      - alert: CacheHitRateLow
        expr: |
          (
            sum(rate(cache_hits_total[5m]))
            /
            (sum(rate(cache_hits_total[5m])) + sum(rate(cache_misses_total[5m])))
          ) < 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "缓存命中率过低"
          description: "缓存命中率为 {{ $value | humanizePercentage }}，低于 80% 阈值"
      
      # 告警 2：Redis 连接数超过 80%
      - alert: RedisConnectionsHigh
        expr: |
          redis_connections_active / redis_max_connections > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Redis 连接数过高"
          description: "Redis 连接数使用率为 {{ $value | humanizePercentage }}"
      
      # 告警 3：缓存降级次数过多
      - alert: CacheDegradationHigh
        expr: |
          increase(cache_degradation_total[5m]) > 100
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "缓存降级次数过多"
          description: "5 分钟内缓存降级 {{ $value }} 次，可能 Redis 故障"
      
      # 告警 4：熔断器打开
      - alert: CircuitBreakerOpen
        expr: |
          cache_circuit_breaker_state{state="open"} == 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "熔断器已打开"
          description: "缓存熔断器已打开，所有请求降级到数据库"
      
      # 告警 5：缓存延迟过高
      - alert: CacheLatencyHigh
        expr: |
          histogram_quantile(0.99, rate(cache_latency_seconds_bucket[5m])) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "缓存延迟过高"
          description: "缓存 P99 延迟为 {{ $value | humanizeDuration }}"
```

### 6.2 新增监控指标

```python
# src/cache/metrics.py（增强版）

class CacheMetrics:
    # ... 原有指标 ...
    
    # ==================== 新增指标 ====================
    
    # 熔断器状态
    circuit_breaker_state = Gauge(
        'cache_circuit_breaker_state',
        '熔断器状态（0=closed, 1=open, 2=half_open）',
        ['breaker_name']
    )
    
    # 本地缓存命中率
    local_cache_hit_rate = Gauge(
        'cache_local_hit_rate',
        '本地缓存命中率',
        ['cache_type']
    )
    
    # 批量操作计数
    cache_batch_operations_total = Counter(
        'cache_batch_operations_total',
        '批量操作总次数',
        ['operation', 'cache_type']
    )
    
    # 预热进度
    cache_warmup_progress_percent = Gauge(
        'cache_warmup_progress_percent',
        '预热进度百分比',
        ['cache_type']
    )
    
    @staticmethod
    def update_circuit_breaker_state(state: CircuitState):
        """更新熔断器状态指标"""
        state_value = {
            CircuitState.CLOSED: 0,
            CircuitState.OPEN: 1,
            CircuitState.HALF_OPEN: 2
        }.get(state, 0)
        
        CacheMetrics.circuit_breaker_state.labels(
            breaker_name="default"
        ).set(state_value)
```

---

## 7. 配置参数

### 7.1 环境变量配置

```bash
# .env（新增配置）

# 本地缓存配置
CACHE_L1_ENABLED=true
CACHE_L1_MAXSIZE=1000
CACHE_L1_TTL=300

# Redis 配置（已存在）
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
REDIS_MAX_CONNECTIONS=50

# 熔断器配置
CIRCUIT_BREAKER_ERROR_THRESHOLD=50
CIRCUIT_BREAKER_TIME_WINDOW=10
CIRCUIT_BREAKER_RECOVERY_TIMEOUT=30
CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS=3

# 缓存预热配置
CACHE_WARMUP_ENABLED=true
CACHE_WARMUP_DELAY=30
CACHE_WARMUP_TOP_N=10

# 缓存 TTL 配置
CACHE_TTL_AGENT_CONFIG=3600
CACHE_TTL_SESSION_HISTORY=1800
```

### 7.2 配置加载

```python
# src/config.py（增强版）

from pydantic_settings import BaseSettings

class CacheSettings(BaseSettings):
    """缓存配置"""
    
    # L1 本地缓存
    cache_l1_enabled: bool = True
    cache_l1_maxsize: int = 1000
    cache_l1_ttl: int = 300
    
    # 熔断器
    circuit_breaker_error_threshold: float = 50.0
    circuit_breaker_time_window: float = 10.0
    circuit_breaker_recovery_timeout: float = 30.0
    circuit_breaker_half_open_max_calls: int = 3
    
    # 预热
    cache_warmup_enabled: bool = True
    cache_warmup_delay: int = 30
    cache_warmup_top_n: int = 10
    
    # TTL
    cache_ttl_agent_config: int = 3600
    cache_ttl_session_history: int = 1800
    
    class Config:
        env_file = ".env"
        env_prefix = ""
```

---

## 8. 实施计划

### 8.1 Sprint 1（2 周）- 核心功能

**目标**：解决高优先级问题，建立核心能力

| 任务 | 优先级 | 预估工时 | 负责人 | 对应需求 |
|------|--------|---------|--------|----------|
| 实现 LocalCache 模块 | P0 | 4h | 开发 | [REQ_REDIS_CACHE_005] |
| 实现 CircuitBreaker 模块 | P0 | 8h | 开发 | [REQ_REDIS_CACHE_002] |
| 实现 CacheInvalidator 模块 | P0 | 8h | 开发 | [REQ_REDIS_CACHE_001] |
| 修复配置删除功能 | P0 | 4h | 开发 | [REQ_REDIS_CACHE_008] |
| 集成到 CacheManager | P0 | 8h | 开发 | 多个需求 |
| 添加健康检查 API | P1 | 4h | 开发 | [REQ_REDIS_CACHE_007] |

**交付物**：
- ✅ LocalCache 模块实现
- ✅ CircuitBreaker 模块实现
- ✅ CacheInvalidator 模块实现
- ✅ 配置删除功能完整实现
- ✅ CacheManager 集成完成
- ✅ 健康检查 API 实现

### 8.2 Sprint 2（2 周）- 监控与优化

**目标**：完善监控告警，优化性能

| 任务 | 优先级 | 预估工时 | 负责人 | 对应需求 |
|------|--------|---------|--------|----------|
| 实现 CacheWarmer 模块 | P1 | 8h | 开发 | [REQ_REDIS_CACHE_004] |
| 实现批量操作接口 | P2 | 8h | 开发 | [REQ_REDIS_CACHE_006] |
| 编写 Prometheus 告警规则 | P1 | 4h | 开发 | [REQ_REDIS_CACHE_003] |
| 集成 Grafana 大盘 | P2 | 8h | 运维 | [REQ_REDIS_CACHE_003] |
| 编写单元测试 | P1 | 16h | 测试 | 所有需求 |
| 性能测试 | P1 | 8h | 测试 | [NFR_REDIS_CACHE_001] |

**交付物**：
- ✅ CacheWarmer 模块实现
- ✅ 批量操作接口实现
- ✅ Prometheus 告警规则配置
- ✅ Grafana 监控大盘
- ✅ 单元测试覆盖率 > 80%
- ✅ 性能测试报告

### 8.3 Sprint 3（1 周）- 测试与文档

**目标**：完善测试和文档，准备上线

| 任务 | 优先级 | 预估工时 | 负责人 |
|------|--------|---------|--------|
| 集成测试 | P1 | 12h | 测试 |
| 灰度发布方案 | P1 | 4h | 运维 |
| 编写运维文档 | P2 | 4h | 开发 |
| 编写 API 文档 | P2 | 4h | 开发 |

**交付物**：
- ✅ 集成测试通过
- ✅ 灰度发布方案
- ✅ 运维文档
- ✅ API 文档

---

## 9. 测试方案

### 9.1 单元测试

**测试范围**：
- `CircuitBreaker` 状态机转换逻辑
- `LocalCache` LRU 淘汰策略
- `CacheInvalidator` Pub/Sub 逻辑
- `CacheManager` 读写操作
- `CacheWarmer` 预热逻辑

**测试覆盖率目标**：> 80%

### 9.2 集成测试

**测试场景**：

| 场景 | 测试内容 | 预期结果 |
|------|---------|---------|
| 缓存一致性 | 多实例并发更新配置 | 5 秒内所有实例缓存失效 |
| 熔断器 | 模拟 Redis 故障 | 50% 错误率时自动熔断 |
| 缓存预热 | 服务启动后自动预热 | 高频配置加载到缓存 |
| 降级恢复 | Redis 恢复后自动恢复 | 30 秒内恢复正常 |
| 批量操作 | 批量读取/删除 | 性能提升 50% 以上 |

### 9.3 性能测试

**测试指标**：

| 指标 | 目标值 | 测试方法 |
|------|--------|---------|
| 缓存命中率 | ≥ 85% | 压测 10 分钟统计 |
| 读取延迟 P99 | ≤ 10ms | JMeter 压测 |
| 吞吐量 | ≥ 10,000 QPS | wrk 压测 |
| 内存占用 | ≤ 100MB (1000 配置) | 监控统计 |

---

## 10. 风险评估

### 10.1 技术风险

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| Redis Pub/Sub 消息丢失 | 中 | 实现消息确认机制 + 重试，必要时使用消息队列 |
| 熔断器误熔断 | 中 | 调整阈值参数 + 手动恢复接口 + 监控告警 |
| 本地缓存 OOM | 低 | 严格限制容量（1000 条）+ TTL（300s）+ 监控 |
| 批量操作性能下降 | 低 | 限制单批次大小（100 条）+ Pipeline 优化 |
| 预热阻塞启动 | 低 | 异步执行 + 延迟 30 秒 + 失败不影响启动 |

### 10.2 业务风险

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| 缓存失效导致数据库压力激增 | 高 | 熔断器 + 限流 + 降级 + 数据库读写分离 |
| 配置更新延迟影响业务 | 中 | 优化 Pub/Sub 性能 + 监控告警 + 5 秒 SLA |
| 灰度期间数据不一致 | 中 | 严格灰度流程 + 快速回滚 + 监控对比 |

---

## 11. 部署方案

### 11.1 灰度发布

**阶段一**：单实例灰度（1 周）
- 选择 1 个实例部署新版本
- 监控缓存命中率、错误率、延迟
- 验证熔断器和降级逻辑

**阶段二**：部分流量灰度（1 周）
- 30% 流量切换到新版本
- 对比新旧版本性能指标
- 验证缓存一致性

**阶段三**：全量发布（1 周）
- 全量切换到新版本
- 持续监控 1 周
- 优化和调整参数

### 11.2 回滚方案

**触发条件**：
- 缓存命中率 < 60%
- 错误率 > 10%
- 服务响应时间 P99 > 500ms

**回滚步骤**：
1. 切换流量到旧版本
2. 分析问题根因
3. 修复后重新灰度

---

## 12. 需求追溯矩阵

### 12.1 功能需求追溯

| PRD 需求 ID | 需求描述 | 设计章节 | 涉及模块 | 验收标准 |
|-------------|---------|---------|---------|---------|
| [REQ_REDIS_CACHE_001] | 缓存一致性保障 | §2.2, §3.3, §4.2 | CacheInvalidator, AgentConfigManager | 5 秒内所有实例缓存失效 |
| [REQ_REDIS_CACHE_002] | 熔断器机制 | §2.3, §3.1, §3.3 | CircuitBreaker, CacheManager | 50% 错误率时自动熔断 |
| [REQ_REDIS_CACHE_003] | 监控告警体系 | §6, §3.2 | CacheMetrics, Prometheus | 缓存命中率 < 80% 触发告警 |
| [REQ_REDIS_CACHE_004] | 缓存预热功能 | §3.4 | CacheWarmer | 启动后自动预热 Top 10 Agent |
| [REQ_REDIS_CACHE_005] | 本地缓存优化 | §2.1, §3.1 | LocalCache | LRU 淘汰 + 容量 1000 + TTL 300s |
| [REQ_REDIS_CACHE_006] | 批量操作优化 | §3.3 | CacheManager | mget/delete_batch 性能提升 50% |
| [REQ_REDIS_CACHE_007] | 缓存健康检查增强 | §5 | API Router | 详细健康状态 + 统计信息 |
| [REQ_REDIS_CACHE_008] | 配置删除功能修复 | §4.1 | AgentConfigManager | 删除配置同时删除 DB + Redis + Local |

### 12.2 非功能需求追溯

| PRD 需求 ID | 需求描述 | 设计章节 | 验收标准 |
|-------------|---------|---------|---------|
| [NFR_REDIS_CACHE_001] | 性能要求 | §9.3 | 缓存命中率 ≥ 85%, 延迟 P99 ≤ 10ms, 吞吐量 ≥ 10,000 QPS |
| [NFR_REDIS_CACHE_002] | 可用性要求 | §2.3, §3.3 | Redis 故障时系统可用性 ≥ 99.5%, 熔断恢复 ≤ 60s |
| [NFR_REDIS_CACHE_003] | 可观测性要求 | §6 | 10+ 核心指标, 告警延迟 ≤ 1min, 结构化日志 |
| [NFR_REDIS_CACHE_004] | 安全性要求 | §7 | 缓存不存储敏感信息, 管理接口需权限验证 |

---

## 13. 附录

### 13.1 参考资料

1. **PRD 文档**：`/home/ubuntu/vrt-projects/projects/AgentEngine-dev/docs/specs/REDIS_CACHE_spec.md`
2. **存量代码解剖报告**：`/home/ubuntu/vrt-projects/projects/AgentEngine-dev/.staging/legacy_code_anatomy.md`
3. **系统设计文档**：`/home/ubuntu/vrt-projects/projects/AgentEngine-dev/docs/DESIGN.md`
4. **现有缓存源码**：`/home/ubuntu/vrt-projects/projects/AgentEngine-dev/src/cache/`

### 13.2 术语表

| 术语 | 说明 |
|------|------|
| L1 缓存 | 本地内存缓存，容量小、速度快 |
| L2 缓存 | Redis 分布式缓存，容量大、共享 |
| Read-Through | 读取时自动回填缓存的策略 |
| Write-Through | 写入时同时更新缓存的策略 |
| Cache-Aside | 更新时删除缓存的策略 |
| 熔断器 | 防止级联故障的保护机制 |
| LRU | 最近最少使用淘汰算法 |
| TTL | Time To Live，缓存过期时间 |
| Pub/Sub | 发布订阅模式 |
| SSE | Server-Sent Events，服务器推送事件 |

### 13.3 配置参数清单

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `CACHE_L1_ENABLED` | true | 是否启用本地缓存 |
| `CACHE_L1_MAXSIZE` | 1000 | 本地缓存容量 |
| `CACHE_L1_TTL` | 300 | 本地缓存 TTL（秒） |
| `CACHE_TTL_AGENT_CONFIG` | 3600 | Agent 配置 Redis TTL（秒） |
| `CIRCUIT_BREAKER_ERROR_THRESHOLD` | 50 | 熔断器错误率阈值（%） |
| `CIRCUIT_BREAKER_TIME_WINDOW` | 10 | 熔断器统计窗口（秒） |
| `CIRCUIT_BREAKER_RECOVERY_TIMEOUT` | 30 | 熔断器恢复超时（秒） |
| `CACHE_WARMUP_DELAY` | 30 | 预热延迟时间（秒） |
| `CACHE_WARMUP_TOP_N` | 10 | 预热 Top N 数量 |
| `CACHE_BATCH_SIZE` | 100 | 批量操作大小限制 |

---

## 14. 审批记录

| 角色 | 姓名 | 审批状态 | 审批时间 | 意见 |
|------|------|---------|---------|------|
| 产品经理 | - | 待审批 | - | - |
| 技术负责人 | - | 待审批 | - | - |
| 架构师 | SA Agent | 已编写 | 2026-03-24 | 符合 PRD 要求，设计合理 |
| 测试负责人 | - | 待审批 | - | - |

---

**文档结束**

---

[SA_APPROVED]
