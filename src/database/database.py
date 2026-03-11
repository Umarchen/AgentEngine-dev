"""
数据库操作模块
负责配置信息读取、Agent状态信息写入、Agent任务轨迹信息写入
"""

import asyncio
import contextlib
from contextlib import asynccontextmanager
import json
import uuid
from typing import Any, Dict, AsyncGenerator, List, Optional
from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from src.database.models import (
    AgentConfigDBModel,
    AgentDBModel,
    AgentHealthStatusDBModel,
    SkillExeInfoDBModel,
    AgentTrajectoryDBModel,
    AgentTrajectoryEvaluationDBModel,
    AgentTaskDBModel,
    SessionDBModel,
    init_db_table
)

from src.models.schemas import AgentConfig, AgentHealthStatus, AgentTask, AgentTrajectory, ContextContent, HealthChecks, SessionInfo, Trajectory
from src.models.evaluation_schemas import TrajectoryEvaluationRecord

class DatabaseManager:
    """
    数据库管理器
    负责所有数据库相关操作，包括：
    1. 配置信息的读取
    2. Agent状态信息的写入
    3. Agent任务轨迹信息的写入
    """
    
    _instance: Optional["DatabaseManager"] = None
    
    def __init__(self, connection_string: str = "sqlite+aiosqlite:///:memory:"):
        """
        初始化数据库管理器
        
        Args:
            connection_string: 数据库连接字符串
        """
        self.connection_string = connection_string
        self._connected = False
        self._engine = None
        self._session_factory = None
        
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._write_task: Optional[asyncio.Task] = None
        # SQLite 不支持 FOR UPDATE 行锁，用应用层锁串行化同 session 的并发写
        self._sqlite_write_lock: asyncio.Lock = asyncio.Lock()
    @classmethod
    def get_instance(cls, connection_string: str = "sqlite+aiosqlite:///:memory:") -> "DatabaseManager":
        """获取数据库管理器单例"""
        if cls._instance is None:
            cls._instance = cls(connection_string)
        return cls._instance
    
    async def connect(self) -> bool:
        """
        建立数据库连接
        
        Returns:
            是否连接成功
        """
        try:
            # 在实际实现中，这里应该建立真正的数据库连接
            # 例如使用 SQLAlchemy 的 async engine
            logger.info(f"正在连接数据库: {self.connection_string}")

            # Ensure sqlite URLs use an async driver (aiosqlite) when needed.
            conn_str = self.connection_string
            if conn_str.startswith("sqlite://") and "aiosqlite" not in conn_str:
                # convert sqlite:///path or sqlite:///:memory: to async form
                conn_str = conn_str.replace("sqlite://", "sqlite+aiosqlite://", 1)

            # 根据 URL 自动调整引擎配置
            engine_args = {"echo": False}

            if "sqlite+aiosqlite:///:memory:" in conn_str:
                # 内存库特有配置：单线程限制解除 + 静态连接池（防止数据丢失）
                engine_args.update({
                    "connect_args": {"check_same_thread": False},
                    "poolclass": StaticPool
                })
            else:
                # 远程库配置：连接池回收时间（防止断连）
                engine_args.update({
                    "pool_recycle": 3600,
                    "pool_pre_ping": True
                })

            self._engine = create_async_engine(conn_str, **engine_args)

            await init_db_table(self._engine)

            self._session_factory = sessionmaker(bind=self._engine, class_=AsyncSession, expire_on_commit=False)
            
            
            self._connected = True
            
            # 启动异步写入任务
            self._write_task = asyncio.create_task(self._process_write_queue())
            
            logger.info("数据库连接成功")
            return True
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            return False
 
    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        上下文管理器：自动处理 session 的开启、提交、回滚和关闭。
        有效防止 'NoneType' 报错和连接泄露。
        """
        async with self._session_factory() as session:
                try:
                    yield session
                    await session.commit() # 可选：在退出时自动 commit
                except Exception:
                    await session.rollback() # 报错时自动回滚
                    raise
                finally:
                    await session.close() # 确保关闭

    async def disconnect(self) -> None:
        """断开数据库连接"""
        try:
            # 停止写入任务
            if self._write_task:
                self._write_task.cancel()
                try:
                    await self._write_task
                except asyncio.CancelledError:
                    pass
            
            # 关闭所有连接并销毁引擎
            if self._engine:
                await self._engine.dispose()
                self._engine = None
                self._session_factory = None
            self._connected = False    
        except Exception as e:
            logger.error(f"断开数据库连接时出错: {e}")
    
    @property
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected
    
    # ==================== 配置信息读取 ====================
    
    async def get_agent_config(self, agent_id: str) -> Optional[AgentConfig]:
        """
        从数据库获取Agent配置信息
        
        Args:
            agent_id: Agent包ID
            
        Returns:
            Agent配置信息，如果不存在则返回None
        """
        try:
            # 新逻辑：先在 t_sys_agent 中查到 agent_config_id，再到 t_sys_agents_configs 获取配置
            logger.debug(f"通过两表关联获取Agent配置: agent_id={agent_id}")

            async with self.get_session() as session:
                # 1) 通过 agent_id 在 t_sys_agent 查找对应的 agent_config_id
                stmt_config_id = select(AgentDBModel.agent_config_id).where(AgentDBModel.agent_id == agent_id)
                config_id = (await session.execute(stmt_config_id)).scalar_one_or_none()

                if not config_id:
                    logger.warning(f"未在 t_sys_agent 找到对应的 agent_config_id: agent_id={agent_id}")
                    return None

                # 2) 使用 agent_config_id 在 t_sys_agents_configs 获取配置详情
                stmt_cfg = select(AgentConfigDBModel).where(AgentConfigDBModel.agent_config_id == config_id)
                db_model = (await session.execute(stmt_cfg)).scalar_one_or_none()
                if db_model:
                    return self.convertDBModel2AgentConfig(db_model)

                logger.warning(f"未在 t_sys_agents_configs 找到配置: agent_config_id={config_id}")
            return None
        except Exception as e:
            logger.error(f"获取Agent配置失败: {e}")
            return None
    
    async def get_all_agent_configs(self) -> List[AgentConfig]:
        """
        获取所有Agent配置信息
        
        Returns:
            所有Agent配置列表
        """
        try:
            # 新逻辑：先在 t_sys_agent 中拿到所有 agent_config_id，再到 t_sys_agents_configs 批量取配置
            logger.debug("通过两表关联获取所有Agent配置")

            async with self.get_session() as session:
                # 1) 获取所有 agent_config_id（来自 t_sys_agent）
                stmt_config_ids = select(AgentDBModel.agent_config_id)
                config_ids = (await session.execute(stmt_config_ids)).scalars().all()

                if not config_ids:
                    logger.info("t_sys_agent 中未找到任何 agent_config_id")
                    return []

                # 去重，避免重复查询
                unique_config_ids = list(dict.fromkeys(config_ids))

                # 2) 使用这些 agent_config_id 在 t_sys_agents_configs 中获取配置详情
                stmt_cfgs = (
                    select(AgentConfigDBModel)
                    .where(AgentConfigDBModel.agent_config_id.in_(unique_config_ids))
                    .order_by(AgentConfigDBModel.create_time.desc())
                )
                db_models = (await session.execute(stmt_cfgs)).scalars().all()

                return [self.convertDBModel2AgentConfig(db_model) for db_model in db_models]

        except Exception as e:
            logger.error(f"获取所有Agent配置失败: {e}")
            return []

    def convertDBModel2AgentConfig(self, db_model):
        return AgentConfig(
            agent_config_id=db_model.agent_config_id,
            agent_id=db_model.agent_id,
            agent_type_id=db_model.agent_type_id,
            agent_type_name=db_model.agent_type_name,
            description=db_model.description or "",
            config_schema=json.loads(db_model.config_schema) if db_model.config_schema else {},
            create_time=db_model.create_time,
            update_time=db_model.update_time if hasattr(db_model, "update_time") else None,
        )
   
    async def save_agent_config(self, agent_config: AgentConfig) -> bool:
        """
        保存Agent配置到数据库
        
        Args:
            agent_config: Agent配置信息
            
        Returns:
            是否保存成功
        """
        try:
            # Ensure we have an active connection/session factory. Some callers
            # create a DatabaseManager without calling connect(); support that
            # by connecting on demand.
            if not self._connected:
                await self.connect()
            # 实际实现中应插入/更新数据库
            # INSERT INTO agent_configs ... ON CONFLICT UPDATE ...
                    # 检查是否已存在具有相同agent_id的记录
            async with self.get_session() as session:
                # 生成或使用现有的 agent_config_id，确保两表使用相同的 id
                cfg_id = agent_config.agent_config_id or str(uuid.uuid4())

                # 1) 先维护 t_sys_agent 中的映射（upsert），使得后续的 get_agent_config 能查到映射
                try:
                    stmt_agent = select(AgentDBModel).where(AgentDBModel.agent_id == agent_config.agent_id)
                    agent_row = (await session.execute(stmt_agent)).scalar_one_or_none()
                    if agent_row:
                        agent_row.agent_config_id = cfg_id
                        agent_row.agent_type_id = agent_config.agent_type_id or agent_row.agent_type_id
                        agent_row.agent_type_name = agent_config.agent_type_name or agent_row.agent_type_name
                        agent_row.update_time = agent_config.update_time or agent_row.update_time
                    else:
                        agent_row = AgentDBModel(
                            agent_id=agent_config.agent_id,
                            agent_type_id=agent_config.agent_type_id,
                            agent_type_name=agent_config.agent_type_name,
                            agent_config_id=cfg_id,
                            create_time=agent_config.create_time,
                        )
                        session.add(agent_row)
                except Exception as e:
                    logger.exception(f"维护 t_sys_agent 映射失败: {e}")

                # 2) 再插入或更新配置表 t_sys_agents_configs，保证 agent_config_id 与 t_sys_agent 中的映射一致
                stmt = select(AgentConfigDBModel).where(AgentConfigDBModel.agent_config_id == cfg_id)
                db_model = (await session.execute(stmt)).scalar_one_or_none()
                if db_model:
                    # 更新现有记录
                    db_model.agent_type_id = agent_config.agent_type_id
                    db_model.agent_type_name = agent_config.agent_type_name
                    db_model.description = agent_config.description
                    db_model.config_schema = json.dumps(agent_config.config_schema, ensure_ascii=False)
                    db_model.update_time = agent_config.update_time or db_model.update_time
                    db_model.agent_id = agent_config.agent_id or db_model.agent_id
                else:
                    # 如果没有按 cfg_id 找到，则尝试按 agent_id 查找（向后兼容）
                    stmt_by_agent = select(AgentConfigDBModel).where(AgentConfigDBModel.agent_id == agent_config.agent_id)
                    db_model = (await session.execute(stmt_by_agent)).scalar_one_or_none()
                    if db_model:
                        # 将其 agent_config_id 与我们生成/指定的 cfg_id 对齐
                        db_model.agent_config_id = cfg_id
                        db_model.agent_type_id = agent_config.agent_type_id
                        db_model.agent_type_name = agent_config.agent_type_name
                        db_model.description = agent_config.description
                        db_model.config_schema = json.dumps(agent_config.config_schema, ensure_ascii=False)
                        db_model.update_time = agent_config.update_time or db_model.update_time
                    else:
                        # 插入新记录
                        db_model = AgentConfigDBModel(
                            agent_config_id=cfg_id,
                            agent_id=agent_config.agent_id,
                            agent_type_id=agent_config.agent_type_id,
                            agent_type_name=agent_config.agent_type_name,
                            description=agent_config.description,
                            config_schema=json.dumps(agent_config.config_schema, ensure_ascii=False),
                            create_time=agent_config.create_time,
                        )
                        session.add(db_model)

                logger.debug(f"保存Agent配置并维护映射成功: {agent_config.agent_id} (config_id={cfg_id})")
                return True
        except Exception as e:
            logger.error(f"保存Agent配置失败: {e}")
            return False

    # ==================== 状态信息写入 ====================
    
    async def save_agent_status(self, status: AgentHealthStatus) -> bool:
        """
        保存Agent健康状态到数据库
        
        Args:
            status: Agent健康状态信息
            
        Returns:
            是否保存成功
        """
        try:
            # 将写入操作加入队列，避免阻塞
            await self._write_queue.put(("status", status))
            logger.debug(f"Agent状态已加入写入队列: {status.agent_id}")
            return True
        except Exception as e:
            logger.error(f"保存Agent状态失败: {e}")
            return False
    
    async def save_agent_status_batch(self, statuses: List[AgentHealthStatus]) -> bool:
        """
        批量保存Agent健康状态到数据库
        
        Args:
            statuses: Agent健康状态列表
            
        Returns:
            是否保存成功
        """
        try:
            for status in statuses:
                await self._write_queue.put(("status", status))
            logger.debug(f"批量Agent状态已加入写入队列: {len(statuses)} 条")
            return True
        except Exception as e:
            logger.error(f"批量保存Agent状态失败: {e}")
            return False
    
    # ==================== 轨迹信息写入 ====================
    
    async def save_agent_trajectory(self, trajectory: AgentTrajectory) -> bool:
        """
        保存Agent运行轨迹到数据库（直接写入）
        
        Args:
            trajectory: Agent运行轨迹信息
            
        Returns:
            是否保存成功
        """
        try:
            await self._upsert_trajectory(trajectory)
            logger.debug(f"Agent轨迹已写入数据库: {trajectory.agent_id}")
            return True
        except Exception as e:
            logger.error(f"保存Agent轨迹失败: {e}")
            return False
    
    # ==================== 轨迹评估信息写入和查询 ====================
    
    async def save_trajectory_evaluation(self, evaluation_record: TrajectoryEvaluationRecord) -> int:
        """
        保存轨迹评估结果到数据库
        
        Args:
            evaluation_record: 轨迹评估记录
            
        Returns:
            评估记录 ID
        """
        try:
            async with self.get_session() as session:
                db_model = AgentTrajectoryEvaluationDBModel(
                    agent_id=evaluation_record.agent_id,
                    user_id=evaluation_record.user_id,
                    session_id=evaluation_record.session_id,
                    trajectory=json.dumps(evaluation_record.trajectory, ensure_ascii=False),
                    evaluation=evaluation_record.evaluation.model_dump_json(),
                    evaluated_at=evaluation_record.evaluated_at,
                    evaluator_model=evaluation_record.evaluator_model,
                    evaluation_prompt_version=evaluation_record.evaluation_prompt_version
                )
                session.add(db_model)
                await session.flush()  # 获取自增ID
                
                evaluation_id = db_model.id
                
                logger.info(f"轨迹评估结果已保存 - ID: {evaluation_id}, agent_id: {evaluation_record.agent_id}")
                return evaluation_id
                
        except Exception as e:
            logger.error(f"保存轨迹评估结果失败: {e}")
            raise
    
    async def get_trajectory_evaluation(
        self,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        evaluation_id: Optional[int] = None
    ) -> Optional[TrajectoryEvaluationRecord]:
        """
        查询轨迹评估结果
        
        Args:
            agent_id: Agent ID（可选）
            user_id: 用户 ID（可选）
            session_id: 会话 ID（可选）
            evaluation_id: 评估记录 ID（可选）
            
        Returns:
            评估记录，如果不存在则返回 None
        """
        try:
            async with self.get_session() as session:
                stmt = select(AgentTrajectoryEvaluationDBModel)
                
                if evaluation_id is not None:
                    stmt = stmt.where(AgentTrajectoryEvaluationDBModel.id == evaluation_id)
                else:
                    if agent_id:
                        stmt = stmt.where(AgentTrajectoryEvaluationDBModel.agent_id == agent_id)
                    if user_id:
                        stmt = stmt.where(AgentTrajectoryEvaluationDBModel.user_id == user_id)
                    if session_id:
                        stmt = stmt.where(AgentTrajectoryEvaluationDBModel.session_id == session_id)
                    
                    # 如果没有指定evaluation_id,返回最新的一条
                    stmt = stmt.order_by(AgentTrajectoryEvaluationDBModel.evaluated_at.desc())
                
                db_model = (await session.execute(stmt)).scalar_one_or_none()
                
                if db_model:
                    from src.models.evaluation_schemas import Evaluation
                    
                    return TrajectoryEvaluationRecord(
                        id=db_model.id,
                        agent_id=db_model.agent_id,
                        user_id=db_model.user_id,
                        session_id=db_model.session_id,
                        trajectory=json.loads(db_model.trajectory),
                        evaluation=Evaluation.model_validate_json(db_model.evaluation),
                        evaluated_at=db_model.evaluated_at,
                        evaluator_model=db_model.evaluator_model,
                        evaluation_prompt_version=db_model.evaluation_prompt_version
                    )
                
                return None
                
        except Exception as e:
            logger.error(f"查询轨迹评估结果失败: {e}")
            return None
    
    async def get_trajectory_evaluations(
        self,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 100
    ) -> List[TrajectoryEvaluationRecord]:
        """
        查询多条轨迹评估结果
        
        Args:
            agent_id: Agent ID（可选）
            user_id: 用户 ID（可选）
            session_id: 会话 ID（可选）
            limit: 返回记录数限制
            
        Returns:
            评估记录列表
        """
        try:
            async with self.get_session() as session:
                stmt = select(AgentTrajectoryEvaluationDBModel)
                
                if agent_id:
                    stmt = stmt.where(AgentTrajectoryEvaluationDBModel.agent_id == agent_id)
                if user_id:
                    stmt = stmt.where(AgentTrajectoryEvaluationDBModel.user_id == user_id)
                if session_id:
                    stmt = stmt.where(AgentTrajectoryEvaluationDBModel.session_id == session_id)
                
                # 按评估时间倒序排列,限制返回数量
                stmt = stmt.order_by(AgentTrajectoryEvaluationDBModel.evaluated_at.desc()).limit(limit)
                
                db_models = (await session.execute(stmt)).scalars().all()
                
                from src.models.evaluation_schemas import Evaluation
                
                return [
                    TrajectoryEvaluationRecord(
                        id=db_model.id,
                        agent_id=db_model.agent_id,
                        user_id=db_model.user_id,
                        session_id=db_model.session_id,
                        trajectory=json.loads(db_model.trajectory),
                        evaluation=Evaluation.model_validate_json(db_model.evaluation),
                        evaluated_at=db_model.evaluated_at,
                        evaluator_model=db_model.evaluator_model,
                        evaluation_prompt_version=db_model.evaluation_prompt_version
                    )
                    for db_model in db_models
                ]
            
        except Exception as e:
            logger.error(f"查询轨迹评估结果失败: {e}")
            return []
    
    # ==================== 内部方法 ====================
    
    async def _process_write_queue(self) -> None:
        """
        处理写入队列
        异步处理所有写入操作，避免阻塞主流程
        """
        logger.info("数据库写入队列处理任务已启动")
        
        while True:
            try:
                # 从队列获取写入任务
                write_type, data = await self._write_queue.get()
                
                if write_type == "status":
                    await self._do_write_status(data)
                elif write_type == "trajectory":
                    await self._do_write_trajectory(data)
                else:
                    logger.warning(f"未知的写入类型: {write_type}")
                
                self._write_queue.task_done()
                
            except asyncio.CancelledError:
                logger.info("数据库写入队列处理任务已停止")
                break
            except Exception as e:
                logger.error(f"处理写入队列时出错: {e}")
    
    async def _do_write_status(self, status: AgentHealthStatus) -> None:
        """
        实际执行状态写入操作
        
        Args:
            status: Agent健康状态信息
        """
        try:
            async with self.get_session() as session:
                db_model = AgentHealthStatusDBModel(
                    agent_id=status.agent_id,
                    agent_type_name=status.agent_type_name,
                    agent_status=status.status,
                    uptime_seconds=status.uptime_seconds,
                    checked_at=status.checked_at,
                    checks=HealthChecks.model_validate(status.checks).model_dump_json() if status.checks else None
                )
                session.add(db_model)
                logger.debug(f"Agent状态写入数据库成功: {status.agent_id}")
        except Exception as e:
            logger.error(f"写入Agent状态到数据库失败: {e}")
    
    async def _do_write_trajectory(self, trajectory: AgentTrajectory) -> None:
        """
        实际执行轨迹写入操作
        
        Args:
            trajectory: Agent运行轨迹信息
        """
        try:
            await self._upsert_trajectory(trajectory)
            logger.debug(f"Agent轨迹写入数据库成功: {trajectory.agent_id}")
        except Exception as e:
            logger.error(f"写入Agent轨迹到数据库失败: {e}")

    async def _upsert_trajectory(self, trajectory: AgentTrajectory) -> None:
        """
        写入或更新轨迹记录（按 agent_id + session_id 合并）
        """
        async with self.get_session() as session:
            stmt = (
                select(AgentTrajectoryDBModel)
                .where(AgentTrajectoryDBModel.agent_id == trajectory.agent_id)
                .where(AgentTrajectoryDBModel.session_id == trajectory.session_id)
                .order_by(AgentTrajectoryDBModel.create_time.desc())
            )
            existing = (await session.execute(stmt)).scalars().first()

            if existing is None:
                db_model = AgentTrajectoryDBModel(
                    agent_id=trajectory.agent_id,
                    user_id=trajectory.user_id,
                    session_id=trajectory.session_id,
                    trajectory=Trajectory.model_validate(trajectory.trajectory).model_dump_json() if trajectory.trajectory else None,
                    create_time=trajectory.create_time,
                    update_time=trajectory.update_time
                )
                session.add(db_model)
                return

            # 追加新的轨迹步骤到已有轨迹中，其它字段保持不变
            existing_trajectory = (
                Trajectory.model_validate_json(existing.trajectory)
                if existing.trajectory
                else Trajectory()
            )
            new_trajectory = (
                Trajectory.model_validate(trajectory.trajectory)
                if trajectory.trajectory
                else None
            )
            if new_trajectory:
                existing_trajectory.steps.extend(new_trajectory.steps)
                existing.trajectory = existing_trajectory.model_dump_json()

            existing.update_time = trajectory.update_time
    
    # ==================== 查询方法（用于调试和测试）====================
    
    async def get_status_history(
        self, 
        agent_id: Optional[str] = None,
        limit: int = 100
    ) -> List[AgentHealthStatus]:
        """
        获取Agent状态历史记录
        
        Args:
            agent_id: 可选的Agent包ID过滤
            limit: 返回记录数限制
            
        Returns:
            状态历史记录列表
        """
        try:
            async with self.get_session() as session:
                # 构建查询
                stmt = select(AgentHealthStatusDBModel)
                
                # 如果提供了agent_id，则添加过滤条件
                if agent_id:
                    stmt = stmt.where(AgentHealthStatusDBModel.agent_id == agent_id)
                # 限制返回的记录数
                stmt.order_by(AgentHealthStatusDBModel.checked_at.desc()).limit(limit)
                db_models = (await session.execute(stmt)).scalars().all()
                
                # 将数据库模型转换为AgentHealthStatus对象
                return [
                    AgentHealthStatus(
                        agent_id=db_model.agent_id,
                        agent_type_name=db_model.agent_type_name,
                        status=db_model.agent_status,
                        uptime_seconds=db_model.uptime_seconds,
                        checked_at=db_model.checked_at,
                        checks=HealthChecks.model_validate_json(db_model.checks)
                    )
                    for db_model in db_models
                ]

        except Exception as e:
            logger.error(f"获取状态历史失败: {e}")
            return []
    
    async def get_trajectory_history(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 100
    ) -> List[AgentTrajectory]:
        """
        获取Agent轨迹历史记录
        
        Args:
            agent_id: 可选的Agent包ID过滤
            session_id: 可选的会话ID过滤
            limit: 返回记录数限制
            
        Returns:
            轨迹历史记录列表
        """
        try:
            async with self.get_session() as session:

                # 构建查询
                stmt = select(AgentTrajectoryDBModel)
                
                # 如果提供了agent_id，则添加过滤条件
                if agent_id:
                    stmt = stmt.where(AgentTrajectoryDBModel.agent_id == agent_id)

                # 如果提供了session_id，则添加过滤条件
                if session_id:
                    stmt = stmt.where(AgentTrajectoryDBModel.session_id == session_id)

                # 限制返回的记录数
                stmt.order_by(AgentTrajectoryDBModel.create_time.desc()).limit(limit)
                db_models = (await session.execute(stmt)).scalars().all()

                
                # 将数据库模型转换为AgentTrajectory对象
                return [
                    AgentTrajectory(
                        agent_id=db_model.agent_id,
                        user_id=db_model.user_id,
                        session_id=db_model.session_id,
                        trajectory=Trajectory.model_validate_json(db_model.trajectory),
                        create_time=db_model.create_time,
                        update_time=db_model.update_time
                    )
                    for db_model in db_models
                ]

        except Exception as e:
            logger.error(f"获取轨迹历史失败: {e}")
            return []

    async def get_task(
        self,
        task_id: str,
    ) -> AgentTask:
        """
        获取Task记录
        
        Args:
            session_id: 会话ID过滤
            
        Returns:
            Task记录
        """
        async with self.get_session() as session:
            stmt = select(AgentTaskDBModel).where(AgentTaskDBModel.task_id == task_id)
            db_model = (await session.execute(stmt)).scalar_one_or_none()
            if db_model:
                return AgentTask(
                    task_id=db_model.task_id,
                    agent_id=db_model.agent_id,
                    user_id=db_model.user_id,
                    session_id=db_model.session_id,
                    task_status=db_model.task_status,
                    token_count=db_model.token_count,
                    create_time=db_model.create_time,
                    context_content=ContextContent.model_validate_json(db_model.context_content),
                    update_time=db_model.update_time,
                )
                
            return None

    async def save_task(
        self,
        agent_id: str,
        session_id: str,
        task_new_context: List[Dict],
        task_id: Optional[str] = None,
        user_id: Optional[str] = None,
        task_status: Optional[str] = None,
        token_count: Optional[int] = None,

    ) -> bool:
        """
        保存Task记录

        不存在相同session_id、agent_id时添加，否则更新
        
        Args:
            agent_id: Agent ID过滤
            session_id: 会话ID过滤
            context_content: 上下文内容
            user_id: 可选的用户ID
            task_status: 可选的任务状态
            token_count: 可选的token数量
        Returns:
            是否保存成功
        """
        try:
            lock = self._sqlite_write_lock if 'sqlite' in self.connection_string else contextlib.nullcontext()
            async with lock:
                async with self.get_session() as session:
                    stmt = select(AgentTaskDBModel).where(
                        AgentTaskDBModel.session_id == session_id,
                        AgentTaskDBModel.agent_id == agent_id
                        )
                    if 'sqlite' not in self.connection_string:
                        stmt = stmt.with_for_update()
                    db_model = (await session.execute(stmt)).scalar_one_or_none()
                    if db_model:
                        # 更新
                        context_content=ContextContent.model_validate_json(db_model.context_content)
                        context_content.context.extend(task_new_context)
                        db_model.context_content = ContextContent.model_validate(context_content).model_dump_json()
                        db_model.task_status = task_status
                        db_model.token_count = token_count
                    else:
                        # 添加
                        context_content=ContextContent(context=task_new_context)
                        db_model = AgentTaskDBModel(
                            task_id = task_id,
                            agent_id=agent_id,
                            session_id=session_id,
                            context_content=ContextContent.model_validate(context_content).model_dump_json(),
                            user_id=user_id,
                            task_status=task_status,
                            token_count=token_count,
                            )
                        session.add(db_model)
                    logger.debug(f"保存Task成功")
                    return True
        except Exception as e:
            logger.error(f"保存Task失败: {e}")
            return False

    async def get_session_info(
        self,
        session_id: str,
    ) -> SessionInfo:
        """
        根据 session_id 获取 Session 记录
        
        Args:
            session_id: 会话ID过滤
            
        Returns:
            SessionDBModel 记录或 None
        """
        async with self.get_session() as session:
            stmt = select(SessionDBModel).where(SessionDBModel.session_id == session_id)
            db_model:SessionDBModel = (await session.execute(stmt)).scalar_one_or_none()
            if db_model:
                return SessionInfo(
                    session_id=db_model.session_id,
                    agent_ids=db_model.agent_ids.split(',') if db_model.agent_ids else [],
                    user_ids=db_model.user_ids.split(',') if db_model.user_ids else [],
                    task_ids=db_model.task_ids.split(',') if db_model.task_ids else [],
                    conversation_history=ContextContent.model_validate_json(db_model.conversation_history),
                    session_ended=db_model.session_ended,
                    create_time=db_model.create_time,
                    update_time=db_model.update_time,
                )
            
            return None

    async def save_session_info(
        self,
        session_id: str,
        agent_id: str,
        user_id: str,
        task_id: str,
        new_messages: List[Dict],
    ) -> bool:
        """
        保存或更新 Session 记录（原子追加模式）

        在事务内重新读取 DB 最新状态，追加 new_messages，原子写回。
        对 PostgreSQL/MySQL 使用 SELECT FOR UPDATE 行锁防止并发覆盖。

        Args:
            session_id: 会话ID
            agent_id: 要添加的Agent ID
            user_id: 要添加的User ID
            task_id: 要添加的Task ID
            new_messages: 本次需要追加的新消息列表

        Returns:
            是否保存成功
        """
        try:
            # SQLite: 用应用层锁串行化；PG/MySQL: 靠 FOR UPDATE 行锁
            lock = self._sqlite_write_lock if 'sqlite' in self.connection_string else contextlib.nullcontext()
            async with lock:
                async with self.get_session() as session:
                    stmt = select(SessionDBModel).where(SessionDBModel.session_id == session_id)
                    if 'sqlite' not in self.connection_string:
                        stmt = stmt.with_for_update()

                    db_model: SessionDBModel = (await session.execute(stmt)).scalar_one_or_none()

                    if db_model:
                        # 读取 DB 中最新的 history，追加新消息
                        current = ContextContent.model_validate_json(db_model.conversation_history)
                        current.context.extend(new_messages)
                        db_model.conversation_history = current.model_dump_json()

                        # 处理agent_ids
                        current_agent_ids = db_model.agent_ids.split(',') if db_model.agent_ids else []
                        if agent_id and agent_id not in current_agent_ids:
                            current_agent_ids.append(agent_id)
                        db_model.agent_ids = ','.join(current_agent_ids) if current_agent_ids else None

                        # 处理user_ids
                        current_user_ids = db_model.user_ids.split(',') if db_model.user_ids else []
                        if user_id and user_id not in current_user_ids:
                            current_user_ids.append(user_id)
                        db_model.user_ids = ','.join(current_user_ids) if current_user_ids else None

                        # 处理task_ids
                        current_task_ids = db_model.task_ids.split(',') if db_model.task_ids else []
                        if task_id and task_id not in current_task_ids:
                            current_task_ids.append(task_id)
                        db_model.task_ids = ','.join(current_task_ids) if current_task_ids else None
                    else:
                        # 创建新记录
                        db_model = SessionDBModel(
                            session_id=session_id,
                            agent_ids=agent_id,
                            user_ids=user_id,
                            task_ids=task_id,
                            conversation_history=ContextContent(context=new_messages).model_dump_json(),
                        )
                        session.add(db_model)

                    return True
        except Exception as e:
            logger.error(f"保存Session失败: {e}")
            return False

# 全局数据库管理器实例获取函数
_db_manager: Optional[DatabaseManager] = None


def get_database_manager() -> DatabaseManager:
    """获取全局数据库管理器实例"""
    # Always return the class-level singleton to avoid divergence between
    # the module-level cache and DatabaseManager._instance (tests may reset
    # the class-level instance directly). This ensures callers always get the
    # current canonical DatabaseManager.
    global _db_manager
    _db_manager = DatabaseManager.get_instance()
    return _db_manager


async def init_database(connection_string: str = "sqlite+aiosqlite:///:memory:") -> DatabaseManager:
    """
    初始化数据库连接
    
    Args:
        connection_string: 数据库连接字符串
        
    Returns:
        数据库管理器实例
    """
    # Use the class-level singleton factory so the class-level instance and
    # module-level reference remain consistent. This prevents divergence
    # between instances created by init flows and those returned by
    # DatabaseManager.get_instance() used elsewhere.
    global _db_manager
    _db_manager = DatabaseManager.get_instance(connection_string)
    await _db_manager.connect()
    return _db_manager


async def close_database() -> None:
    """关闭数据库连接"""
    global _db_manager
    if _db_manager:
        await _db_manager.disconnect()
        _db_manager = None


async def upsert_skill_exe_info(
    skill_name: str,
    executable: bool,
    entry_module: str = "",
    entry_function: str = "",
    input_schema: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    arguments_preview: Optional[str] = None,
    executed: Optional[bool] = None,
    duration_ms: Optional[float] = None,
    result_size: Optional[int] = None,
    error_message: Optional[str] = None,
) -> bool:
    manager = get_database_manager()
    if not manager.is_connected:
        return False

    try:
        async with manager.get_session() as session:
            stmt = select(SkillExeInfoDBModel).where(SkillExeInfoDBModel.skill_name == skill_name)
            db_model = (await session.execute(stmt)).scalar_one_or_none()
            schema_json = json.dumps(input_schema or {"type": "object"}, ensure_ascii=False)

            if db_model:
                db_model.executable = executable
                db_model.entry_module = entry_module
                db_model.entry_function = entry_function
                db_model.input_schema = schema_json
                if trace_id is not None:
                    db_model.trace_id = trace_id
                if arguments_preview is not None:
                    db_model.arguments_preview = arguments_preview
                if executed is not None:
                    db_model.executed = executed
                if duration_ms is not None:
                    db_model.duration_ms = duration_ms
                if result_size is not None:
                    db_model.result_size = result_size
                if error_message is not None:
                    db_model.error_message = error_message
                if any(v is not None for v in [trace_id, arguments_preview, executed, duration_ms, result_size, error_message]):
                    db_model.executed_at = func.now()
            else:
                db_model = SkillExeInfoDBModel(
                    skill_name=skill_name,
                    executable=executable,
                    entry_module=entry_module,
                    entry_function=entry_function,
                    input_schema=schema_json,
                    trace_id=trace_id,
                    arguments_preview=arguments_preview,
                    executed=executed,
                    duration_ms=duration_ms,
                    result_size=result_size,
                    error_message=error_message,
                    executed_at=func.now() if any(v is not None for v in [trace_id, arguments_preview, executed, duration_ms, result_size, error_message]) else None,
                )
                session.add(db_model)

        return True
    except Exception as exc:
        logger.debug(f"写入 t_skill_exe_info 失败(skill={skill_name}): {exc}")
        return False
