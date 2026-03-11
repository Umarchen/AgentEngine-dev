"""
Agent Engine Service 完整功能测试
测试所有需求中的功能点:
1. 初始化 - 从数据库加载Agent配置
2. Agent请求响应 - 任务执行、Agent创建/复用
3. Agent状态信息上报 - 健康检查上报
4. Agent运行轨迹信息上报 - 轨迹记录与异步上报
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# 导入必要模块
from src.models.schemas import (
    AgentConfig,
    AgentTaskRequest,
    AgentTaskResponse,
    AgentHealthStatus,
    AgentTrajectory,
    TrajectoryStep,
    Trajectory,
    HealthChecks,
)
from src.database.database import DatabaseManager
from src.core.base import AgentRegistry
from src.core.config_manager import AgentConfigManager
from src.core.agent_manager import AgentManager
from src.services.health_reporter import HealthReporter

# 导入 agents 模块以触发 Agent 类的注册
import src.agents


class TestInitialization:
    """
    功能点1: 初始化测试
    - 从数据库拉取Agent配置信息
    - 保存在Agent配置信息管理模块中
    """

    @pytest.fixture
    async def db_manager(self):
        """创建并连接数据库管理器"""
        db = DatabaseManager("sqlite:///test_init.db")
        await db.connect()
        yield db
        await db.disconnect()

    @pytest.fixture
    async def config_manager(self, db_manager):
        """创建配置管理器"""
        AgentConfigManager.reset_instance()
        cm = AgentConfigManager(db_manager)
        return cm

    @pytest.mark.asyncio
    async def test_database_connection(self, db_manager):
        """测试数据库连接"""
        assert db_manager.is_connected is True

    @pytest.mark.asyncio
    async def test_load_configs_from_database(self, db_manager, config_manager):
        """测试从数据库加载配置"""
        # 准备测试数据
        test_configs = [
            AgentConfig(
                agent_config_id="cfg-pkg-001",
                agent_id="pkg-001",
                agent_type_id="uuid-echo-xxx",
                agent_type_name="echo_agent",
                description="测试Echo Agent",
                config_schema={"type": "object"}
            ),
            AgentConfig(
                agent_config_id="cfg-pkg-002",
                agent_id="pkg-002",
                agent_type_id="uuid-risk-assessment-xxx",
                agent_type_name="risk-assessment",
                description="风险评估Agent"
            )
        ]
        
        # 保存到数据库
        for config in test_configs:
            await db_manager.save_agent_config(config)
        
        # 初始化配置管理器
        success = await config_manager.initialize()
        assert success is True
        assert config_manager.is_initialized is True
        
        # 验证配置已加载
        config1 = await config_manager.get_config("pkg-001")
        assert config1 is not None
        assert config1.agent_type_name == "echo_agent"

        config2 = await config_manager.get_config("pkg-002")
        assert config2 is not None
        assert config2.agent_type_name == "risk-assessment"
    @pytest.mark.asyncio
    async def test_config_data_format(self, db_manager, config_manager):
        """测试配置数据格式完整性"""
        config = AgentConfig(
            agent_config_id="cfg-pkg-format-test",
            agent_id="pkg-format-test",
            agent_type_id="uuid-echo-xxx",
            agent_type_name="echo_agent",
            description="测试数据格式",
            config_schema={"type": "object", "properties": {}}
        )
        
        await db_manager.save_agent_config(config)
        retrieved = await db_manager.get_agent_config("pkg-format-test")
        
        # 验证所有字段
        assert retrieved.agent_id == "pkg-format-test"
        assert retrieved.agent_type_name == "echo_agent"
        assert retrieved.description == "测试数据格式"
        assert retrieved.config_schema == {"type": "object", "properties": {}}
        assert isinstance(retrieved.create_time, datetime)


class TestAgentTaskResponse:
    """
    功能点2: Agent请求响应测试
    - 判断agent对象是否已创建
    - 通过agent_id找到对应的agent对象
    - 创建新agent对象
    - 执行Agent任务
    """

    @pytest.fixture
    async def setup_manager(self):
        """设置测试环境"""
        db_manager = DatabaseManager("sqlite:///test_task.db")
        await db_manager.connect()
        
        AgentConfigManager.reset_instance()
        config_manager = AgentConfigManager(db_manager)
        
        # 添加测试配置
        config = AgentConfig(
            agent_config_id="cfg-pkg-task-test",
            agent_id="pkg-task-test",
            agent_type_id="uuid-echo-xxx",
            agent_type_name="echo_agent"
        )
        await config_manager.add_config(config)
        
        AgentManager.reset_instance()
        agent_manager = AgentManager(config_manager, db_manager)
        
        yield {
            "db_manager": db_manager,
            "config_manager": config_manager,
            "agent_manager": agent_manager
        }
        
        await agent_manager.stop_all_agents()
        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_agent_not_exists_then_create(self, setup_manager):
        """测试Agent不存在时创建新Agent"""
        agent_manager = setup_manager["agent_manager"]
        
        # 确认Agent不存在
        assert agent_manager.has_agent("pkg-task-test") is False
        
        # 获取Agent（应该会自动创建）
        agent = await agent_manager.get_agent("pkg-task-test")
        
        assert agent is not None
        assert agent_manager.has_agent("pkg-task-test") is True

    @pytest.mark.asyncio
    async def test_agent_exists_reuse(self, setup_manager):
        """测试Agent已存在时复用"""
        agent_manager = setup_manager["agent_manager"]
        
        # 第一次获取Agent
        agent1 = await agent_manager.get_agent("pkg-task-test")
        assert agent1 is not None
        
        # 第二次获取Agent
        agent2 = await agent_manager.get_agent("pkg-task-test")
        
        # 应该是同一个实例
        assert agent1 is agent2

    @pytest.mark.asyncio
    async def test_execute_task_with_request(self, setup_manager):
        """测试任务执行请求"""
        agent_manager = setup_manager["agent_manager"]
        
        request = AgentTaskRequest(
            agent_id="pkg-task-test",
            user_id="user-001",
            session_id="session-001",
            input={"query": "Hello, Agent!"},
            timeout=60
        )
        
        response = await agent_manager.execute_task(request)
        
        # 验证响应
        assert response.success is True
        assert response.agent_id == "pkg-task-test"
        assert response.session_id == "session-001"
        assert response.output is not None
        assert response.error is None
        assert response.execution_time > 0

    @pytest.mark.asyncio
    async def test_execute_task_without_session_id(self, setup_manager):
        """测试不传session_id时自动生成"""
        agent_manager = setup_manager["agent_manager"]
        
        request = AgentTaskRequest(
            agent_id="pkg-task-test",
            user_id="user-001",
            input={"query": "Test without session"}
        )
        
        response = await agent_manager.execute_task(request)
        
        assert response.success is True
        assert response.session_id is not None
        assert len(response.session_id) > 0

    @pytest.mark.asyncio
    async def test_execute_task_config_not_found(self, setup_manager):
        """测试配置不存在时失败"""
        agent_manager = setup_manager["agent_manager"]
        
        request = AgentTaskRequest(
            agent_id="non-existent-pkg",
            user_id="user-001",
            input={"query": "Test"}
        )
        
        response = await agent_manager.execute_task(request)
        
        assert response.success is False
        assert "无法获取或创建" in response.error

    @pytest.mark.asyncio
    async def test_dynamic_agent_registration(self):
        """测试Agent类动态注册"""
        # 检查已注册的Agent类型
        echo_class = AgentRegistry.get("echo_agent")
        assert echo_class is not None
        
        risk_class = AgentRegistry.get("risk-assessment")
        assert risk_class is not None
        
        # 检查不存在的类型
        unknown_class = AgentRegistry.get("unknown-type")
        assert unknown_class is None


class TestTrajectoryReport:
    """
    功能点4: Agent运行轨迹信息上报测试
    - 记录轨迹信息
    - 异步上传至数据库（不阻塞Agent返回）
    """

    @pytest.fixture
    async def setup_trajectory_test(self):
        """设置轨迹测试环境"""
        db_manager = DatabaseManager("sqlite:///test_trajectory.db")
        await db_manager.connect()
        
        AgentConfigManager.reset_instance()
        config_manager = AgentConfigManager(db_manager)
        
        config = AgentConfig(
            agent_config_id="cfg-pkg-trajectory-test",
            agent_id="pkg-trajectory-test",
            agent_type_id="uuid-echo-xxx",
            agent_type_name="echo_agent"
        )
        await config_manager.add_config(config)
        
        AgentManager.reset_instance()
        agent_manager = AgentManager(config_manager, db_manager)
        
        yield {
            "db_manager": db_manager,
            "agent_manager": agent_manager
        }
        
        await agent_manager.stop_all_agents()
        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_trajectory_data_format(self, setup_trajectory_test):
        """测试轨迹数据格式"""
        db_manager = setup_trajectory_test["db_manager"]
        
        # 构造测试轨迹数据
        trajectory = AgentTrajectory(
            agent_id="pkg-trajectory-test",
            session_id="session-traj-001",
            user_id="user-001",
            trajectory=Trajectory(steps=[
                TrajectoryStep(
                    step=0,
                    state="当前环境的观测值",
                    action="智能体采取的操作",
                    reward=0.0,
                    next_state="执行动作后的观测值",
                    is_terminal=False
                ),
                TrajectoryStep(
                    step=1,
                    state="执行动作后的观测值",
                    action="最终操作",
                    reward=1.0,
                    next_state="任务完成",
                    is_terminal=True
                )
            ])
        )
        
        # 保存轨迹
        result = await db_manager.save_agent_trajectory(trajectory)
        assert result is True

    @pytest.mark.asyncio
    async def test_trajectory_async_save(self, setup_trajectory_test):
        """测试轨迹异步保存（非阻塞）"""
        agent_manager = setup_trajectory_test["agent_manager"]
        
        import time
        
        request = AgentTaskRequest(
            agent_id="pkg-trajectory-test",
            user_id="user-001",
            input={"query": "测试异步保存"}
        )
        
        # 记录执行时间
        start_time = time.time()
        response = await agent_manager.execute_task(request)
        execution_time = time.time() - start_time
        
        assert response.success is True
        # 验证执行时间合理（轨迹保存不应该阻塞）
        # Echo Agent的模拟延迟是0.1秒，加上一些处理时间
        assert execution_time < 1.0  # 应该在1秒内完成


class TestDatabaseOperations:
    """
    特性测试: 数据库操作模块独立性
    - 配置信息读取
    - Agent状态信息写入
    - Agent任务轨迹信息写入
    """

    @pytest.fixture
    async def db_manager(self):
        """创建数据库管理器"""
        db = DatabaseManager("sqlite:///test_db_ops.db")
        await db.connect()
        yield db
        await db.disconnect()

    @pytest.mark.asyncio
    async def test_config_read_operations(self, db_manager):
        """测试配置信息读取操作"""
        # 保存配置
        config = AgentConfig(
            agent_config_id="cfg-pkg-db-test",
            agent_id="pkg-db-test",
            agent_type_id="uuid-echo-xxx",
            agent_type_name="echo_agent"
        )
        await db_manager.save_agent_config(config)
        
        # 读取单个配置
        retrieved = await db_manager.get_agent_config("pkg-db-test")
        assert retrieved is not None
        
        # 读取所有配置
        all_configs = await db_manager.get_all_agent_configs()
        assert len(all_configs) > 0

    @pytest.mark.asyncio
    async def test_status_write_operations(self, db_manager):
        """测试Agent状态信息写入操作"""
        status = AgentHealthStatus(
            agent_id="pkg-db-test",
            agent_type_name="echo_agent",
            status="healthy",
            checks=HealthChecks(alive=True, responsive=True, task_queue_healthy=True),
            uptime_seconds=3600.5
        )
        
        # 单条写入
        result = await db_manager.save_agent_status(status)
        assert result is True
        
        # 等待写入队列处理
        await asyncio.sleep(0.2)
        
        # 批量写入
        statuses = [status, status]
        result = await db_manager.save_agent_status_batch(statuses)
        assert result is True

    @pytest.mark.asyncio
    async def test_trajectory_write_operations(self, db_manager):
        """测试Agent轨迹信息写入操作"""
        trajectory = AgentTrajectory(
            agent_id="pkg-db-test",
            session_id="session-db-test",
            user_id="user-001",
            trajectory=Trajectory(steps=[
                TrajectoryStep(
                    step=0,
                    state="state0",
                    action="action0",
                    reward=0.0,
                    next_state="state1",
                    is_terminal=True
                )
            ])
        )
        
        # 写入轨迹
        result = await db_manager.save_agent_trajectory(trajectory)
        assert result is True
        
        # 等待写入队列处理
        await asyncio.sleep(0.2)
        
        # 查询轨迹历史
        history = await db_manager.get_trajectory_history(
            agent_id="pkg-db-test",
            limit=10
        )
        assert len(history) > 0


class TestAgentRegistration:
    """测试Agent动态注册机制"""

    def test_registered_agent_types(self):
        """测试已注册的Agent类型"""
        all_agents = AgentRegistry.get_all()
        
        # 检查预期的Agent类型
        assert "echo_agent" in all_agents
        assert "risk-assessment" in all_agents

    def test_agent_creation_by_type(self):
        """测试根据类型创建Agent"""
        config = AgentConfig(
            agent_config_id="cfg-pkg-type-test",
            agent_id="pkg-type-test",
            agent_type_id="uuid-echo-xxx",
            agent_type_name="echo_agent"
        )
        
        agent_class = AgentRegistry.get("echo_agent")
        # Agent constructors now expect a JSON string as config
        agent = agent_class(config.json())

        assert agent is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
