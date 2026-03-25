"""
Agent 配置信息管理模块（增强版）
负责管理 Agent 配置信息的缓存和获取
集成 Redis 缓存支持、缓存一致性保证
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
    Agent 配置信息管理器（增强版）
    
    负责：
    1. 从数据库加载配置
    2. 提供配置的快速查询（多级缓存：L1 本地 + L2 Redis）
    3. 配置的增删改查
    4. 缓存一致性保证（通过 CacheInvalidator）
    
    对应需求：
    - [REQ_REDIS_CACHE_001] 缓存一致性保障（增强/修复）
    - [REQ_REDIS_CACHE_008] 配置删除功能修复（修复）
    """
    
    _instance: Optional["AgentConfigManager"] = None
    
    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        cache_manager: Optional[CacheManager] = None,
        cache_invalidator: Optional[Any] = None  # CacheInvalidator 实例
    ):
        """
        初始化配置管理器
        
        Args:
            db_manager: 数据库管理器实例
            cache_manager: 缓存管理器实例（可选）
            cache_invalidator: 缓存失效广播器实例（可选）
        """
        self._db_manager = db_manager or get_database_manager()
        self._cache_manager = cache_manager or get_cache_manager()
        self._cache_invalidator = cache_invalidator
        self._config_cache: Dict[str, AgentConfig] = {}  # 本地缓存（L1）
        self._initialized = False
        self._lock = asyncio.Lock()
        
        # 是否启用 Redis 缓存
        self._use_redis_cache = self._cache_manager is not None
        
    @classmethod
    def get_instance(
        cls,
        db_manager: Optional[DatabaseManager] = None,
        cache_manager: Optional[CacheManager] = None,
        cache_invalidator: Optional[Any] = None
    ) -> "AgentConfigManager":
        """获取配置管理器单例"""
        if cls._instance is None:
            cls._instance = cls(db_manager, cache_manager, cache_invalidator)
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
        更新流程：数据库 -> 删除 Redis -> 删除本地缓存 -> 广播失效
        
        Args:
            config: Agent 配置信息
            
        Returns:
            是否成功
        """
        try:
            # 1. 保存到数据库
            success = await self._db_manager.save_agent_config(config)
            
            if success:
                # 2. 删除 Redis 缓存（保证一致性）
                if self._use_redis_cache:
                    cache_key = CacheKeyBuilder.agent_config(config.agent_id)
                    await self._cache_manager.delete(cache_key, cache_type="agent_config")
                    logger.debug(f"已失效 Redis 缓存: {config.agent_id}")
                
                # 3. 更新本地缓存
                self._config_cache[config.agent_id] = config
                logger.info(f"配置已添加/更新: {config.agent_id}")
                
                # 4. 广播缓存失效消息（多实例一致性）
                await self._broadcast_invalidation([config.agent_id])
            
            return success
        except Exception as e:
            logger.error(f"添加配置失败: {e}")
            return False
    
    async def remove_config(self, agent_id: str) -> bool:
        """
        移除 Agent 配置（已修复）
        删除流程：数据库 -> 删除 Redis -> 删除本地缓存 -> 广播失效
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            是否成功
            
        对应需求：[REQ_REDIS_CACHE_008] 配置删除功能修复（修复）
        """
        try:
            # 1. 从数据库删除（已修复）
            db_success = await self._delete_from_database(agent_id)
            
            if not db_success:
                logger.error(f"从数据库删除配置失败: {agent_id}")
                return False
            
            # 2. 从本地缓存移除
            if agent_id in self._config_cache:
                del self._config_cache[agent_id]
                logger.info(f"配置已从本地缓存移除: {agent_id}")
            
            # 3. 失效 Redis 缓存
            if self._use_redis_cache:
                cache_key = CacheKeyBuilder.agent_config(agent_id)
                await self._cache_manager.delete(cache_key, cache_type="agent_config")
                logger.debug(f"已失效 Redis 缓存: {agent_id}")
            
            # 4. 广播缓存失效消息（多实例一致性）
            await self._broadcast_invalidation([agent_id])
            
            logger.info(f"配置已完全移除: {agent_id}")
            return True
            
        except Exception as e:
            logger.error(f"移除配置失败: {e}")
            return False
    
    async def _delete_from_database(self, agent_id: str) -> bool:
        """
        从数据库删除配置（使用事务保证原子性）
        
        Args:
            agent_id: Agent ID
            
        Returns:
            是否删除成功
            
        对应需求：[REQ_REDIS_CACHE_008] 配置删除功能修复（修复）
        """
        try:
            # 使用数据库事务
            async with self._db_manager.transaction():
                # 删除配置记录
                success = await self._db_manager.delete_agent_config(agent_id)
                
                if success:
                    logger.info(f"已从数据库删除配置: {agent_id}")
                    return True
                else:
                    logger.warning(f"配置在数据库中不存在: {agent_id}")
                    return False
        
        except Exception as e:
            logger.error(f"从数据库删除配置失败: {agent_id}, 错误: {e}")
            return False
    
    async def _broadcast_invalidation(self, agent_ids: List[str]):
        """
        广播缓存失效消息
        
        Args:
            agent_ids: 要失效的 Agent ID 列表
            
        对应需求：[REQ_REDIS_CACHE_001] 缓存一致性保障（增强/修复）
        """
        if self._cache_invalidator is None:
            logger.debug("未配置缓存失效广播器，跳过广播")
            return
        
        try:
            # 构建缓存键列表
            cache_keys = [
                CacheKeyBuilder.agent_config(agent_id)
                for agent_id in agent_ids
            ]
            
            # 广播失效消息
            await self._cache_invalidator.invalidate_keys(cache_keys)
            
            logger.info(
                f"已广播缓存失效消息 - agent_ids: {len(agent_ids)}"
            )
        
        except Exception as e:
            logger.error(f"广播缓存失效消息失败: {e}")
    
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
            
            # 3. 广播缓存失效消息
            await self._broadcast_invalidation([agent_id])
            
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
            
            # 广播全部失效
            agent_ids = [config.agent_id for config in configs]
            await self._broadcast_invalidation(agent_ids)
            
            return len(configs)
        except Exception as e:
            logger.error(f"刷新所有配置失败: {e}")
            return 0
    
    # ==================== 批量操作（新增）====================
    
    async def get_configs_batch(
        self,
        agent_ids: List[str]
    ) -> Dict[str, AgentConfig]:
        """
        批量获取配置
        
        Args:
            agent_ids: Agent ID 列表
            
        Returns:
            Agent ID -> AgentConfig 映射
        """
        result = {}
        
        if self._use_redis_cache:
            # 使用批量获取接口
            cache_keys = {
                agent_id: CacheKeyBuilder.agent_config(agent_id)
                for agent_id in agent_ids
            }
            
            cache_values = await self._cache_manager.mget(
                keys=list(cache_keys.values()),
                model_class=AgentConfig,
                cache_type="agent_config"
            )
            
            # 映射回 agent_id
            for agent_id, cache_key in cache_keys.items():
                if cache_key in cache_values:
                    result[agent_id] = cache_values[cache_key]
        
        # 补充未命中的配置
        for agent_id in agent_ids:
            if agent_id not in result:
                config = await self.get_config(agent_id)
                if config:
                    result[agent_id] = config
        
        return result
    
    async def remove_configs_batch(
        self,
        agent_ids: List[str]
    ) -> Dict[str, bool]:
        """
        批量删除配置
        
        Args:
            agent_ids: Agent ID 列表
            
        Returns:
            Agent ID -> 是否成功 映射
        """
        result = {}
        
        for agent_id in agent_ids:
            result[agent_id] = await self.remove_config(agent_id)
        
        return result
    
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
    
    def set_cache_invalidator(self, cache_invalidator: Any):
        """
        设置缓存失效广播器
        
        Args:
            cache_invalidator: CacheInvalidator 实例
        """
        self._cache_invalidator = cache_invalidator
        logger.info("已设置缓存失效广播器")


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
    cache_manager: Optional[CacheManager] = None,
    cache_invalidator: Optional[Any] = None
) -> AgentConfigManager:
    """
    初始化配置管理器
    
    Args:
        db_manager: 可选的数据库管理器实例
        cache_manager: 可选的缓存管理器实例
        cache_invalidator: 可选的缓存失效广播器实例
        
    Returns:
        配置管理器实例
    """
    # Use the class-level factory to ensure the class-level singleton is set
    # and the module-level reference stays in sync.
    global _config_manager
    _config_manager = AgentConfigManager.get_instance(
        db_manager, cache_manager, cache_invalidator
    )
    await _config_manager.initialize()
    return _config_manager
