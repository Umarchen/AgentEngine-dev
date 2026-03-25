"""
缓存管理 API 路由
新增缓存相关的管理接口

对应需求：
- [REQ_REDIS_CACHE_007] 缓存健康检查增强
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from loguru import logger

# 缓存管理路由
cache_router = APIRouter(prefix="/cache", tags=["cache"])


# ==================== 健康检查接口 ====================

@cache_router.get(
    "/health",
    summary="缓存健康检查",
    description="返回缓存的详细健康状态信息"
)
async def get_cache_health() -> Dict[str, Any]:
    """
    缓存健康检查
    
    返回：
    - 连接状态
    - 熔断器状态
    - 键数量
    - 内存使用
    - 降级次数
    """
    try:
        from src.cache import get_cache_manager
        
        cache_manager = get_cache_manager()
        if not cache_manager:
            return {
                "status": "unavailable",
                "message": "缓存管理器未初始化"
            }
        
        health = await cache_manager.health_check()
        stats = await cache_manager.get_stats()
        
        return {
            "status": health.get("status", "unknown"),
            "connected": health.get("connected", False),
            "circuit_breaker_state": health.get("circuit_breaker_state", "unknown"),
            "keys_count": stats.get("keys_count", 0),
            "memory_used_mb": round(stats.get("memory_used_mb", 0), 2),
            "degradation_count": stats.get("degradation_count", 0),
            "fallback_count": stats.get("fallback_count", 0),
        }
        
    except Exception as e:
        logger.error(f"缓存健康检查失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@cache_router.get(
    "/stats",
    summary="缓存统计信息",
    description="返回详细的缓存统计信息"
)
async def get_cache_stats() -> Dict[str, Any]:
    """
    缓存统计信息
    
    返回：
    - 命中率
    - 键分布
    - 内存使用
    - 本地缓存统计
    - 熔断器统计
    """
    try:
        from src.cache import get_cache_manager
        
        cache_manager = get_cache_manager()
        if not cache_manager:
            return {
                "status": "unavailable",
                "message": "缓存管理器未初始化"
            }
        
        stats = await cache_manager.get_stats()
        
        # 计算命中率
        total = stats.get("hits", 0) + stats.get("misses", 0)
        hit_rate = (stats.get("hits", 0) / total) if total > 0 else 0
        
        return {
            "status": "success",
            "hit_rate": round(hit_rate, 4),
            "connected": stats.get("connected", False),
            "keys_count": stats.get("keys_count", 0),
            "memory_used_mb": round(stats.get("memory_used_mb", 0), 2),
            "degradation_count": stats.get("degradation_count", 0),
            "fallback_count": stats.get("fallback_count", 0),
            "local_cache": stats.get("local_cache", {}),
            "circuit_breaker": stats.get("circuit_breaker", {}),
        }
        
    except Exception as e:
        logger.error(f"获取缓存统计失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


# ==================== 缓存管理接口 ====================

@cache_router.post(
    "/clear",
    summary="清除所有缓存",
    description="清除所有实例的 Redis 缓存和本地缓存"
)
async def clear_all_cache() -> Dict[str, Any]:
    """
    清除所有缓存
    
    需要管理员权限（TODO: 添加权限验证）
    """
    try:
        from src.cache import get_cache_manager
        
        cache_manager = get_cache_manager()
        if not cache_manager:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="缓存管理器未初始化"
            )
        
        # 删除所有 agent:config:* 键
        deleted = await cache_manager.delete_pattern("agent:config:*")
        
        logger.info(f"清除缓存完成，删除 {deleted} 个键")
        
        return {
            "success": True,
            "deleted_keys": deleted,
            "message": f"已清除 {deleted} 个缓存键"
        }
        
    except Exception as e:
        logger.error(f"清除缓存失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"清除缓存失败: {e}"
        )


@cache_router.post(
    "/clear/{agent_id}",
    summary="清除指定 Agent 缓存",
    description="清除指定 Agent 的缓存"
)
async def clear_agent_cache(agent_id: str) -> Dict[str, Any]:
    """
    清除指定 Agent 缓存
    """
    try:
        from src.cache import get_cache_manager, CacheKeyBuilder
        
        cache_manager = get_cache_manager()
        if not cache_manager:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="缓存管理器未初始化"
            )
        
        cache_key = CacheKeyBuilder.agent_config(agent_id)
        deleted = await cache_manager.delete(cache_key, broadcast=True)
        
        return {
            "success": deleted,
            "agent_id": agent_id,
            "message": f"已清除 Agent {agent_id} 的缓存"
        }
        
    except Exception as e:
        logger.error(f"清除缓存失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"清除缓存失败: {e}"
        )


# ==================== 熔断器管理接口 ====================

@cache_router.get(
    "/circuit-breaker",
    summary="获取熔断器状态",
    description="返回熔断器的详细状态信息"
)
async def get_circuit_breaker_status() -> Dict[str, Any]:
    """
    获取熔断器状态
    """
    try:
        from src.cache import get_cache_manager
        
        cache_manager = get_cache_manager()
        if not cache_manager:
            return {
                "status": "unavailable",
                "message": "缓存管理器未初始化"
            }
        
        # 如果是增强版管理器
        if hasattr(cache_manager, 'circuit_breaker'):
            cb = cache_manager.circuit_breaker
            return {
                "status": "success",
                "circuit_breaker": cb.get_stats()
            }
        
        return {
            "status": "unavailable",
            "message": "熔断器未启用"
        }
        
    except Exception as e:
        logger.error(f"获取熔断器状态失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@cache_router.post(
    "/circuit-breaker/open",
    summary="手动打开熔断器",
    description="手动打开熔断器，所有 Redis 操作将直接降级"
)
async def force_open_circuit_breaker() -> Dict[str, Any]:
    """
    手动打开熔断器
    
    需要管理员权限（TODO: 添加权限验证）
    """
    try:
        from src.cache import get_cache_manager
        
        cache_manager = get_cache_manager()
        if not cache_manager:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="缓存管理器未初始化"
            )
        
        if hasattr(cache_manager, 'circuit_breaker'):
            cache_manager.circuit_breaker.force_open()
            logger.warning("熔断器已手动打开")
            
            return {
                "success": True,
                "state": "open",
                "message": "熔断器已手动打开"
            }
        
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="熔断器未启用"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"打开熔断器失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"打开熔断器失败: {e}"
        )


@cache_router.post(
    "/circuit-breaker/close",
    summary="手动关闭熔断器",
    description="手动关闭熔断器，恢复正常 Redis 操作"
)
async def force_close_circuit_breaker() -> Dict[str, Any]:
    """
    手动关闭熔断器
    
    需要管理员权限（TODO: 添加权限验证）
    """
    try:
        from src.cache import get_cache_manager
        
        cache_manager = get_cache_manager()
        if not cache_manager:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="缓存管理器未初始化"
            )
        
        if hasattr(cache_manager, 'circuit_breaker'):
            cache_manager.circuit_breaker.force_close()
            logger.info("熔断器已手动关闭")
            
            return {
                "success": True,
                "state": "closed",
                "message": "熔断器已手动关闭"
            }
        
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="熔断器未启用"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"关闭熔断器失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"关闭熔断器失败: {e}"
        )


# ==================== 预热接口 ====================

@cache_router.post(
    "/warmup",
    summary="手动触发预热",
    description="手动触发缓存预热"
)
async def trigger_cache_warmup(
    top_n: int = 10,
    agent_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    手动触发缓存预热
    
    Args:
        top_n: 预热 Top N 高频 Agent（如果未指定 agent_ids）
        agent_ids: 指定预热的 Agent ID 列表
    """
    try:
        from src.cache import get_cache_manager
        from src.database.database import get_database_manager
        from src.cache.warmer import CacheWarmer
        
        cache_manager = get_cache_manager()
        if not cache_manager:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="缓存管理器未初始化"
            )
        
        db_manager = get_database_manager()
        warmer = CacheWarmer(cache_manager, db_manager)
        
        if agent_ids:
            # 预热指定的 Agent
            warmed = await warmer.manual_warmup(agent_ids)
            return {
                "success": True,
                "warmed": warmed,
                "total": len(agent_ids),
                "message": f"已预热 {warmed}/{len(agent_ids)} 个配置"
            }
        else:
            # 预热 Top N
            warmed = await warmer.warmup_top_agents(top_n)
            return {
                "success": True,
                "warmed": warmed,
                "total": top_n,
                "message": f"已预热 Top {top_n} 中的 {warmed} 个配置"
            }
        
    except Exception as e:
        logger.error(f"缓存预热失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"缓存预热失败: {e}"
        )


# ==================== 失效广播接口 ====================

@cache_router.get(
    "/invalidator/stats",
    summary="获取失效广播统计",
    description="返回缓存失效广播的统计信息"
)
async def get_invalidator_stats() -> Dict[str, Any]:
    """
    获取失效广播统计
    """
    try:
        from src.cache import get_cache_manager
        
        cache_manager = get_cache_manager()
        if not cache_manager or not hasattr(cache_manager, 'invalidator'):
            return {
                "status": "unavailable",
                "message": "失效广播器未启用"
            }
        
        invalidator = cache_manager.invalidator
        if invalidator:
            return {
                "status": "success",
                "stats": invalidator.get_stats()
            }
        
        return {
            "status": "unavailable",
            "message": "失效广播器未初始化"
        }
        
    except Exception as e:
        logger.error(f"获取失效广播统计失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
