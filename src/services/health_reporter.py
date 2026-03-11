"""
Agent 健康状态上报服务
定期查询所有 Agent 的健康状态并上传至数据库
"""

import asyncio
from datetime import datetime
from typing import Optional

from loguru import logger

from src.database.database import DatabaseManager, get_database_manager
from src.core.agent_manager import AgentManager, get_agent_manager


class HealthReporter:
    """
    健康状态上报器
    定期查询所有 Agent 的健康状态并上传至数据库
    """
    
    _instance: Optional["HealthReporter"] = None
    
    def __init__(
        self,
        agent_manager: Optional[AgentManager] = None,
        db_manager: Optional[DatabaseManager] = None,
        report_interval: int = 60  # 默认60秒上报一次
    ):
        """
        初始化健康状态上报器
        
        Args:
            agent_manager: Agent 管理器实例
            db_manager: 数据库管理器实例
            report_interval: 上报间隔（秒）
        """
        self._agent_manager = agent_manager or get_agent_manager()
        self._db_manager = db_manager or get_database_manager()
        self._report_interval = report_interval
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        logger.info(f"健康状态上报器初始化完成，上报间隔: {report_interval}秒")
    
    @classmethod
    def get_instance(
        cls,
        agent_manager: Optional[AgentManager] = None,
        db_manager: Optional[DatabaseManager] = None,
        report_interval: int = 60
    ) -> "HealthReporter":
        """获取健康状态上报器单例"""
        if cls._instance is None:
            cls._instance = cls(agent_manager, db_manager, report_interval)
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._instance = None
    
    @property
    def is_running(self) -> bool:
        """检查上报器是否正在运行"""
        return self._running
    
    async def start(self) -> None:
        """启动健康状态上报服务"""
        if self._running:
            logger.warning("健康状态上报器已在运行")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._report_loop())
        logger.info("健康状态上报服务已启动")
    
    async def stop(self) -> None:
        """停止健康状态上报服务"""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        logger.info("健康状态上报服务已停止")
    
    async def _report_loop(self) -> None:
        """健康状态上报循环"""
        logger.info("健康状态上报循环开始")
        
        while self._running:
            try:
                await self._do_report()
            except Exception as e:
                logger.error(f"健康状态上报失败: {e}")
            
            # 等待下一次上报
            try:
                await asyncio.sleep(self._report_interval)
            except asyncio.CancelledError:
                break
        
        logger.info("健康状态上报循环结束")
    
    async def _do_report(self) -> None:
        """执行一次健康状态上报"""
        try:
            # 获取所有 Agent 的健康状态
            health_statuses = await self._agent_manager.get_all_agents_health()
            
            if not health_statuses:
                logger.debug("当前没有活跃的 Agent，跳过上报")
                return
            
            # 批量保存到数据库
            await self._db_manager.save_agent_status_batch(health_statuses)
            
            # 统计健康状态
            healthy_count = sum(1 for s in health_statuses if s.status == "healthy")
            unhealthy_count = len(health_statuses) - healthy_count
            
            logger.info(
                f"健康状态上报完成: "
                f"总计 {len(health_statuses)} 个 Agent, "
                f"健康 {healthy_count}, "
                f"异常 {unhealthy_count}"
            )
            
        except Exception as e:
            logger.error(f"执行健康状态上报时出错: {e}")
            raise
    
    async def report_now(self) -> None:
        """立即执行一次健康状态上报"""
        await self._do_report()
    
    def set_report_interval(self, interval: int) -> None:
        """
        设置上报间隔
        
        Args:
            interval: 上报间隔（秒）
        """
        if interval < 1:
            raise ValueError("上报间隔必须大于等于1秒")
        
        self._report_interval = interval
        logger.info(f"健康状态上报间隔已更新为: {interval}秒")


# 全局健康状态上报器实例
_health_reporter: Optional[HealthReporter] = None


def get_health_reporter() -> HealthReporter:
    """获取全局健康状态上报器实例"""
    # Always obtain the latest class-level singleton. Tests may reset the
    # HealthReporter class-level instance directly; overwrite the module
    # variable to ensure callers receive the current instance.
    global _health_reporter
    _health_reporter = HealthReporter.get_instance()
    return _health_reporter


async def init_health_reporter(
    agent_manager: Optional[AgentManager] = None,
    db_manager: Optional[DatabaseManager] = None,
    report_interval: int = 60
) -> HealthReporter:
    """
    初始化并启动健康状态上报器
    
    Args:
        agent_manager: 可选的 Agent 管理器实例
        db_manager: 可选的数据库管理器实例
        report_interval: 上报间隔（秒）
        
    Returns:
        健康状态上报器实例
    """
    # Use the class-level factory so the class-level singleton is initialized
    # and the module-level reference stays in sync. Then start the reporter.
    global _health_reporter
    _health_reporter = HealthReporter.get_instance(agent_manager, db_manager, report_interval)
    await _health_reporter.start()
    return _health_reporter


async def stop_health_reporter() -> None:
    """停止健康状态上报器"""
    global _health_reporter
    if _health_reporter:
        await _health_reporter.stop()
        _health_reporter = None
