"""
缓存预热模块
提供服务启动时自动预热高频访问的缓存数据

对应需求：
- [REQ_REDIS_CACHE_004] 缓存预热功能
"""

import asyncio
from typing import List, Optional

from loguru import logger


class CacheWarmer:
    """
    缓存预热器
    
    功能：
    1. 服务启动时预热高频数据
    2. 异步执行，不阻塞启动
    3. 提供手动触发接口
    4. 支持多种数据源预热
    
    使用场景：
    - 服务冷启动时减少数据库压力
    - 定时刷新热点数据
    - 手动预热特定数据
    
    Example:
        >>> warmer = CacheWarmer(cache_manager, db_manager)
        >>> await warmer.start_background_warmup()
        >>> # 或手动触发
        >>> await warmer.warmup_top_agents(10)
    """
    
    def __init__(
        self,
        cache_manager,
        db_manager,
        warmup_delay: int = 30
    ):
        """
        初始化预热器
        
        Args:
            cache_manager: 缓存管理器实例
            db_manager: 数据库管理器实例
            warmup_delay: 预热延迟（秒），启动后多久开始预热
        """
        self.cache_manager = cache_manager
        self.db_manager = db_manager
        self.warmup_delay = warmup_delay
        self._task: Optional[asyncio.Task] = None
        
        # 预热状态
        self._is_warming = False
        self._last_warmup_time: Optional[float] = None
        self._warmup_count = 0
    
    async def start_background_warmup(self) -> None:
        """启动后台预热任务"""
        if self._task and not self._task.done():
            logger.warning("预热任务已在运行中")
            return
        
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
        if self._is_warming:
            logger.warning("预热正在进行中，跳过")
            return 0
        
        self._is_warming = True
        logger.info(f"开始预热 Top {top_n} Agent 配置")
        
        try:
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
                        from src.cache import CacheKeyBuilder, CacheTTL
                        
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
            
            import time
            self._last_warmup_time = time.time()
            self._warmup_count += warmed_count
            
            logger.info(f"预热完成: {warmed_count}/{len(top_agents)}")
            
            # 更新预热指标
            self._record_warmup_progress(
                cache_type="agent_config",
                warmed=warmed_count,
                total=len(top_agents)
            )
            
            return warmed_count
            
        except Exception as e:
            logger.error(f"预热过程异常: {e}")
            return 0
        finally:
            self._is_warming = False
    
    async def _get_top_agents(self, top_n: int) -> List[str]:
        """
        获取高频 Agent 列表
        
        Args:
            top_n: 数量
            
        Returns:
            Agent ID 列表
        """
        try:
            # 方案1：从数据库统计高频访问的 Agent
            # 临时实现：返回最近更新的 Agent
            sql = """
            SELECT agent_id 
            FROM t_sys_agents_configs 
            ORDER BY update_time DESC 
            LIMIT %s
            """
            
            results = await self.db_manager.fetch_all(sql, top_n)
            return [row["agent_id"] for row in results] if results else []
            
        except Exception as e:
            logger.error(f"获取高频 Agent 列表失败: {e}")
            # 降级：从当前缓存获取
            if hasattr(self.cache_manager, 'get_all_agent_ids'):
                agent_ids = self.cache_manager.get_all_agent_ids()
                return agent_ids[:top_n]
            return []
    
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
                    from src.cache import CacheKeyBuilder, CacheTTL
                    
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
        
        logger.info(f"手动预热完成: {warmed_count}/{len(agent_ids)}")
        return warmed_count
    
    async def warmup_all_configs(self) -> int:
        """
        预热所有配置
        
        Returns:
            实际预热数量
        """
        logger.info("开始预热所有配置")
        
        try:
            # 从数据库获取所有配置
            configs = await self.db_manager.get_all_agent_configs()
            
            if not configs:
                logger.warning("未找到任何配置")
                return 0
            
            warmed_count = 0
            for config in configs:
                try:
                    from src.cache import CacheKeyBuilder, CacheTTL
                    
                    cache_key = CacheKeyBuilder.agent_config(config.agent_id)
                    await self.cache_manager.set(
                        cache_key,
                        config,
                        ttl=CacheTTL.AGENT_CONFIG,
                        cache_type="agent_config"
                    )
                    warmed_count += 1
                except Exception as e:
                    logger.error(f"预热配置 {config.agent_id} 失败: {e}")
            
            logger.info(f"所有配置预热完成: {warmed_count}/{len(configs)}")
            return warmed_count
            
        except Exception as e:
            logger.error(f"预热所有配置失败: {e}")
            return 0
    
    def _record_warmup_progress(
        self,
        cache_type: str,
        warmed: int,
        total: int
    ) -> None:
        """
        记录预热进度到监控指标
        
        Args:
            cache_type: 缓存类型
            warmed: 已预热数量
            total: 总数
        """
        try:
            from src.cache.metrics import CacheMetrics
            CacheMetrics.record_warmup_progress(cache_type, warmed, total)
        except ImportError:
            pass
    
    def cancel_warmup(self) -> None:
        """取消预热任务"""
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("预热任务已取消")
    
    def get_stats(self) -> dict:
        """
        获取预热统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "is_warming": self._is_warming,
            "last_warmup_time": self._last_warmup_time,
            "warmup_count": self._warmup_count,
            "warmup_delay": self.warmup_delay,
        }


class CacheWarmupScheduler:
    """
    缓存预热调度器
    支持定时预热
    """
    
    def __init__(self, warmer: CacheWarmer):
        """
        初始化调度器
        
        Args:
            warmer: 预热器实例
        """
        self.warmer = warmer
        self._scheduled_tasks: dict = {}
    
    async def schedule_warmup(
        self,
        name: str,
        interval_seconds: int,
        warmup_func,
        *args,
        **kwargs
    ) -> None:
        """
        调度定时预热任务
        
        Args:
            name: 任务名称
            interval_seconds: 间隔时间（秒）
            warmup_func: 预热函数
            *args: 函数参数
            **kwargs: 函数关键字参数
        """
        async def _run_periodically():
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    await warmup_func(*args, **kwargs)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"定时预热任务 {name} 执行失败: {e}")
        
        self._scheduled_tasks[name] = asyncio.create_task(_run_periodically())
        logger.info(f"定时预热任务 {name} 已启动，间隔: {interval_seconds}s")
    
    def cancel_schedule(self, name: str) -> bool:
        """
        取消定时任务
        
        Args:
            name: 任务名称
            
        Returns:
            是否取消成功
        """
        if name in self._scheduled_tasks:
            self._scheduled_tasks[name].cancel()
            del self._scheduled_tasks[name]
            logger.info(f"定时预热任务 {name} 已取消")
            return True
        return False
    
    def cancel_all(self) -> None:
        """取消所有定时任务"""
        for name in list(self._scheduled_tasks.keys()):
            self.cancel_schedule(name)
        logger.info("所有定时预热任务已取消")
