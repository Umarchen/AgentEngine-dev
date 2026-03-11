"""
Agent 管理器
负责 Agent 对象的创建、获取、管理和生命周期控制
"""

import asyncio
import time
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional, Type
import json
from pathlib import Path
from dataclasses import dataclass, field
from abc import ABC

from sqlalchemy import select

from loguru import logger

from src.models.schemas import (
    AgentConfig,
    AgentHealthStatus,
    AgentTemplate,
    AgentTrajectory,
    AgentTaskRequest,
    AgentTaskResponse,
    ContextContent,
    StreamChunk,
    StreamEventType,
    Trajectory,
    TrajectoryStep,
)
from src.database.database import DatabaseManager, get_database_manager
from src.database.models import AgentTemplateDBModel, AgentTypeDBModel
from src.core.base import AgentRegistry
from src.core.config_manager import AgentConfigManager, get_config_manager
from src.services.evaluation import TrajectoryEvaluator, get_trajectory_evaluator


@dataclass
class AgentTemplateRaw:
    agent_type_name: str
    model_config: List[Dict[str, Any]] = field(default_factory=list)
    prompt_config: List[Dict[str, Any]] = field(default_factory=list)
    mcp_tool_config: List[Dict[str, Any]] = field(default_factory=list)
    mcp_server_config: List[Dict[str, Any]] = field(default_factory=list)
    agent_template_id: Optional[str] = None
    agent_type_id: Optional[str] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None

    @classmethod
    def from_template(cls, template: AgentTemplate) -> "AgentTemplateRaw":
        return cls(
            agent_type_name=template.agent_type_name,
            model_config=list(template.model_items or []),
            prompt_config=list(template.prompt_config or []),
            mcp_tool_config=list(template.mcp_tool_config or []),
            mcp_server_config=list(template.mcp_server_config or []),
            agent_template_id=template.agent_template_id,
            agent_type_id=template.agent_type_id,
            create_time=template.create_time,
            update_time=template.update_time,
        )

    def ensure_identity(self) -> None:
        if not self.agent_template_id:
            self.agent_template_id = str(uuid.uuid4())
        if not self.agent_type_id:
            self.agent_type_id = str(uuid.uuid4())

    def stamp_now(self) -> None:
        now = datetime.utcnow()
        self.create_time = now
        self.update_time = now

class AgentManager:
    """
    Agent 管理器
    负责：
    1. Agent 对象的创建和获取
    2. Agent 任务的执行
    3. Agent 生命周期管理
    """
    
    _instance: Optional["AgentManager"] = None
    
    def __init__(
        self,
        config_manager: Optional[AgentConfigManager] = None,
        db_manager: Optional[DatabaseManager] = None,
        evaluator: Optional[TrajectoryEvaluator] = None
    ):
        """
        初始化 Agent 管理器
        
        Args:
            config_manager: 配置管理器实例
            db_manager: 数据库管理器实例
            evaluator: 轨迹评估器实例（可选，默认使用全局单例）
        """

        self._config_manager = config_manager or get_config_manager()
        self._db_manager = db_manager or get_database_manager()
        self._evaluator = evaluator or get_trajectory_evaluator()
        # Agent 实例缓存: agent_id -> 任意类型的实例（通常是 BaseAgent 或用户自定义实现）
        # 允许存放任意类对象，运行时会按需调用期望的方法（invoke 等）
        self._agents: Dict[str, Any] = {}
        self._agent_templates_cache: List[AgentTemplateRaw] = []

        # 锁，用于并发安全
        self._lock = asyncio.Lock()

        logger.info("Agent 管理器初始化完成")

    def _build_trajectory(self, messages: Any, session_ended: bool) -> Trajectory:
        """
        根据一组消息构建 Trajectory 对象（与变量名 output 无绑定）。

        参数：
        - messages: 一系列消息（通常为 dict 列表，包含 `role` 与 `content`）
        - session_ended: 会话是否结束（用于设置 is_terminal）

        规则：
        - 若 messages 为 None 或为空，则返回空 Trajectory
        - 若 messages 为列表，则使用列表的前两项构造 step（第一项 content -> state，第二项 content -> action）
        - 若 messages 为单个值（str/dict等），将其当作第一项处理
        - 出现异常时返回空 Trajectory 并记录错误
        """
        try:
            if not messages:
                return Trajectory()

            items = messages if isinstance(messages, list) else [messages]

            step = []

            # 遍历所有 items，获取每个 item 的 "content" 内容
            for item in items:
                step.append(TrajectoryStep(
                    role=item.get("role"),
                    content=item.get("content")
                ))
            return Trajectory(steps=step)
        except Exception as e:
            logger.error(f"构建 Trajectory 失败: {e}", exc_info=True)
            return Trajectory()
    
    def _build_output_result(
        self,
        agent_id: str,
        session_id: str,
        success: bool,
        output: Any,
        error: Optional[str],
        execution_time: float,
    ) -> AgentTaskResponse:
        """
        从 agent 返回的 output（通常为消息字典列表）中提取最后一条记录的内容。

        返回：
        - 如果最后一条存在且为 dict 且含有 "content" 字段，返回该字段值
        - 如果最后一条存在但不是 dict，直接返回该值
        - 否则返回 None
        """
        try:
            # 提取最后一条记录作为最终输出
            if not output:
                final_output = None
            else:
                items = output if isinstance(output, list) else [output]
                if len(items) == 0:
                    final_output = None
                else:
                    last = items[-1]
                    final_output = last["content"] if isinstance(last, dict) and "content" in last else last

            return AgentTaskResponse(
                success=success,
                agent_id=agent_id,
                session_id=session_id,
                output=final_output,
                error=error,
                execution_time=execution_time,
            )
        except Exception as e:
            logger.error(f"提取 output 最后一条记录失败: {e}", exc_info=True)
            return AgentTaskResponse(
                success=False,
                agent_id=agent_id,
                session_id=session_id,
                output=None,
                error=str(e),
                execution_time=execution_time,
            )
    
    @classmethod
    def get_instance(
        cls,
        config_manager: Optional[AgentConfigManager] = None,
        db_manager: Optional[DatabaseManager] = None
    ) -> "AgentManager":
        """获取 Agent 管理器单例"""
        if cls._instance is None:
            cls._instance = cls(config_manager, db_manager)
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._instance = None
    def _get_agent_template_config_paths(self) -> List[Path]:
        agents_dir = Path(__file__).resolve().parent.parent / "agents"
        if not agents_dir.exists():
            logger.error(f"未找到 agents 目录: {agents_dir}")
            return []

        candidate_files = sorted(agents_dir.rglob("agent_template.json"))
        if not candidate_files:
            logger.error(f"agents 目录下未找到 agent_template.json 文件: {agents_dir}")
            return []

        # 返回匹配的路径列表
        return candidate_files

    def get_agent_template_raw_data(self) -> List[AgentTemplateRaw]:
        if self._agent_templates_cache:
            return [deepcopy(template) for template in self._agent_templates_cache]

        templates: List[AgentTemplateRaw] = []
        config_paths = self._get_agent_template_config_paths()
        if not config_paths:
            return templates

        for config_path in config_paths:
            try:
                payload = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    templates.append(AgentTemplateRaw(**payload))
                else:
                    logger.error(
                        f"Agent模板文件必须是JSON对象: {config_path}"
                    )
            except Exception as exc:
                logger.error(
                    f"读取Agent模板配置文件失败: {config_path} - {exc}",
                    exc_info=True,
                )

        self._agent_templates_cache = templates
        return [deepcopy(template) for template in templates]

       
    # ==================== AgentType表数据初始化 ==============
    
    async def init_agent_type_data(self) -> bool:
        templates = self.get_agent_template_raw_data()
        if not templates:
            logger.warning("未加载到任何Agent模板，跳过AgentType初始化")
            return False
        if not self._db_manager.is_connected:
            connected = await self._db_manager.connect()
            if not connected:
                logger.error("数据库连接失败，无法初始化AgentType表")
                return False

        try:
            async with self._db_manager.get_session() as session:
                inserted_count = 0
                for template in templates:
                    #生成agent_type_id和agent_template_id
                    template.ensure_identity()
                    #生成create_time和update_time
                    template.stamp_now()

                    stmt = select(AgentTypeDBModel.agent_type_id).where(
                        AgentTypeDBModel.agent_type_name == template.agent_type_name
                    )
                    exists = (await session.execute(stmt)).scalar_one_or_none()
                    if exists:
                        logger.info(
                            "AgentType记录已存在，跳过写入: {}",
                            template.agent_type_name,
                        )
                        continue

                    await session.merge(
                        AgentTypeDBModel(
                            agent_type_id=template.agent_type_id,
                            agent_type_name=template.agent_type_name,
                            agent_template_id=template.agent_template_id,
                            create_time=template.create_time,
                            update_time=template.update_time,
                        )
                        )
                    inserted_count += 1

            self._agent_templates_cache = templates

            logger.info(f"AgentType表初始化完成，写入 {inserted_count} 条记录")
            return True
        except Exception as exc:
            logger.error(f"初始化AgentType表失败: {exc}", exc_info=True)
            return False

    # ==================== Agent配置模板表数据初始化 ==============

    async def init_agent_template_data(self) -> bool:
        templates = self.get_agent_template_raw_data()
        if not templates:
            logger.warning("未加载到任何Agent模板，跳过Agent模板表初始化")
            return False

        if not self._db_manager.is_connected:
            connected = await self._db_manager.connect()
            if not connected:
                logger.error("数据库连接失败，无法初始化Agent模板表")
                return False

        try:
            async with self._db_manager.get_session() as session:
                inserted_count = 0
                for template in templates:
                    template.ensure_identity()
                    template.stamp_now()

                    stmt = select(AgentTemplateDBModel.agent_type_name).where(
                        AgentTemplateDBModel.agent_type_name == template.agent_type_name
                    )
                    exists = (await session.execute(stmt)).scalar_one_or_none()
                    if exists:
                        logger.info(
                            "Agent模板记录已存在，跳过写入: {}",
                            template.agent_type_name,
                        )
                        continue

                    await session.merge(
                        AgentTemplateDBModel(
                            agent_template_id=template.agent_template_id,
                            agent_type_id=template.agent_type_id,
                            agent_type_name=template.agent_type_name,
                            model_config=json.dumps(template.model_config, ensure_ascii=False),
                            prompt_config=json.dumps(template.prompt_config, ensure_ascii=False),
                            mcp_tool_config=json.dumps(template.mcp_tool_config, ensure_ascii=False),
                            mcp_server_config=json.dumps(template.mcp_server_config, ensure_ascii=False),
                            create_time=template.create_time,
                            update_time=template.update_time,
                        )
                    )
                    inserted_count += 1

            logger.info(f"Agent模板表初始化完成，写入 {inserted_count} 条记录")
            return True
        except Exception as exc:
            logger.error(f"初始化Agent模板表失败: {exc}", exc_info=True)
            return False


    # ==================== Agent 获取和创建 ====================
    
    async def get_agent(self, agent_id: str) -> Optional[Any]:
        """
        获取 Agent 对象
        如果已存在则返回，否则尝试创建
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            Agent 对象，如果无法获取/创建则返回 None
        """
        # 检查是否已存在
        if agent_id in self._agents:
            logger.debug(f"Agent 已存在，直接返回: {agent_id}")
            return self._agents[agent_id]
        
        # 不存在，尝试创建
        return await self.create_agent(agent_id)
    
    async def create_agent(self, agent_id: str) -> Optional[Any]:
        """
        创建 Agent 对象
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            创建的 Agent 对象，如果创建失败则返回 None
        """
        async with self._lock:
            # 双重检查
            if agent_id in self._agents:
                return self._agents[agent_id]
            
            try:
                # 1. 从配置管理器获取配置
                config = await self._config_manager.get_config(agent_id)
                
                if not config:
                    logger.error(f"无法获取 Agent 配置: {agent_id}")
                    return None
                
                # 2. 使用唯一的 agent_type_name 获取对应的 Agent 类
                lookup_key = config.agent_type_name
                agent_class = AgentRegistry.get(lookup_key)

                if not agent_class:
                    logger.error(f"未注册的 Agent 类型: {lookup_key}")
                    return None
                
                # 3. 创建 Agent 实例（agent_class 可能是任意可调用），
                #    构造器期望接收一个 JSON 字符串形式的 config（str）。
                #    我们先把配置对象序列化为 JSON 字符串再尝试构造，若失败
                #    则尝试无参构造。
                try:
                    # 尝试使用 Pydantic v2 的 model_dump 或 v1 的 dict/json
                    cfg_str = None
                    try:
                        cfg_str = json.dumps(config.config_schema)
                    except Exception:
                        cfg_str = "{}"

                    agent = agent_class(cfg_str)
                except TypeError:
                    try:
                        agent = agent_class()
                    except Exception as e:
                        logger.error(f"实例化 Agent 类失败: {agent_class} - {e}")
                        return None
                except Exception as e:
                    logger.error(f"实例化 Agent 类时发生错误: {e}")
                    return None

                # 4. 缓存 Agent 实例
                self._agents[agent_id] = agent
                
                # 记录创建信息，显示类型名
                logger.info(f"Agent 创建成功: {agent_id} (agent_type_name={config.agent_type_name})")
                return agent
                
            except Exception as e:
                logger.error(f"创建 Agent 失败 {agent_id}: {e}")
                return None
    
    def has_agent(self, agent_id: str) -> bool:
        """检查 Agent 是否已创建"""
        return agent_id in self._agents
    
    def get_all_agents(self) -> Dict[str, ABC]:
        """获取所有 Agent 实例"""
        return self._agents.copy()
    
    def get_all_agent_ids(self) -> List[str]:
        """获取所有已创建的 Agent 的 agent_id"""
        return list(self._agents.keys())
    
    # ==================== Agent 任务执行 ====================
    
    async def execute_task(self, request: AgentTaskRequest) -> AgentTaskResponse:
        """
        执行 Agent 任务
        
        流程：
        1. 判断 Agent 对象是否存在
        2. 如果不存在则创建
        3. 执行任务
        4. 异步上报轨迹信息
        
        Args:
            request: 任务请求
            
        Returns:
            任务响应
        """
        start_time = time.time()
        agent_id = request.agent_id
        session_id = request.session_id or str(uuid.uuid4())
        
        try:
            # 1. 获取或创建 Agent
            agent = await self.get_agent(agent_id)
            
            if not agent:
                return AgentTaskResponse(
                    success=False,
                    agent_id=agent_id,
                    session_id=session_id,
                    output=None,
                    error=f"无法获取或创建 Agent: {agent_id}",
                    execution_time=time.time() - start_time
                )
            
            # 2. 设置上下文
            history = None
            session_info = await self._db_manager.get_session_info(session_id)
            if session_info:
                history = session_info.conversation_history.context
            
            # 3. 执行任务
            try:
                input_data = dict(request.input)
                if request.user_name is not None:
                    input_data["user_name"] = request.user_name
                output = await asyncio.wait_for(
                    agent.invoke(
                        input_data=input_data,
                        history=history
                    ),
                    timeout=request.timeout
                )
                success = True
                error = None
            except asyncio.TimeoutError:
                output = None
                success = False
                error = f"任务执行超时（{request.timeout}秒）"
            except Exception as e:
                output = None
                success = False
                error = str(e)
                logger.error(f"Agent 任务执行失败 {agent_id}: {e}")
            
            execution_time = time.time() - start_time
            
            # 4. 获取轨迹信息并转换为 Trajectory 对象
            # 输出可能是 None / 列表 / 单个 dict 或字符串。
            # 目标：把 output 转为 Trajectory，其中 TrajectoryStep.state = 第一条 role 配对的 content，
            # TrajectoryStep.action = 第二条 role 配对的 content
            # 使用独立函数将 messages/output 转为 Trajectory
            trajectory = self._build_trajectory(output, request.session_ended)
            
            # 5. 异步上报轨迹信息（不阻塞返回）
            asyncio.create_task(
                self._execute_trajectory_report_and_evaluation(
                    agent_id=agent_id,
                    session_id=session_id,
                    user_id=request.user_id,
                    trajectory=trajectory,
                    session_ended=request.session_ended
                )
            )

            # 获取任务运行状态
            task_status = "running"
            if success and request.session_ended:
                task_status = "done"
            elif not success:
                task_status = "failed"

            # 保存任务和会话信息（只传新消息，由 DB 层原子追加）
            asyncio.create_task(self._save_task_and_session_info(
                agent_id=agent_id,
                session_id=session_id,
                user_id=request.user_id,
                task_status=task_status,
                output=output,
            ))
            
            
            # 返回通过 _build_output_result 构造的 AgentTaskResponse
            return self._build_output_result(
                agent_id=agent_id,
                session_id=session_id,
                success=success,
                output=output,
                error=error,
                execution_time=execution_time,
            )
            
        except Exception as e:
            logger.error(f"执行任务时发生错误 {agent_id}: {e}", exc_info=True)
            return AgentTaskResponse(
                success=False,
                agent_id=agent_id,
                session_id=session_id,
                output=None,
                error=str(e),
                execution_time=time.time() - start_time
            )

    async def _save_task_and_session_info(
        self,
        agent_id: str,
        session_id: str,
        user_id: str,
        task_status: str,
        output: List[Dict],
    ):
        """
        保存任务和会话信息
        """
        # 确保 output 是列表格式，以满足 ContextContent 校验
        task_output = output
        if task_output is None:
            task_output = []
        elif isinstance(task_output, dict):
            task_output = [task_output]
        elif not isinstance(task_output, list):
             # 如果是字符串或其他类型，尝试包装为 assistant 消息
             if isinstance(task_output, str):
                 task_output = [{"role": "assistant", "content": task_output}]
             else:
                 # 兜底：包装为列表
                 task_output = [task_output]

        task_id = str(uuid.uuid4())
        await self._db_manager.save_task(
            task_id=task_id,
            agent_id=agent_id,
            session_id=session_id,
            task_new_context=task_output,
            user_id=user_id,
            task_status=task_status,
        )
        await self._db_manager.save_session_info(
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            task_id=task_id,
            new_messages=task_output,
        )


    async def _execute_trajectory_report_and_evaluation(
        self,
        agent_id: str,
        session_id: str,
        user_id: str,
        trajectory: Trajectory,
        session_ended: bool
    ) -> None:
        """
        顺序执行后台任务：先上报轨迹，然后根据 session_ended 决定是否评估
        
        逻辑：
        1. 总是上报轨迹信息到数据库
        2. 只有当 session_ended=True（任务的最后一个会话）时，才调用评估模型
        3. 如果 session_ended=False，只上报轨迹，不调用评估模型
        
        Args:
            agent_id: Agent ID
            session_id: 会话ID
            user_id: 用户ID
            trajectory: 轨迹信息
            session_ended: 会话是否结束（True表示最后一个会话，需要评估）
        """
        try:
            # 步骤1：上报轨迹信息（所有会话都需要上报）
            await self._report_trajectory(
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                trajectory=trajectory
            )
            logger.debug(f"轨迹上报完成: session_id={session_id}")
            
            # 步骤2：只有当任务的最后一个会话（session_ended=True）时，才调用评估模型
            if session_ended:
                try:
                    logger.info(
                        f"会话结束（最后一个会话），调用评估模型 - agent_id={agent_id}, "
                        f"user_id={user_id}, session_id={session_id}"
                    )
                    
                    # 调用评估模型，评估模型会从数据库拉取轨迹信息
                    eval_response = await self._evaluator.evaluate_trajectory(
                        agent_id=agent_id,
                        user_id=user_id,
                        session_id=session_id,
                        force_reevaluate=False
                    )
                    
                    if eval_response.success:
                        logger.info(
                            f"评估完成 - session_id={session_id}, "
                            f"evaluation_id={eval_response.evaluation_id}, "
                            f"score={eval_response.evaluation.overall.score}"
                        )
                    else:
                        logger.warning(
                            f"评估失败 - session_id={session_id}, "
                            f"error={eval_response.error}"
                        )
                        
                except Exception as e:
                    logger.error(
                        f"调用评估模型时出错 - session_id={session_id}: {e}",
                        exc_info=True
                    )
            else:
                # session_ended=False，只上报轨迹，不调用评估模型
                logger.debug(
                    f"非最后会话，仅上报轨迹，不调用评估模型 - session_id={session_id}"
                )
                    
        except Exception as e:
            logger.error(f"顺序后台任务执行失败: {e}", exc_info=True)    
    
    async def execute_task_stream(
        self,
        request: AgentTaskRequest
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        流式执行 Agent 任务
        
        Args:
            request: 任务请求
            
        Yields:
            StreamChunk: 流式数据块
        """
        start_time = time.time()
        agent_id = request.agent_id
        session_id = request.session_id or str(uuid.uuid4())
        chunk_index = 0
        collected_output = []
        success = True
        error = None
        
        logger.info(f"收到流式任务请求: agent_id={agent_id}, user_id={request.user_id}")
        
        try:
            # 1. 获取或创建 Agent
            agent = await self.get_agent(agent_id)
            
            if not agent:
                yield StreamChunk(
                    event=StreamEventType.ERROR,
                    data={"error": f"无法获取或创建 Agent: {agent_id}"},
                    agent_id=agent_id,
                    session_id=session_id,
                    chunk_index=chunk_index
                )
                return
            
            # 2. 设置上下文
            history = None
            session_info = await self._db_manager.get_session_info(session_id)
            if session_info:
                history = session_info.conversation_history.context
            
            # 3. 流式执行任务
            try:
                input_data = dict(request.input)
                if request.user_name is not None:
                    input_data["user_name"] = request.user_name
                async for chunk in agent.stream(
                    input_data=input_data,
                    history=history
                ):
                    current_chunk_index = chunk_index
                    chunk_index += 1
                    
                    # 收集输出
                    if isinstance(chunk, dict) and "content" in chunk:
                        collected_output.append(chunk)
                    
                    yield StreamChunk(
                        event=StreamEventType.CONTENT,
                        data=chunk,
                        agent_id=agent_id,
                        session_id=session_id,
                        chunk_index=current_chunk_index
                    )
                    
            except asyncio.TimeoutError:
                success = False
                error = f"任务执行超时（{request.timeout}秒）"
                yield StreamChunk(
                    event=StreamEventType.ERROR,
                    data={"error": error},
                    agent_id=agent_id,
                    session_id=session_id,
                    chunk_index=chunk_index
                )
                return
            except Exception as e:
                success = False
                error = str(e)
                logger.error(f"流式执行失败 {agent_id}: {e}")
                yield StreamChunk(
                    event=StreamEventType.ERROR,
                    data={"error": error},
                    agent_id=agent_id,
                    session_id=session_id,
                    chunk_index=chunk_index
                )
                return
            
            execution_time = time.time() - start_time
            
            # 4. 获取轨迹信息并转换为 Trajectory 对象
            trajectory = self._build_trajectory(collected_output, request.session_ended)
            
            # 5. 异步上报轨迹信息（不阻塞返回）
            asyncio.create_task(
                self._execute_trajectory_report_and_evaluation(
                    agent_id=agent_id,
                    session_id=session_id,
                    user_id=request.user_id,
                    trajectory=trajectory,
                    session_ended=request.session_ended
                )
            )

            # 获取任务运行状态
            task_status = "running"
            if success and request.session_ended:
                task_status = "done"
            elif not success:
                task_status = "failed"

            # 保存任务和会话信息（只传新消息，由 DB 层原子追加）
            asyncio.create_task(self._save_task_and_session_info(
                agent_id=agent_id,
                session_id=session_id,
                user_id=request.user_id,
                task_status=task_status,
                output=collected_output,
            ))
            
            # 发送完成事件
            yield StreamChunk(
                event=StreamEventType.DONE,
                data={
                    "success": success,
                    "error": error,
                    "execution_time": execution_time
                },
                agent_id=agent_id,
                session_id=session_id,
                chunk_index=chunk_index
            )
                            
        except Exception as e:
            logger.error(f"流式执行时发生错误 {agent_id}: {e}")
            yield StreamChunk(
                event=StreamEventType.ERROR,
                data={"error": str(e)},
                agent_id=agent_id,
                session_id=session_id,
                chunk_index=chunk_index
            )
    
    async def _report_trajectory(
        self,
        agent_id: str,
        session_id: str,
        user_id: str,
        trajectory: Trajectory
    ) -> None:
        """
        异步上报轨迹信息到数据库
        
        Args:
            agent_id: Agent 包ID
            session_id: 会话ID
            user_id: 用户ID
            trajectory: 轨迹信息
        """
        try:
            trajectory_data = AgentTrajectory(
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                trajectory=trajectory,
                create_time=datetime.now(),
                update_time=datetime.now()
            )
            
            await self._db_manager.save_agent_trajectory(trajectory_data)
            logger.debug(f"轨迹信息上报成功: {agent_id}")
        except Exception as e:
            logger.error(f"上报轨迹信息失败 {agent_id}: {e}")
    
    # ==================== Agent 健康状态 ====================
    
    async def get_agent_health(self, agent_id: str) -> Optional[AgentHealthStatus]:
        """
        获取指定 Agent 的健康状态
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            健康状态，如果 Agent 不存在则返回 None
        """
        if agent_id not in self._agents:
            return None
        
        agent = self._agents[agent_id]
        await agent.health_check()
        return agent.get_health_status()
    
    async def get_all_agents_health(self) -> List[AgentHealthStatus]:
        """
        获取所有 Agent 的健康状态
        
        Returns:
            所有 Agent 的健康状态列表
        """
        health_statuses = []
        
        for agent_id, agent in self._agents.items():
            try:
                pass
                #预留模块，待后续实现
                #await agent.health_check()
                #health_statuses.append(agent.get_health_status())
            except Exception as e:
                logger.error(f"获取 Agent 健康状态失败 {agent_id}: {e}")
        
        return health_statuses
    
    # ==================== Agent 生命周期管理 ====================
    
    async def stop_agent(self, agent_id: str) -> bool:
        """
        停止指定 Agent
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            是否成功停止
        """
        if agent_id not in self._agents:
            logger.warning(f"Agent 不存在: {agent_id}")
            return False
        
        try:
            del self._agents[agent_id]
            logger.info(f"Agent 已停止并移除: {agent_id}")
            return True
        except Exception as e:
            logger.error(f"停止 Agent 失败 {agent_id}: {e}")
            return False
    
    async def stop_all_agents(self) -> int:
        """
        停止所有 Agent
        
        Returns:
            成功停止的 Agent 数量
        """
        stopped_count = 0
        agent_ids = list(self._agents.keys())
        
        for agent_id in agent_ids:
            if await self.stop_agent(agent_id):
                stopped_count += 1
        
        logger.info(f"已停止 {stopped_count} 个 Agent")
        return stopped_count
    
    async def restart_agent(self, agent_id: str) -> Optional[ABC]:
        """
        重启指定 Agent
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            重启后的 Agent 对象
        """
        await self.stop_agent(agent_id)
        return await self.create_agent(agent_id)
    
    def get_agent_count(self) -> int:
        """获取当前活跃的 Agent 数量"""
        return len(self._agents)


# 全局 Agent 管理器实例获取函数
_agent_manager: Optional[AgentManager] = None


def get_agent_manager() -> AgentManager:
    """获取全局 Agent 管理器实例"""
    # Always return the class-level singleton to avoid divergence between
    # module-level cache and AgentManager._instance. Tests may reset the
    # class-level instance directly, so overwrite the module-level variable
    # to keep callers consistent.
    global _agent_manager
    _agent_manager = AgentManager.get_instance()
    return _agent_manager


async def init_agent_manager(
    config_manager: Optional[AgentConfigManager] = None,
    db_manager: Optional[DatabaseManager] = None
) -> AgentManager:
    """
    初始化 Agent 管理器
    
    Args:
        config_manager: 可选的配置管理器实例
        db_manager: 可选的数据库管理器实例
        
    Returns:
        Agent 管理器实例
    """
    # Create/obtain the class-level singleton so module and class singletons
    # remain consistent across the codebase.
    global _agent_manager
    _agent_manager = AgentManager.get_instance(config_manager, db_manager)

    # 初始化AgentType表数据
    try:
        agent_type_initialized = await _agent_manager.init_agent_type_data()
    except Exception:
        logger.error("初始化AgentType表时发生异常", exc_info=True)
        raise

    if not agent_type_initialized:
        raise RuntimeError("AgentType表初始化失败，终止Agent管理器初始化")

    # 初始化Agent配置模板表数据
    try:
        agent_template_initialized = await _agent_manager.init_agent_template_data()
    except Exception:
        logger.error("初始化Agent配置模板表时发生异常", exc_info=True)
        raise

    if not agent_template_initialized:
        raise RuntimeError("Agent配置模板表初始化失败，终止Agent管理器初始化")
    
    return _agent_manager
