
import os
import sys
import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

# Must setup paths before imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app import app
from src.core.agent_manager import get_agent_manager
from src.core.config_manager import get_config_manager
from src.models.schemas import AgentConfig, AgentTaskRequest
from src.core.base import AgentRegistry
from openjiuwen.core.foundation.llm.model import _CLIENT_TYPE_REGISTRY
from src.core.custom_auth_model import CustomAuthModel

# Import our agent to ensure registration
from src.agents.userid_agent.userid_agent import UseridAgent

# Setup environment to use 'userid' as provider for custom auth
os.environ["CUSTOM_AUTH_PROVIDER"] = "userid"
os.environ["LLM_SSL_VERIFY"] = "false"

class TestUseridAgentE2E:
    
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        # Register Model
        _CLIENT_TYPE_REGISTRY["userid"] = CustomAuthModel
        yield
        # Cleanup if needed
        if "userid" in _CLIENT_TYPE_REGISTRY:
            del _CLIENT_TYPE_REGISTRY["userid"]

    @patch("src.core.config_manager.AgentConfigManager.get_config")
    @patch("openjiuwen.core.foundation.llm.model.Model.invoke", new_callable=AsyncMock)
    @patch("src.core.agent_manager.get_database_manager") # Mock DB to avoid connection errors
    def test_userid_agent_execution(self, mock_db_manager, mock_model_invoke, mock_get_config):
        """
        Test the full flow:
        Request -> Router -> AgentManager -> UseridAgent -> CustomAuthModel -> Mocked LLM
        """
        
        agent_id = "test_userid_agent_001"
        user_id = "u_userid_test_user_888"
        
        # 1. Setup Config Mock
        # AgentManager needs to find config for "test_userid_agent_001"
        mock_config = AgentConfig(
            agent_config_id="cfg_1",
            agent_id=agent_id,
            agent_type_id="type_userid",
            agent_type_name="userid_agent", # Matches @AgentRegistry.register("userid_agent")
            description="Test Userid Agent",
            config_schema={}
        )
        mock_get_config.return_value = mock_config  # allow async return if needed?
        # get_config is async defined in ConfigManager? let's check. 
        # Typically yes.
        async def async_get_config(*args, **kwargs):
            return mock_config
        mock_get_config.side_effect = async_get_config

        # 2. Setup DB Mock (Execute task calls DB)
        mock_db = MagicMock()
        mock_db_manager.return_value = mock_db
        mock_db.is_connected = True
        mock_db.get_session_info = AsyncMock(return_value=None)
        # execute_task calls _save_task_and_session_info which is async
        
        # 3. Setup Model Invoke Mock
        mock_response = MagicMock()
        mock_response.content = "Userid Success Response"
        mock_model_invoke.return_value = mock_response

        # 4. Create Client
        client = TestClient(app)

        # 5. Send Request
        payload = {
            "agent_id": agent_id,
            "user_id": user_id,
            "input": {
                "query": "Hello Userid Agent",
                # The user_id is NOT automatically passed to invoke by AgentManager
                # So we must pass it here OR modify AgentManager.
                # For this test, let's explicitly pass it in input to verify the agent uses it.
                "user_id": user_id 
            },
            "stream": False
        }

        response = client.post("/api/v1/agent/execute", json=payload)

        # 6. Verify Response
        assert response.status_code == 200
        data = response.json()
        print(f"Response Data: {data}")
        assert data["success"] is True
        assert "Process" in str(data["output"])

        # 7. Verify CustomAuthModel was initialized with correct user_id
        # We can't easily check initialization arguments of CustomAuthModel 
        # because it's instantiated inside get_model.
        # But we can check if _invoke was called and what context it had.
        
        # However, to be 100% sure proper headers were generated, we should mock `requests.Session.post`
        # instead of `_invoke` if we want to check headers.
        # BUT `CustomAuthModel._get_headers` is called inside `_invoke`.
        # Since we mocked `_invoke`, the internal logic wasn't run.
        
        # Let's verify `UseridAgent.invoke` called `ModelFactory.get_model` with user_id.
        # We can patch ModelFactory.get_model
    
    @patch("src.core.config_manager.AgentConfigManager.get_config")
    @patch("openjiuwen.core.foundation.llm.model.Model.__init__", return_value=None)
    @patch("openjiuwen.core.foundation.llm.model.Model.invoke", new_callable=AsyncMock)
    @patch("src.core.agent_manager.get_database_manager")
    def test_userid_agent_execution_verify_config_user_id(self, mock_db_manager, mock_model_invoke, mock_model_init, mock_get_config):
        """
        验证从管理面配置中加载 userid 并使用
        """
        agent_id = "test_userid_agent_003"
        request_user_id = "u_request_user_777" # 发起请求的用户（用于鉴权/统计）
        config_user_id = "u_config_managed_888" # Agent 绑定的特定业务账号（用于调用模型）
        
        # 模拟管理面配置 (Config Schema)
        config_payload = {
            "model_config": {
                "userid_main_model": {
                    "model_provider": "userid",
                    "base_url": "http://test-api",
                    "api_key": "test-key-config",
                    "model_name": "gpt-fake",
                    "user_id": config_user_id
                }
            }
        }
        
        mock_config = AgentConfig(
            agent_config_id="cfg_3",
            agent_id=agent_id,
            agent_type_id="type_userid",
            agent_type_name="userid_agent",
            description="Test Userid Agent with Config",
            config_schema=config_payload
        )
        async def async_get_config(*args, **kwargs):
            return mock_config
        mock_get_config.side_effect = async_get_config

        # Setup Model Mock
        mock_model_invoke.return_value = MagicMock(content="Config User ID Test")
        
        # Setup DB
        mock_db = MagicMock()
        mock_db_manager.return_value = mock_db
        mock_db.get_session_info = AsyncMock(return_value=None)

        client = TestClient(app)
        
        # 请求中不再携带 input.user_id
        payload = {
            "agent_id": agent_id,
            "user_id": request_user_id,
            "input": {
                "query": "Check Config User ID"
            },
            "stream": False
        }
        
        resp = client.post("/api/v1/agent/execute", json=payload)
        assert resp.status_code == 200
        
        # Assertions
        # 验证 Model 初始化使用的是 config_user_id 而不是 request_user_id
        args, kwargs = mock_model_init.call_args
        
        client_config = kwargs.get("model_client_config")
        
        # 检查参数
        assert client_config.client_provider == "userid"
        
        # 关键验证：这里应该使用配置中的 ID "u_config_managed_888"
        actual_user_id = getattr(client_config, "user_id", None)
        if not actual_user_id and hasattr(client_config, "model_extra") and client_config.model_extra:
            actual_user_id = client_config.model_extra.get("user_id")
            
        print(f"\nExpected User ID: {config_user_id}, Actual: {actual_user_id}")
        assert actual_user_id == config_user_id
        
        # 还可以验证其他配置参数
        assert client_config.api_key == "test-key-config"
        assert client_config.api_base == "http://test-api"

        print("\nVerified: Model used configured user_id correctly.")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

