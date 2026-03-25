"""
L1 本地缓存模块
基于 cachetools.TTLCache 实现本地缓存，支持 LRU 淘汰和 TTL 过期
"""

from typing import Any, Optional, Dict, Tuple
from cachetools import TTLCache
from loguru import logger


class LocalCacheStats:
    """本地缓存统计信息"""
    
    def __init__(self):
        self.hits = 0  # 命中次数
        self.misses = 0  # 未命中次数
        self.evictions = 0  # 淘汰次数
        self.expirations = 0  # 过期次数
    
    @property
    def total_requests(self) -> int:
        """总请求数"""
        return self.hits + self.misses
    
    @property
    def hit_rate(self) -> float:
        """命中率"""
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "total_requests": self.total_requests,
            "hit_rate": round(self.hit_rate, 4),
            "current_size": 0  # 由 LocalCache 填充
        }


class LocalCache:
    """
    L1 本地缓存
    
    特性：
    - 基于 TTLCache 实现，支持 LRU 淘汰策略
    - 支持 TTL 过期时间
    - 容量限制，防止 OOM
    - 提供统计信息
    
    对应需求：[REQ_REDIS_CACHE_005] 本地缓存优化（增强）
    """
    
    def __init__(
        self,
        maxsize: int = 1000,
        ttl: float = 300.0
    ):
        """
        初始化本地缓存
        
        Args:
            maxsize: 最大容量（默认 1000，可配置 CACHE_L1_MAXSIZE）
            ttl: TTL 过期时间（秒，默认 300s，可配置 CACHE_L1_TTL）
        """
        self.maxsize = maxsize
        self.ttl = ttl
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._stats = LocalCacheStats()
        
        logger.info(
            f"LocalCache 初始化完成 - maxsize={maxsize}, ttl={ttl}s"
        )
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，不存在或过期返回 None
        """
        try:
            value = self._cache.get(key)
            if value is not None:
                self._stats.hits += 1
                logger.debug(f"LocalCache 命中: {key}")
                return value
            else:
                self._stats.misses += 1
                logger.debug(f"LocalCache 未命中: {key}")
                return None
        except Exception as e:
            # TTLCache 内部错误（如过期清理）
            self._stats.misses += 1
            logger.warning(f"LocalCache GET 异常: {key}, 错误: {e}")
            return None
    
    def set(self, key: str, value: Any) -> bool:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            
        Returns:
            是否设置成功
        """
        try:
            # 检查是否会触发淘汰
            if len(self._cache) >= self.maxsize and key not in self._cache:
                self._stats.evictions += 1
                logger.debug(f"LocalCache 触发淘汰: {key}")
            
            self._cache[key] = value
            logger.debug(f"LocalCache 设置: {key}")
            return True
        except Exception as e:
            logger.error(f"LocalCache SET 失败: {key}, 错误: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """
        删除缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            是否删除成功（键不存在也返回 True）
        """
        try:
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"LocalCache 删除: {key}")
            return True
        except Exception as e:
            logger.warning(f"LocalCache DELETE 失败: {key}, 错误: {e}")
            return False
    
    def clear(self) -> bool:
        """
        清空所有缓存
        
        Returns:
            是否清空成功
        """
        try:
            self._cache.clear()
            logger.info("LocalCache 已清空")
            return True
        except Exception as e:
            logger.error(f"LocalCache CLEAR 失败: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """
        检查键是否存在
        
        Args:
            key: 缓存键
            
        Returns:
            键是否存在
        """
        return key in self._cache
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        stats = self._stats.to_dict()
        stats["current_size"] = len(self._cache)
        stats["maxsize"] = self.maxsize
        stats["ttl"] = self.ttl
        return stats
    
    def get_size(self) -> int:
        """
        获取当前缓存大小
        
        Returns:
            当前缓存的键数量
        """
        return len(self._cache)
    
    def get_keys(self) -> list:
        """
        获取所有缓存键（用于调试）
        
        Returns:
            所有缓存键列表
        """
        return list(self._cache.keys())
    
    def delete_batch(self, keys: list) -> Tuple[int, int]:
        """
        批量删除缓存键
        
        Args:
            keys: 要删除的键列表
            
        Returns:
            (成功数量, 失败数量)
        """
        success_count = 0
        fail_count = 0
        
        for key in keys:
            if self.delete(key):
                success_count += 1
            else:
                fail_count += 1
        
        logger.info(
            f"LocalCache 批量删除完成 - 成功: {success_count}, 失败: {fail_count}"
        )
        return success_count, fail_count


# 模块级单例（可选使用）
_local_cache_instance: Optional[LocalCache] = None


def get_local_cache(
    maxsize: int = 1000,
    ttl: float = 300.0,
    reset: bool = False
) -> LocalCache:
    """
    获取本地缓存单例
    
    Args:
        maxsize: 最大容量
        ttl: TTL 过期时间
        reset: 是否重置单例
        
    Returns:
        LocalCache 实例
    """
    global _local_cache_instance
    
    if _local_cache_instance is None or reset:
        _local_cache_instance = LocalCache(maxsize=maxsize, ttl=ttl)
    
    return _local_cache_instance
