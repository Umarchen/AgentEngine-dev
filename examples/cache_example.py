"""
Redis 缓存使用示例
演示如何使用缓存模块的各种功能
"""

import asyncio
from pydantic import BaseModel
from loguru import logger

from src.cache import (
    RedisClient,
    RedisConfig,
    CacheManager,
    CacheKeyBuilder,
    CacheTTL,
    CacheSerializer,
    CacheMetrics,
)


# 定义示例模型
class AgentConfig(BaseModel):
    """Agent 配置模型"""
    agent_id: str
    name: str
    description: str
    timeout: int = 300


# 示例 1: 基础缓存操作
async def basic_cache_operations():
    """演示基础缓存操作"""
    logger.info("=== 示例 1: 基础缓存操作 ===")
    
    # 1. 创建 Redis 客户端
    config = RedisConfig(
        host="127.0.0.1",
        port=6379,
        db=0,
    )
    redis_client = RedisClient(config)
    
    # 2. 连接 Redis
    connected = await redis_client.connect()
    if not connected:
        logger.error("Redis 连接失败")
        return
    
    logger.info("Redis 连接成功")
    
    # 3. 创建缓存管理器
    cache_manager = CacheManager(redis_client)
    
    # 4. 设置缓存
    config_data = {
        "agent_id": "agent_001",
        "name": "Echo Agent",
        "description": "简单的回显 Agent",
        "timeout": 300,
    }
    
    await cache_manager.set(
        key=CacheKeyBuilder.agent_config("agent_001"),
        value=config_data,
        ttl=CacheTTL.AGENT_CONFIG,
        cache_type="agent_config"
    )
    logger.info(f"已设置缓存: {CacheKeyBuilder.agent_config('agent_001')}")
    
    # 5. 获取缓存
    cached = await cache_manager.get(
        key=CacheKeyBuilder.agent_config("agent_001"),
        cache_type="agent_config"
    )
    logger.info(f"从缓存获取: {cached}")
    
    # 6. 删除缓存
    await cache_manager.delete(
        key=CacheKeyBuilder.agent_config("agent_001"),
        cache_type="agent_config"
    )
    logger.info("已删除缓存")
    
    # 7. 断开连接
    await redis_client.disconnect()
    logger.info("Redis 连接已断开")


# 示例 2: Pydantic 模型缓存
async def pydantic_model_cache():
    """演示 Pydantic 模型缓存"""
    logger.info("\n=== 示例 2: Pydantic 模型缓存 ===")
    
    # 创建缓存管理器
    config = RedisConfig()
    redis_client = RedisClient(config)
    await redis_client.connect()
    cache_manager = CacheManager(redis_client)
    
    # 创建 Pydantic 模型
    agent_config = AgentConfig(
        agent_id="agent_002",
        name="Risk Assessment Agent",
        description="风险评估 Agent",
        timeout=600,
    )
    
    # 序列化并存储
    await cache_manager.set(
        key=CacheKeyBuilder.agent_config("agent_002"),
        value=agent_config,
        ttl=CacheTTL.AGENT_CONFIG,
        cache_type="agent_config"
    )
    logger.info(f"已存储 Pydantic 模型: {agent_config.agent_id}")
    
    # 获取并反序列化为模型
    cached_config = await cache_manager.get(
        key=CacheKeyBuilder.agent_config("agent_002"),
        model_class=AgentConfig,
        cache_type="agent_config"
    )
    
    if cached_config:
        logger.info(f"从缓存获取模型: {cached_config.agent_id}, 类型: {type(cached_config)}")
        assert isinstance(cached_config, AgentConfig)
    
    # 清理
    await cache_manager.delete(CacheKeyBuilder.agent_config("agent_002"))
    await redis_client.disconnect()


# 示例 3: Read-Through 模式（带降级）
async def read_through_pattern():
    """演示 Read-Through 模式"""
    logger.info("\n=== 示例 3: Read-Through 模式 ===")
    
    # 创建缓存管理器
    config = RedisConfig()
    redis_client = RedisClient(config)
    await redis_client.connect()
    cache_manager = CacheManager(redis_client)
    
    # 模拟数据库加载函数
    async def load_from_database():
        """从数据库加载配置"""
        logger.info("从数据库加载配置...")
        await asyncio.sleep(0.1)  # 模拟数据库延迟
        return {
            "agent_id": "agent_003",
            "name": "Database Agent",
            "description": "从数据库加载的 Agent",
            "timeout": 300,
        }
    
    # 第一次调用：缓存未命中，从数据库加载
    logger.info("第一次调用（缓存未命中）:")
    result1 = await cache_manager.get_with_fallback(
        key=CacheKeyBuilder.agent_config("agent_003"),
        loader=load_from_database,
        ttl=CacheTTL.AGENT_CONFIG,
        cache_type="agent_config"
    )
    logger.info(f"结果: {result1}")
    
    # 第二次调用：缓存命中
    logger.info("\n第二次调用（缓存命中）:")
    result2 = await cache_manager.get_with_fallback(
        key=CacheKeyBuilder.agent_config("agent_003"),
        loader=load_from_database,
        ttl=CacheTTL.AGENT_CONFIG,
        cache_type="agent_config"
    )
    logger.info(f"结果: {result2}")
    
    # 清理
    await cache_manager.delete(CacheKeyBuilder.agent_config("agent_003"))
    await redis_client.disconnect()


# 示例 4: 监控指标
async def metrics_example():
    """演示监控指标采集"""
    logger.info("\n=== 示例 4: 监控指标 ===")
    
    # 手动记录指标
    CacheMetrics.record_hit("agent_config")
    CacheMetrics.record_hit("agent_config")
    CacheMetrics.record_miss("agent_config")
    
    CacheMetrics.record_latency("get", "agent_config", 0.005)
    CacheMetrics.record_latency("set", "agent_config", 0.003)
    
    logger.info("已记录监控指标")
    logger.info("访问 /metrics 端点查看 Prometheus 指标")


# 示例 5: 批量操作
async def batch_operations():
    """演示批量操作"""
    logger.info("\n=== 示例 5: 批量操作 ===")
    
    # 创建缓存管理器
    config = RedisConfig()
    redis_client = RedisClient(config)
    await redis_client.connect()
    cache_manager = CacheManager(redis_client)
    
    # 批量设置缓存
    configs = [
        {"agent_id": f"agent_{i:03d}", "name": f"Agent {i}"} 
        for i in range(1, 6)
    ]
    
    for cfg in configs:
        await cache_manager.set(
            key=CacheKeyBuilder.agent_config(cfg["agent_id"]),
            value=cfg,
            ttl=CacheTTL.AGENT_CONFIG,
            cache_type="agent_config"
        )
    
    logger.info(f"已批量设置 {len(configs)} 个缓存")
    
    # 批量删除（按模式）
    deleted_count = await cache_manager.delete_pattern(
        pattern="agent:config:agent_*",
        cache_type="agent_config"
    )
    logger.info(f"已批量删除 {deleted_count} 个缓存")
    
    await redis_client.disconnect()


# 示例 6: 健康检查和统计
async def health_and_stats():
    """演示健康检查和统计"""
    logger.info("\n=== 示例 6: 健康检查和统计 ===")
    
    # 创建缓存管理器
    config = RedisConfig()
    redis_client = RedisClient(config)
    await redis_client.connect()
    cache_manager = CacheManager(redis_client)
    
    # 健康检查
    health = await cache_manager.health_check()
    logger.info(f"健康状态: {health}")
    
    # 获取统计信息
    stats = await cache_manager.get_stats()
    logger.info(f"统计信息: {stats}")
    
    # Redis 信息
    info = await redis_client.get_info()
    logger.info(f"Redis 版本: {info.get('redis_version', 'unknown')}")
    
    # 内存使用
    memory = await redis_client.get_memory_usage()
    logger.info(f"内存使用: {memory}")
    
    await redis_client.disconnect()


# 主函数
async def main():
    """运行所有示例"""
    try:
        await basic_cache_operations()
        await pydantic_model_cache()
        await read_through_pattern()
        await metrics_example()
        await batch_operations()
        await health_and_stats()
        
        logger.info("\n✅ 所有示例运行完成")
        
    except Exception as e:
        logger.error(f"示例运行失败: {e}")
        raise


if __name__ == "__main__":
    # 运行示例
    asyncio.run(main())
