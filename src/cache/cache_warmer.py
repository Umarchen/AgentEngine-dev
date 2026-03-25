"""
缓存预热模块
在服务启动时自动预热高频访问的缓存数据
"""

import asyncio
from typing import Optional, List, Callable, Any
from loguru import logger


class CacheWarmerStats:
    """缓存预热统计信息"""
    
    def __init__(self):
        self.total_warmups = 0  # 总预热次数
        self.success_count = 0  # 成功预热数量
        self.failure_count = 0  # 失败预热数量
        self.last_warmup_time: Optional[float] = None  # 最后预热时间
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "total_warmups": self.total_warmups,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_warmup_time": self.last_warmup_time
        }


class CacheWarmer:
    """
    缓存预热器
    
    功能：
    1. 服务启动后自动预热高频访问的 Agent 配置
    2. 支持手动触发预热
    3. 异步执行，不阻塞服务启动
    
    对应需求：[REQ_REDIS_CACHE_004] 缓存预热功能（新增）
    """
    
    def __init__(
        self,
        cache_manager: Any,  # CacheManager 实例
        get_top_agents_func: Callable[[], List[str]],
        delay_seconds: int = 30,
        top_n: int = 10
    ):
        """
        初始化缓存预热器
        
        Args:
            cache_manager: 缓存管理器实例
            get_top_agents_func: 获取高频 Agent ID 列表的函数
            delay_seconds: 启动后延迟多少秒开始预热（默认 30s）
            top_n: 预热 Top N 个高频 Agent（默认 10）
        """
        self.cache_manager = cache_manager
        self.get_top_agents_func = get_top_agents_func
        self.delay_seconds = delay_seconds
        self.top_n = top_n
        
        # 后台任务
        self._warmup_task: Optional[asyncio.Task] = None
        
        # 统计信息
        self._stats = CacheWarmerStats()
        
        logger.info(
            f"CacheWarmer 初始化 - delay={delay_seconds}s, top_n={top_n}"
        )
    
    async def start_background_warmup(self):
        """
        启动后台预热任务
        
        延迟 delay_seconds 秒后开始预热
        """
        if self._warmup_task and not self._warmup_task.done():
            logger.warning("CacheWarmer 后台预热任务已在运行")
            return
        
        self._warmup_task = asyncio.create_task(
            self._delayed_warmup()
        )
        
        logger.info(
            f"CacheWarmer 后台预热任务已启动 - "
            f"将在 {self.delay_seconds} 秒后开始"
        )
    
    async def _delayed_warmup(self):
        """
        延迟预热（后台任务）
        """
        try:
            # 延迟等待
            await asyncio.sleep(self.delay_seconds)
            
            # 执行预热
            await self.warmup_top_agents()
        
        except asyncio.CancelledError:
            logger.info("CacheWarmer 后台预热任务已取消")
        except Exception as e:
            logger.error(f"CacheWarmer 后台预热任务失败: {e}")
    
    async def warmup_top_agents(self) -> dict:
        """
        预热高频 Agent 配置
        
        Returns:
            预热结果统计
        """
        logger.info(f"CacheWarmer 开始预热 Top {self.top_n} Agent 配置")
        
        self._stats.total_warmups += 1
        self._stats.last_warmup_time = asyncio.get_event_loop().time()
        
        result = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "agents": []
        }
        
        try:
            # 获取高频 Agent ID 列表
            agent_ids = await self._get_top_agents()
            
            if not agent_ids:
                logger.info("CacheWarmer 未获取到高频 Agent 列表")
                return result
            
            result["total"] = len(agent_ids)
            
            # 批量预热
            for agent_id in agent_ids:
                try:
                    # 触发缓存加载（从数据库加载到缓存）
                    # 这里假设 cache_manager.get() 会自动回源数据库
                    # 如果有专门的 warmup 方法，使用 warmup 方法
                    if hasattr(self.cache_manager, 'warmup'):
                        await self.cache_manager.warmup(agent_id)
                    else:
                        # 使用 get 触发缓存加载
                        await self.cache_manager.get(agent_id)
                    
                    result["success"] += 1
                    self._stats.success_count += 1
                    result["agents"].append({
                        "agent_id": agent_id,
                        "status": "success"
                    })
                    
                    logger.debug(f"CacheWarmer 预热成功: {agent_id}")
                
                except Exception as e:
                    result["failed"] += 1
                    self._stats.failure_count += 1
                    result["agents"].append({
                        "agent_id": agent_id,
                        "status": "failed",
                        "error": str(e)
                    })
                    
                    logger.warning(
                        f"CacheWarmer 预热失败: {agent_id}, 错误: {e}"
                    )
            
            logger.info(
                f"CacheWarmer 预热完成 - "
                f"总数: {result['total']}, "
                f"成功: {result['success']}, "
                f"失败: {result['failed']}"
            )
        
        except Exception as e:
            logger.error(f"CacheWarmer 预热过程失败: {e}")
            self._stats.failure_count += 1
        
        return result
    
    async def _get_top_agents(self) -> List[str]:
        """
        获取高频访问的 Agent ID 列表
        
        Returns:
            Agent ID 列表
        """
        try:
            # 调用外部函数获取高频 Agent
            if asyncio.iscoroutinefunction(self.get_top_agents_func):
                agent_ids = await self.get_top_agents_func()
            else:
                agent_ids = self.get_top_agents_func()
            
            # 限制数量
            if len(agent_ids) > self.top_n:
                agent_ids = agent_ids[:self.top_n]
            
            logger.info(
                f"CacheWarmer 获取到 {len(agent_ids)} 个高频 Agent"
            )
            
            return agent_ids
        
        except Exception as e:
            logger.error(f"CacheWarmer 获取高频 Agent 列表失败: {e}")
            return []
    
    async def warmup_keys(self, keys: List[str]) -> dict:
        """
        预热指定的缓存键
        
        Args:
            keys: 缓存键列表
            
        Returns:
            预热结果统计
        """
        logger.info(f"CacheWarmer 开始预热 {len(keys)} 个缓存键")
        
        result = {
            "total": len(keys),
            "success": 0,
            "failed": 0,
            "keys": []
        }
        
        for key in keys:
            try:
                # 触发缓存加载
                if hasattr(self.cache_manager, 'warmup'):
                    await self.cache_manager.warmup(key)
                else:
                    await self.cache_manager.get(key)
                
                result["success"] += 1
                result["keys"].append({
                    "key": key,
                    "status": "success"
                })
            
            except Exception as e:
                result["failed"] += 1
                result["keys"].append({
                    "key": key,
                    "status": "failed",
                    "error": str(e)
                })
                
                logger.warning(f"CacheWarmer 预热缓存键失败: {key}, 错误: {e}")
        
        logger.info(
            f"CacheWarmer 缓存键预热完成 - "
            f"成功: {result['success']}, 失败: {result['failed']}"
        )
        
        return result
    
    def cancel(self):
        """
        取消后台预热任务
        """
        if self._warmup_task and not self._warmup_task.done():
            self._warmup_task.cancel()
            logger.info("CacheWarmer 后台预热任务已取消")
    
    def get_stats(self) -> dict:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        stats = self._stats.to_dict()
        stats.update({
            "delay_seconds": self.delay_seconds,
            "top_n": self.top_n,
            "task_running": self._warmup_task is not None and not self._warmup_task.done()
        })
        return stats


# 全局单例（可选）
_cache_warmer_instance: Optional[CacheWarmer] = None


def get_cache_warmer(
    cache_manager: Any,
    get_top_agents_func: Callable[[], List[str]],
    delay_seconds: int = 30,
    top_n: int = 10,
    reset: bool = False
) -> CacheWarmer:
    """
    获取缓存预热器单例
    
    Args:
        cache_manager: 缓存管理器实例
        get_top_agents_func: 获取高频 Agent ID 列表的函数
        delay_seconds: 启动后延迟秒数
        top_n: 预热 Top N 个
        reset: 是否重置单例
        
    Returns:
        CacheWarmer 实例
    """
    global _cache_warmer_instance
    
    if _cache_warmer_instance is None or reset:
        _cache_warmer_instance = CacheWarmer(
            cache_manager=cache_manager,
            get_top_agents_func=get_top_agents_func,
            delay_seconds=delay_seconds,
            top_n=top_n
        )
    
    return _cache_warmer_instance
