"""
Agent 配置信息管理模块
负责管理 Agent 配置信息的缓存和获取
集成 Redis 缓存支持
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


class AgentConfigManager:
    """
    Agent 配置信息管理器
    负责：
    1. 从数据库加载配置
    2. 提供配置的快速查询（优先从 Redis 缓存）
    3. 配置的增删改查
    4. 缓存一致性保证
    """
    
    _instance: Optional["AgentConfigManager"] = None
    
    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        cache_manager: Optional[CacheManager] = None
    ):
        """
        初始化配置管理器
        
        Args:
            db_manager: 数据库管理器实例
            cache_manager: 缓存管理器实例（可选）
        """
        self._db_manager = db_manager or get_database_manager()
        self._cache_manager = cache_manager or get_cache_manager()
        self._config_cache: Dict[str, AgentConfig] = {}  # 本地缓存（可选）
        self._initialized = False
        self._lock = asyncio.Lock()
        
        # 是否启用 Redis 缓存
        self._use_redis_cache = self._cache_manager is not None
        
    @classmethod
    def get_instance(
        cls,
        db_manager: Optional[DatabaseManager] = None,
        cache_manager: Optional[CacheManager] = None
    ) -> "AgentConfigManager":
        """获取配置管理器单例"""
        if cls._instance is None:
            cls._instance = cls(db_manager, cache_manager)
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._instance = None
    
    async def initialize(self) -> bool:
        """
        初始化配置管理器
        从数据库加载所有 Agent 配置到本地缓存
        
        Returns:
            是否初始化成功
        """
        async with self._lock:
            if self._initialized:
                logger.debug("配置管理器已初始化，跳过")
                return True
            
            try:
                logger.info("正在从数据库加载 Agent 配置...")
                
                # 确保数据库已连接
                if not self._db_manager.is_connected:
                    await self._db_manager.connect()
                
                # 从数据库获取所有配置
                configs = await self._db_manager.get_all_agent_configs()
                
                # 加载到缓存
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
            Agent 配置，如果不存在则返回 None
        """
        # 1. 尝试从 Redis 缓存获取（如果启用）
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
                # 同步到本地缓存（可选）
                self._config_cache[agent_id] = config
                return config
        
        # 2. Redis 未启用或缓存未命中，从本地缓存获取
        if agent_id in self._config_cache:
            logger.debug(f"从本地缓存获取配置: {agent_id}")
            return self._config_cache[agent_id]
        
        # 3. 本地缓存也未命中，从数据库获取
        logger.debug(f"缓存未命中，从数据库获取配置: {agent_id}")
        config = await self._db_manager.get_agent_config(agent_id)
        
        if config:
            # 更新本地缓存
            self._config_cache[agent_id] = config
            logger.debug(f"配置已加载到缓存: {agent_id}")
        else:
            logger.warning(f"配置不存在: {agent_id}")
        
        return config
    
    def get_config_sync(self, agent_id: str) -> Optional[AgentConfig]:
        """
        同步获取 Agent 配置（仅从缓存）
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            Agent 配置，如果不在缓存中则返回 None
        """
        return self._config_cache.get(agent_id)
    
    async def get_all_configs(self) -> List[AgentConfig]:
        """
        获取所有 Agent 配置
        
        Returns:
            所有 Agent 配置列表
        """
        return list(self._config_cache.values())
    
    def get_all_agent_ids(self) -> List[str]:
        """
        获取所有已缓存的 agent_id
        
        Returns:
            agent_id 列表
        """
        return list(self._config_cache.keys())
    
    # ==================== 配置管理 ====================
    
    async def add_config(self, config: AgentConfig) -> bool:
        """
        添加或更新 Agent 配置
        
        Args:
            config: Agent 配置信息
            
        Returns:
            是否成功
        """
        try:
            # 1. 保存到数据库
            success = await self._db_manager.save_agent_config(config)
            
            if success:
                # 2. 更新本地缓存
                self._config_cache[config.agent_id] = config
                logger.info(f"配置已添加/更新: {config.agent_id}")
                
                # 3. 失效 Redis 缓存（保证一致性）
                if self._use_redis_cache:
                    cache_key = CacheKeyBuilder.agent_config(config.agent_id)
                    await self._cache_manager.delete(cache_key, cache_type="agent_config")
                    logger.debug(f"已失效 Redis 缓存: {config.agent_id}")
            
            return success
        except Exception as e:
            logger.error(f"添加配置失败: {e}")
            return False
    
    async def remove_config(self, agent_id: str) -> bool:
        """
        移除 Agent 配置
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            是否成功
        """
        try:
            # 1. 从本地缓存移除
            if agent_id in self._config_cache:
                del self._config_cache[agent_id]
                logger.info(f"配置已从本地缓存移除: {agent_id}")
            
            # 2. 失效 Redis 缓存
            if self._use_redis_cache:
                cache_key = CacheKeyBuilder.agent_config(agent_id)
                await self._cache_manager.delete(cache_key, cache_type="agent_config")
                logger.debug(f"已失效 Redis 缓存: {agent_id}")
            
            # TODO: 从数据库移除
            return True
        except Exception as e:
            logger.error(f"移除配置失败: {e}")
            return False
    
    async def refresh_config(self, agent_id: str) -> Optional[AgentConfig]:
        """
        刷新指定配置（从数据库重新加载）
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            刷新后的配置
        """
        try:
            # 1. 失效 Redis 缓存
            if self._use_redis_cache:
                cache_key = CacheKeyBuilder.agent_config(agent_id)
                await self._cache_manager.delete(cache_key, cache_type="agent_config")
                logger.debug(f"已失效 Redis 缓存: {agent_id}")
            
            # 2. 从数据库获取最新配置
            config = await self._db_manager.get_agent_config(agent_id)
            
            if config:
                self._config_cache[agent_id] = config
                logger.info(f"配置已刷新: {agent_id}")
            elif agent_id in self._config_cache:
                # 数据库中不存在，从缓存移除
                del self._config_cache[agent_id]
                logger.warning(f"配置在数据库中不存在，已从缓存移除: {agent_id}")
            
            return config
        except Exception as e:
            logger.error(f"刷新配置失败: {e}")
            return None
    
    async def refresh_all(self) -> int:
        """
        刷新所有配置（从数据库重新加载）
        
        Returns:
            刷新的配置数量
        """
        try:
            configs = await self._db_manager.get_all_agent_configs()
            
            # 清空并重建缓存
            self._config_cache.clear()
            for config in configs:
                self._config_cache[config.agent_id] = config
            
            logger.info(f"所有配置已刷新，共 {len(configs)} 个")
            return len(configs)
        except Exception as e:
            logger.error(f"刷新所有配置失败: {e}")
            return 0
    
    # ==================== 工具方法 ====================
    
    def has_config(self, agent_id: str) -> bool:
        """检查配置是否在缓存中"""
        return agent_id in self._config_cache
    
    def get_config_count(self) -> int:
        """获取缓存中的配置数量"""
        return len(self._config_cache)
    
    def clear_cache(self) -> None:
        """清空缓存"""
        self._config_cache.clear()
        self._initialized = False
        logger.info("配置缓存已清空")


# 全局配置管理器实例获取函数
_config_manager: Optional[AgentConfigManager] = None


def get_config_manager() -> AgentConfigManager:
    """获取全局配置管理器实例"""
    # Always obtain the latest class-level singleton. Tests may reset the
    # AgentConfigManager class-level instance directly, so keeping a stale
    # module-level cache can cause different modules to see different
    # instances. Overwrite the module-level variable to stay in sync.
    global _config_manager
    _config_manager = AgentConfigManager.get_instance()
    return _config_manager


async def init_config_manager(
    db_manager: Optional[DatabaseManager] = None,
    cache_manager: Optional[CacheManager] = None
) -> AgentConfigManager:
    """
    初始化配置管理器
    
    Args:
        db_manager: 可选的数据库管理器实例
        cache_manager: 可选的缓存管理器实例
        
    Returns:
        配置管理器实例
    """
    # Use the class-level factory to ensure the class-level singleton is set
    # and the module-level reference stays in sync.
    global _config_manager
    _config_manager = AgentConfigManager.get_instance(db_manager, cache_manager)
    await _config_manager.initialize()
    return _config_manager
