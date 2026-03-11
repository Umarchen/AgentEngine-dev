import os
import sys
import unittest
import asyncio
from typing import cast
from unittest.mock import MagicMock, patch, AsyncMock

# 设置 SSL 验证环境变变，避免测试环境报错
os.environ["LLM_SSL_VERIFY"] = "false"

# 添加项目根目录到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openjiuwen.core.foundation.llm.model import _CLIENT_TYPE_REGISTRY, Model
from openjiuwen.core.foundation.llm.schema.config import ModelClientConfig, ModelRequestConfig
from src.core.custom_auth_model import CustomAuthModel
from openjiuwen.core.foundation.llm.schema.message import AssistantMessage
from openjiuwen.core.foundation.llm.schema.message_chunk import AssistantMessageChunk

class TestCustomAuthModel(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        """注册模型"""
        _CLIENT_TYPE_REGISTRY["userid"] = CustomAuthModel
        print("Model registered: userid -> CustomAuthModel")

    @classmethod
    def tearDownClass(cls):
        """清理注册的模型 (可选)"""
        if "userid" in _CLIENT_TYPE_REGISTRY:
            del _CLIENT_TYPE_REGISTRY["userid"]

    def test_initialization_and_headers(self):
        """测试初始化和 Header 生成"""
        api_key = "test_key"
        api_base = "http://test.api"
        user_id = "u_123"
        
        client_config = ModelClientConfig(
            client_provider="userid",
            api_key=api_key,
            api_base=api_base,
            user_id=user_id,
            verify_ssl=False
        )
        
        model = Model(model_client_config=client_config)
        
        self.assertIsInstance(model._client, CustomAuthModel)
        self.assertEqual(model._client.user_id, user_id)
        
        async_client = model._client._create_async_openai_client()
        self.assertEqual(async_client.default_headers["User-Id"], user_id)
        self.assertEqual(async_client.api_key, api_key)
        print("Initialization and Headers check passed.")


if __name__ == "__main__":
    unittest.main()

