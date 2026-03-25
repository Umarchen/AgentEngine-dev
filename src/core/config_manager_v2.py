"""
增强版配置管理器模块
修复配置删除功能，增强缓存一致性保障

对应需求：
- [REQ_REDIS_CACHE_001] 缓存一致性保障
- [REQ_REDIS_CACHE_008] 配置删除功能修复
"""

import asyncio
from typing import Dict, List, Optional
from loguru import logger

from src.models.schemas import AgentConfig
from src.database.database import DatabaseManager, get_database_manager
from src.cache import (
    CacheManager,
    CacheKeyBuilder,
    CacheTTL,
    get_cache_manager,
)


class AgentConfigManagerV2:
    """
    增强版 Agent 配置管理器
    
    增强：
    1. 完整的配置删除逻辑（DB + Redis + Local）
    2. 缓存失效广播
    3. 事务支持
    4. 缓存预热
    """
    
    _instance: Optional["AgentConfigManagerV2"] = None
    
    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        cache_manager: Optional[CacheManager] = None
    ):
        """
        初始化配置管理器
        
        Args:
            db_manager: 数据库管理器实例
            cache_manager: 缓存管理器实例
        """
        self._db_manager = db_manager or get_database_manager()
        self._cache_manager = cache_manager or get_cache_manager()
        self._config_cache: Dict[str, AgentConfig] = {}  # 本地缓存
        self._initialized = False
        self._lock = asyncio.Lock()
        
        # 是否启用 Redis 缓存
        self._use_redis_cache = self._cache_manager is not None
        
        # 缓存失效器（延迟初始化）
        self._invalidator = None
    
    @classmethod
    def get_instance(
        cls,
        db_manager: Optional[DatabaseManager] = None,
        cache_manager: Optional[CacheManager] = None
    ) -> "AgentConfigManagerV2":
        """获取配置管理器单例"""
        if cls._instance is None:
            cls._instance = cls(db_manager, cache_manager)
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """重置单例"""
        cls._instance = None
    
    async def initialize(self) -> bool:
        """
        初始化配置管理器
        
        Returns:
            是否初始化成功
        """
        async with self._lock:
            if self._initialized:
                logger.debug("配置管理器已初始化，跳过")
                return True
            
            try:
                logger.info("正在从数据库加载 Agent 配置...")
                
                if not self._db_manager.is_connected:
                    await self._db_manager.connect()
                
                configs = await self._db_manager.get_all_agent_configs()
                
                for config in configs:
                    self._config_cache[config.agent_id] = config
                
                self._initialized = True
                logger.info(f"Agent 配置加载完成，共 {len(self._config_cache)} 个配置")
                return True
                
            except Exception as e:
                logger.error(f"初始化配置管理器失败: {e}")
                return False
    
    @property
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._initialized
    
    # ==================== 配置获取 ====================
    
    async def get_config(self, agent_id: str) -> Optional[AgentConfig]:
        """
        获取 Agent 配置
        优先从 Redis 缓存获取，缓存未命中则从数据库获取（Read-Through 策略）
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            Agent 配置，不存在返回 None
        """
        # 1. 尝试从 Redis 缓存获取
        if self._use_redis_cache:
            cache_key = CacheKeyBuilder.agent_config(agent_id)
            
            config = await self._cache_manager.get_with_fallback(
                key=cache_key,
                loader=lambda: self._db_manager.get_agent_config(agent_id),
                ttl=CacheTTL.AGENT_CONFIG,
                model_class=AgentConfig,
                cache_type="agent_config"
            )
            
            if config:
                self._config_cache[agent_id] = config
                return config
        
        # 2. 从本地缓存获取
        if agent_id in self._config_cache:
            logger.debug(f"从本地缓存获取配置: {agent_id}")
            return self._config_cache[agent_id]
        
        # 3. 从数据库获取
        logger.debug(f"缓存未命中，从数据库获取配置: {agent_id}")
        config = await self._db_manager.get_agent_config(agent_id)
        
        if config:
            self._config_cache[agent_id] = config
            logger.debug(f"配置已加载到缓存: {agent_id}")
        else:
            logger.warning(f"配置不存在: {agent_id}")
        
        return config
    
    def get_config_sync(self, agent_id: str) -> Optional[AgentConfig]:
        """同步获取配置（仅从本地缓存）"""
        return self._config_cache.get(agent_id)
    
    async def get_all_configs(self) -> List[AgentConfig]:
        """获取所有配置"""
        return list(self._config_cache.values())
    
    def get_all_agent_ids(self) -> List[str]:
        """获取所有 agent_id"""
        return list(self._config_cache.keys())
    
    # ==================== 配置管理（增强）====================
    
    async def add_config(self, config: AgentConfig) -> bool:
        """
        添加或更新 Agent 配置
        
        流程：
        1. 保存到数据库
        2. 删除 Redis 缓存（确保一致性）
        3. 更新本地缓存
        4. 广播缓存失效消息
        
        Args:
            config: Agent 配置
            
        Returns:
            是否成功
        """
        try:
            # 1. 保存到数据库
            success = await self._db_manager.save_agent_config(config)
            
            if success:
                # 2. 删除 Redis 缓存
                if self._use_redis_cache:
                    cache_key = CacheKeyBuilder.agent_config(config.agent_id)
                    await self._cache_manager.delete(
                        cache_key,
                        cache_type="agent_config",
                        broadcast=True  # 广播失效消息
                    )
                    logger.debug(f"已失效 Redis 缓存: {config.agent_id}")
                
                # 3. 更新本地缓存
                self._config_cache[config.agent_id] = config
                logger.info(f"配置已添加/更新: {config.agent_id}")
            
            return success
        except Exception as e:
            logger.error(f"添加配置失败: {e}")
            return False
    
    async def remove_config(self, agent_id: str) -> bool:
        """
        移除 Agent 配置（增强版，修复 TODO）
        
        流程：
        1. 从数据库删除记录
        2. 删除 Redis 缓存
        3. 删除本地缓存
        4. 广播缓存失效消息
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            是否成功
        """
        try:
            # 1. 从数据库删除（使用事务）
            db_deleted = await self._delete_from_database(agent_id)
            
            if db_deleted:
                # 2. 删除 Redis 缓存
                if self._use_redis_cache:
                    cache_key = CacheKeyBuilder.agent_config(agent_id)
                    await self._cache_manager.delete(
                        cache_key,
                        cache_type="agent_config",
                        broadcast=True
                    )
                    logger.debug(f"已失效 Redis 缓存: {agent_id}")
                
                # 3. 删除本地缓存
                if agent_id in self._config_cache:
                    del self._config_cache[agent_id]
                    logger.info(f"配置已从本地缓存移除: {agent_id}")
                
                # 4. 广播失效消息（如果缓存管理器支持）
                if self._invalidator:
                    await self._invalidator.publish_invalidation(
                        CacheKeyBuilder.agent_config(agent_id)
                    )
                
                logger.info(f"配置已删除: {agent_id}")
                return True
            else:
                logger.warning(f"数据库中未找到配置: {agent_id}")
                return False
                
        except Exception as e:
            logger.error(f"移除配置失败: {e}")
            return False
    
    async def _delete_from_database(self, agent_id: str) -> bool:
        """
        从数据库删除配置记录（支持事务）
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            是否删除成功
        """
        try:
            # 使用数据库事务删除
            async with self._db_manager.get_session() as session:
                # 构造删除 SQL
                from sqlalchemy import text
                
                # 删除相关记录（t_sys_agents_configs）
                sql = text("""
                    DELETE FROM t_sys_agents_configs 
                    WHERE agent_id = :agent_id
                """)
                
                result = await session.execute(sql, {"agent_id": agent_id})
                
                if result.rowcount > 0:
                    logger.debug(f"从数据库删除配置: {agent_id}, 行数: {result.rowcount}")
                    return True
                else:
                    return False
                    
        except Exception as e:
            logger.error(f"从数据库删除配置失败: {agent_id}, 错误: {e}")
            return False
    
    async def refresh_config(self, agent_id: str) -> Optional[AgentConfig]:
        """
        刷新指定配置
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            刷新后的配置
        """
        try:
            # 1. 删除缓存
            if self._use_redis_cache:
                cache_key = CacheKeyBuilder.agent_config(agent_id)
                await self._cache_manager.delete(
                    cache_key,
                    cache_type="agent_config",
                    broadcast=True
                )
                logger.debug(f"已失效缓存: {agent_id}")
            
            # 2. 从数据库获取最新配置
            config = await self._db_manager.get_agent_config(agent_id)
            
            if config:
                self._config_cache[agent_id] = config
                logger.info(f"配置已刷新: {agent_id}")
            elif agent_id in self._config_cache:
                del self._config_cache[agent_id]
                logger.warning(f"配置在数据库中不存在，已从缓存移除: {agent_id}")
            
            return config
        except Exception as e:
            logger.error(f"刷新配置失败: {e}")
            return None
    
    async def refresh_all(self) -> int:
        """刷新所有配置"""
        try:
            configs = await self._db_manager.get_all_agent_configs()
            
            self._config_cache.clear()
            for config in configs:
                self._config_cache[config.agent_id] = config
            
            logger.info(f"所有配置已刷新，共 {len(configs)} 个")
            return len(configs)
        except Exception as e:
            logger.error(f"刷新所有配置失败: {e}")
            return 0
    
    # ==================== 缓存预热（新增）====================
    
    async def warmup_configs(self, agent_ids: List[str]) -> int:
        """
        预热指定配置到缓存
        
        Args:
            agent_ids: Agent ID 列表
            
        Returns:
            预热数量
        """
        warmed = 0
        
        for agent_id in agent_ids:
            try:
                config = await self._db_manager.get_agent_config(agent_id)
                if config:
                    if self._use_redis_cache:
                        cache_key = CacheKeyBuilder.agent_config(agent_id)
                        await self._cache_manager.set(
                            cache_key,
                            config,
                            ttl=CacheTTL.AGENT_CONFIG,
                            cache_type="agent_config"
                        )
                    self._config_cache[agent_id] = config
                    warmed += 1
            except Exception as e:
                logger.error(f"预热配置失败: {agent_id}, 错误: {e}")
        
        logger.info(f"配置预热完成: {warmed}/{len(agent_ids)}")
        return warmed
    
    # ==================== 批量操作（新增）====================
    
    async def get_configs_batch(
        self,
        agent_ids: List[str]
    ) -> Dict[str, Optional[AgentConfig]]:
        """
        批量获取配置
        
        Args:
            agent_ids: Agent ID 列表
            
        Returns:
            {agent_id: config} 字典
        """
        result = {}
        
        # 如果缓存管理器支持批量操作
        if self._use_redis_cache and hasattr(self._cache_manager, 'mget'):
            cache_keys = [
                CacheKeyBuilder.agent_config(aid) for aid in agent_ids
            ]
            values = await self._cache_manager.mget(
                cache_keys,
                model_class=AgentConfig,
                cache_type="agent_config"
            )
            
            for agent_id, value in zip(agent_ids, values):
                result[agent_id] = value
                if value:
                    self._config_cache[agent_id] = value
        else:
            # 降级：逐个获取
            for agent_id in agent_ids:
                result[agent_id] = await self.get_config(agent_id)
        
        return result
    
    # ==================== 工具方法 ====================
    
    def has_config(self, agent_id: str) -> bool:
        """检查配置是否在缓存中"""
        return agent_id in self._config_cache
    
    def get_config_count(self) -> int:
        """获取缓存中的配置数量"""
        return len(self._config_cache)
    
    def clear_cache(self) -> None:
        """清空本地缓存"""
        self._config_cache.clear()
        self._initialized = False
        logger.info("配置缓存已清空")


# 全局配置管理器实例
_config_manager_v2: Optional[AgentConfigManagerV2] = None


def get_config_manager_v2() -> AgentConfigManagerV2:
    """获取全局配置管理器实例"""
    global _config_manager_v2
    _config_manager_v2 = AgentConfigManagerV2.get_instance()
    return _config_manager_v2


async def init_config_manager_v2(
    db_manager: Optional[DatabaseManager] = None,
    cache_manager: Optional[CacheManager] = None
) -> AgentConfigManagerV2:
    """初始化配置管理器"""
    global _config_manager_v2
    _config_manager_v2 = AgentConfigManagerV2.get_instance(db_manager, cache_manager)
    await _config_manager_v2.initialize()
    return _config_manager_v2
