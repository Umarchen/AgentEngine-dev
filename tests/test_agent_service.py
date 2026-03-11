"""
Agent Engine Service 测试用例
"""

import pytest
import asyncio
from datetime import datetime

from src.models.schemas import (
    AgentConfig,
    AgentTaskRequest,
    AgentHealthStatus,
    AgentTrajectory,
    TrajectoryStep,
    Trajectory,
)
from src.database.database import DatabaseManager
from src.core.base import AgentRegistry
from src.core.config_manager import AgentConfigManager
from src.core.agent_manager import AgentManager

# 导入 agents 模块以触发 Agent 类的注册
import src.agents


# ==================== 数据模型测试 ====================

class TestSchemas:
    """数据模型测试"""
        
    def test_agent_task_request(self):
        """测试 AgentTaskRequest 模型"""
        request = AgentTaskRequest(
            agent_id="test-package-001",
            user_id="user-001",
            session_id="session-001",
            input={"query": "测试输入"},
            timeout=60
        )
        
        assert request.agent_id == "test-package-001"
        assert request.user_id == "user-001"
        assert request.timeout == 60
    

# ==================== 数据库模块测试 ====================

class TestDatabaseManager:
    """数据库管理器测试"""
    
    @pytest.fixture
    def db_manager(self):
        """创建数据库管理器实例"""
        return DatabaseManager("sqlite:///test_agent_engine.db")
    
    @pytest.mark.asyncio
    async def test_connect_disconnect(self, db_manager):
        """测试连接和断开"""
        # 连接
        result = await db_manager.connect()
        assert result is True
        assert db_manager.is_connected is True
        await db_manager.disconnect()
        assert db_manager.is_connected is False
    
    @pytest.mark.asyncio
    async def test_save_and_get_config(self, db_manager):
        """测试保存和获取配置"""
        await db_manager.connect()
        
        config = AgentConfig(
            agent_config_id="cfg-test-package-002",
            agent_id="test-package-002",
            agent_type_id="test",
            agent_type_name="Test Agent"
        )
        
        # 保存配置
        result = await db_manager.save_agent_config(config)
        assert result is True
        
        # 获取配置
        retrieved = await db_manager.get_agent_config("test-package-002")
        assert retrieved is not None
        assert retrieved.agent_id == "test-package-002"
        
        await db_manager.disconnect()


# ==================== Agent 基类测试 ====================

class TestBaseAgent:
    """Agent 基类测试"""
    
    @pytest.fixture
    def config(self):
        """创建测试配置"""
        return AgentConfig(
            agent_config_id="cfg-test-package-003",
            agent_id="test-package-003",
            agent_type_id="echo",
            agent_type_name="echo_agent"
        )
    
    def test_agent_registry_register(self, config):
        """测试 Agent 注册"""
        # 检查 echo 类型是否已注册
        agent_class = AgentRegistry.get("echo_agent")
        assert agent_class is not None
    
    def test_agent_registry_not_found(self):
        """测试获取不存在的 Agent 类型"""
        agent_class = AgentRegistry.get("non-existent-type")
        assert agent_class is None


# ==================== 配置管理器测试 ====================

class TestConfigManager:
    """配置管理器测试"""
    
    @pytest.fixture
    def config_manager(self):
        """创建配置管理器实例"""
        db_manager = DatabaseManager()
        return AgentConfigManager(db_manager)
    
    @pytest.mark.asyncio
    async def test_add_and_get_config(self, config_manager):
        """测试添加和获取配置"""
        config = AgentConfig(
            agent_config_id="cfg-test-package-004",
            agent_id="test-package-004",
            agent_type_id="echo",
            agent_type_name="echo_agent"
        )
        
        # 添加配置
        result = await config_manager.add_config(config)
        assert result is True
        
        # 检查是否存在
        assert config_manager.has_config("test-package-004")
        
        # 获取配置
        retrieved = await config_manager.get_config("test-package-004")
        assert retrieved is not None
        assert retrieved.agent_type_name == "echo_agent"


# ==================== Agent 管理器测试 ====================

class TestAgentManager:
    """Agent 管理器测试"""
    
    @pytest.fixture
    async def agent_manager(self):
        """创建 Agent 管理器实例"""
        db_manager = DatabaseManager()
        await db_manager.connect()
        
        config_manager = AgentConfigManager(db_manager)
        
        # 添加测试配置
        config = AgentConfig(
            agent_config_id="cfg-test-package-005",
            agent_id="test-package-005",
            agent_type_id="echo",
            agent_type_name="echo_agent"
        )
        await config_manager.add_config(config)
        
        return AgentManager(config_manager, db_manager)
    
    @pytest.mark.asyncio
    async def test_create_agent(self, agent_manager):
        """测试创建 Agent"""
        agent = await agent_manager.create_agent("test-package-005")
        
        assert agent is not None
    
    @pytest.mark.asyncio
    async def test_execute_task(self, agent_manager):
        """测试执行任务"""
        request = AgentTaskRequest(
            agent_id="test-package-005",
            user_id="test-user",
            input={"query": "Hello, Agent!"}
        )
        
        response = await agent_manager.execute_task(request)
        
        assert response.success is True
        assert response.agent_id == "test-package-005"
        assert response.output is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
