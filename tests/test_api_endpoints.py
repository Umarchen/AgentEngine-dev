"""
Agent Engine Service API 端点测试
测试所有 RESTful API 接口
"""

import pytest
import asyncio
from datetime import datetime
from typing import Dict, Any

from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from src.app import create_app
from src.models.schemas import AgentConfig
from src.database.database import DatabaseManager
from src.core.config_manager import AgentConfigManager
from src.core.agent_manager import AgentManager
from src.services.health_reporter import HealthReporter

# 导入 agents 模块以触发 Agent 类的注册
import src.agents


class TestAPIEndpoints:
    """API 端点测试"""

    @pytest.fixture
    def app(self):
        """创建测试应用"""
        return create_app()

    @pytest.fixture
    def client(self, app):
        """创建同步测试客户端"""
        return TestClient(app)

    @pytest.fixture
    async def async_client(self, app):
        """创建异步测试客户端"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
            yield ac

    def test_root_endpoint(self, client):
        """测试根路径"""
        response = client.get("/")
        # 根据app.py中的定义，可能返回404或者有根路由
        assert response.status_code in [200, 404]

    def test_docs_endpoint(self, client):
        """测试API文档端点"""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_openapi_endpoint(self, client):
        """测试OpenAPI端点"""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "info" in data


class TestAgentConfigAPI:
    """Agent配置管理API测试"""

    @pytest.fixture
    async def setup_api_test(self):
        """设置API测试环境"""
        # 重置单例
        DatabaseManager._instance = None
        AgentConfigManager.reset_instance()
        AgentManager.reset_instance()
        HealthReporter.reset_instance()
        
        db_manager = DatabaseManager.get_instance("sqlite:///test_api.db")
        await db_manager.connect()
        
        config_manager = AgentConfigManager.get_instance(db_manager)
        await config_manager.initialize()
        
        # 添加测试配置
        test_config = AgentConfig(
            agent_config_id="cfg-api-test-pkg-001",
            agent_id="api-test-pkg-001",
            agent_type_id="uuid-echo-xxx",
            agent_type_name="echo_agent",
            description="用于API测试的Agent"
        )
        await config_manager.add_config(test_config)
        
        agent_manager = AgentManager.get_instance(config_manager, db_manager)
        health_reporter = HealthReporter.get_instance(agent_manager, db_manager, 60)
        
        yield {
            "db_manager": db_manager,
            "config_manager": config_manager,
            "agent_manager": agent_manager,
            "health_reporter": health_reporter
        }
        
        await health_reporter.stop()
        await agent_manager.stop_all_agents()
        await db_manager.disconnect()
        
        # 重置单例
        DatabaseManager._instance = None
        AgentConfigManager.reset_instance()
        AgentManager.reset_instance()
        HealthReporter.reset_instance()

    @pytest.mark.asyncio
    async def test_get_all_configs(self, setup_api_test):
        """测试获取所有配置"""
        from src.api.router import get_all_configs
        
        configs = await get_all_configs()
        assert len(configs) >= 1
        
        # 验证测试配置存在
        agent_ids = [c.agent_id for c in configs]
        assert "api-test-pkg-001" in agent_ids

    @pytest.mark.asyncio
    async def test_get_single_config(self, setup_api_test):
        """测试获取单个配置"""
        from src.api.router import get_config
        
        config = await get_config("api-test-pkg-001")
        assert config is not None
        assert config.agent_id == "api-test-pkg-001"
        assert config.agent_type_name == "echo_agent"

    @pytest.mark.asyncio
    async def test_add_config(self, setup_api_test):
        """测试添加配置"""
        from src.api.router import add_config
        
        new_config = AgentConfig(
            agent_config_id="cfg-api-test-pkg-new",
            agent_id="api-test-pkg-new",
            agent_type_id="uuid-echo-xxx",
            agent_type_name="echo_agent"
        )
        
        result = await add_config(new_config)
        assert result["success"] is True
        
        # 验证配置已添加
        config_manager = setup_api_test["config_manager"]
        config = await config_manager.get_config("api-test-pkg-new")
        assert config is not None


class TestAgentExecutionAPI:
    """Agent任务执行API测试"""

    @pytest.fixture
    async def setup_execution_test(self):
        """设置执行测试环境"""
        DatabaseManager._instance = None
        AgentConfigManager.reset_instance()
        AgentManager.reset_instance()
        HealthReporter.reset_instance()
        
        db_manager = DatabaseManager.get_instance("sqlite:///test_exec.db")
        await db_manager.connect()
        
        config_manager = AgentConfigManager.get_instance(db_manager)
        await config_manager.initialize()
        
        test_config = AgentConfig(
            agent_config_id="cfg-exec-test-pkg-001",
            agent_id="exec-test-pkg-001",
            agent_type_id="uuid-echo-xxx",
            agent_type_name="echo_agent"
        )
        await config_manager.add_config(test_config)
        
        agent_manager = AgentManager.get_instance(config_manager, db_manager)
        health_reporter = HealthReporter.get_instance(agent_manager, db_manager, 60)
        
        yield {
            "db_manager": db_manager,
            "agent_manager": agent_manager
        }
        
        await health_reporter.stop()
        await agent_manager.stop_all_agents()
        await db_manager.disconnect()
        
        DatabaseManager._instance = None
        AgentConfigManager.reset_instance()
        AgentManager.reset_instance()
        HealthReporter.reset_instance()

    @pytest.mark.asyncio
    async def test_execute_agent_task(self, setup_execution_test):
        """测试执行Agent任务"""
        from src.api.router import execute_agent_task
        from src.models.schemas import AgentTaskRequest
        
        request = AgentTaskRequest(
            agent_id="exec-test-pkg-001",
            user_id="api-test-user",
            session_id="api-test-session",
            input={"query": "Hello from API test!"},
            timeout=60
        )
        
        response = await execute_agent_task(request)
        
        assert response.success is True
        assert response.agent_id == "exec-test-pkg-001"
        assert response.session_id == "api-test-session"
        assert response.output is not None
        assert "echo" in str(response.output).lower() or "Hello" in str(response.output)

    @pytest.mark.asyncio
    async def test_execute_task_creates_agent(self, setup_execution_test):
        """测试执行任务时自动创建Agent"""
        agent_manager = setup_execution_test["agent_manager"]
        
        # 确认Agent不存在
        assert agent_manager.has_agent("exec-test-pkg-001") is False
        
        from src.api.router import execute_agent_task
        from src.models.schemas import AgentTaskRequest
        
        request = AgentTaskRequest(
            agent_id="exec-test-pkg-001",
            user_id="api-test-user",
            input={"query": "Test auto create"}
        )
        
        response = await execute_agent_task(request)
        
        assert response.success is True
        # 现在Agent应该存在了
        assert agent_manager.has_agent("exec-test-pkg-001") is True


class TestAgentManagementAPI:
    """Agent管理API测试"""

    @pytest.fixture
    async def setup_management_api(self):
        """设置管理API测试环境"""
        DatabaseManager._instance = None
        AgentConfigManager.reset_instance()
        AgentManager.reset_instance()
        HealthReporter.reset_instance()
        
        db_manager = DatabaseManager.get_instance("sqlite:///test_mgmt_api.db")
        await db_manager.connect()
        
        config_manager = AgentConfigManager.get_instance(db_manager)
        await config_manager.initialize()
        
        test_config = AgentConfig(
            agent_config_id="cfg-mgmt-api-pkg-001",
            agent_id="mgmt-api-pkg-001",
            agent_type_id="uuid-echo-xxx",
            agent_type_name="echo_agent"
        )
        await config_manager.add_config(test_config)
        
        agent_manager = AgentManager.get_instance(config_manager, db_manager)
        health_reporter = HealthReporter.get_instance(agent_manager, db_manager, 60)
        
        yield {
            "agent_manager": agent_manager,
            "config_manager": config_manager,
            "db_manager": db_manager
        }
        
        await health_reporter.stop()
        await agent_manager.stop_all_agents()
        await db_manager.disconnect()
        
        DatabaseManager._instance = None
        AgentConfigManager.reset_instance()
        AgentManager.reset_instance()
        HealthReporter.reset_instance()

    @pytest.mark.asyncio
    async def test_get_agent_list(self, setup_management_api):
        """测试获取Agent列表"""
        agent_manager = setup_management_api["agent_manager"]
        
        # 先创建Agent
        await agent_manager.create_agent("mgmt-api-pkg-001")
        
        from src.api.router import get_agent_list
        
        agent_list = await get_agent_list()
        
        assert "mgmt-api-pkg-001" in agent_list

    @pytest.mark.asyncio
    async def test_stop_agent(self, setup_management_api):
        """测试停止Agent"""
        agent_manager = setup_management_api["agent_manager"]
        
        # 先创建Agent
        await agent_manager.create_agent("mgmt-api-pkg-001")
        assert agent_manager.has_agent("mgmt-api-pkg-001") is True
        
        from src.api.router import stop_agent
        
        result = await stop_agent("mgmt-api-pkg-001")
        
        assert result["success"] is True
        assert agent_manager.has_agent("mgmt-api-pkg-001") is False

    @pytest.mark.asyncio
    async def test_restart_agent(self, setup_management_api):
        """测试重启Agent"""
        agent_manager = setup_management_api["agent_manager"]
        
        # 先创建Agent
        agent1 = await agent_manager.create_agent("mgmt-api-pkg-001")
        original_start_time = agent1._start_time
        
        # 等待一小段时间
        await asyncio.sleep(0.1)
        
        from src.api.router import restart_agent
        
        result = await restart_agent("mgmt-api-pkg-001")
        
        assert result["success"] is True
        
        # 验证Agent已重启（启动时间更新）
        agent2 = await agent_manager.get_agent("mgmt-api-pkg-001")
        assert agent2._start_time > original_start_time


class TestServiceStatusAPI:
    """服务状态API测试"""

    @pytest.fixture
    async def setup_status_api(self):
        """设置状态API测试环境"""
        DatabaseManager._instance = None
        AgentConfigManager.reset_instance()
        AgentManager.reset_instance()
        HealthReporter.reset_instance()
        
        db_manager = DatabaseManager.get_instance("sqlite:///test_status_api.db")
        await db_manager.connect()
        
        config_manager = AgentConfigManager.get_instance(db_manager)
        await config_manager.initialize()
        
        agent_manager = AgentManager.get_instance(config_manager, db_manager)
        health_reporter = HealthReporter.get_instance(agent_manager, db_manager, 60)
        await health_reporter.start()
        
        yield {
            "agent_manager": agent_manager,
            "config_manager": config_manager,
            "health_reporter": health_reporter,
            "db_manager": db_manager
        }
        
        await health_reporter.stop()
        await agent_manager.stop_all_agents()
        await db_manager.disconnect()
        
        DatabaseManager._instance = None
        AgentConfigManager.reset_instance()
        AgentManager.reset_instance()
        HealthReporter.reset_instance()

    @pytest.mark.asyncio
    async def test_get_service_status(self, setup_status_api):
        """测试获取服务状态"""
        from src.api.router import get_service_status
        
        status = await get_service_status()
        
        assert status["status"] == "running"
        assert "agent_count" in status
        assert "config_count" in status
        assert status["health_reporter_running"] is True
        assert status["database_connected"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
