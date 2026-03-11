"""
Userid Agent Implementation for testing CustomAuthModel
"""

from typing import Any, Dict, List

from loguru import logger
from openjiuwen.core.foundation.llm.model import Model
from openjiuwen.core.foundation.llm.schema.config import ModelClientConfig, ModelRequestConfig
from src.core.base import BaseAgent, AgentRegistry
from src.config import get_settings

@AgentRegistry.register("userid_agent")
class UseridAgent(BaseAgent):
    """
    Userid Agent 用于测试 userid 鉴权
    """

    def __init__(self, config: str):
        logger.debug(f"UseridAgent 初始化 config: {config}")
        super().__init__(config)
        self._load_config(config)

    def _load_config(self, config_str: str):
        """解析配置"""
        import json
        try:
            config = json.loads(config_str)
            self.config_data = config
            
            # 解析模型配置
            # 假设配置结构: {"model_config": {"userid_main_model": {"model_provider": "userid", "api_key": "...", ...}}}
            model_conf_map = config.get("model_config", {})
            # 取第一个或者指定名称的模型
            self.model_config = model_conf_map.get("userid_main_model") or next(iter(model_conf_map.values()), {})
            
        except Exception as e:
            logger.error(f"UseridAgent 加载配置失败: {e}")
            self.model_config = {}

    async def invoke(
        self,
        input_data: Dict[str, Any],
        history: List[Dict] = None
    ) -> Any:
        """
        执行任务，使用 CustomAuthModel 调用 LLM
        """
        logger.debug(f"UseridAgent invoke 入参 input_data: {input_data}, history: {history}")
        logger.info(f"UseridAgent 执行任务 model_config: {self.model_config}")
        
     
        query = input_data.get("query", input_data)
        if isinstance(query, dict):
            content = query.get("content", str(query))
        else:
            content = str(query)

        try:
            # 构造消息
            messages = [{"role": "user", "content": content}]
            
            # Extract basic params
            model_provider = self.model_config.get("model_provider", "userid")
            user_id = self.model_config.get("user_id")
            api_key = self.model_config.get("auth_token") or self.model_config.get("api_key")
            api_base = self.model_config.get("base_url")
            model_name = self.model_config.get("model_name", "gpt-3.5-turbo")

            logger.info(f"UseridAgent 构建模型参数: model_provider={model_provider}, user_id={user_id}, api_key={api_key}, api_base={api_base}")

            # 准备额外的参数，过滤掉数据库元数据字段，避免污染请求体导致 401
            # 常见不需要传给 LLM 的字段
            exclude_keys = {
                "model_provider", "api_key", "base_url", "user_id", 
                "id", "create_time", "update_time", "auth_method", "auth_token",
                "model_name", "model_config_id"
            }
            
            extra_kwargs = {
                k: v for k, v in self.model_config.items() 
                if k not in exclude_keys
            }
            logger.debug(f"UseridAgent 额外透传参数: {extra_kwargs}")

            settings = get_settings()
            verify_ssl = self.model_config.get("verify_ssl", settings.llm_ssl_verify)
            ssl_cert = self.model_config.get("ssl_cert") or settings.llm_ssl_cert
            disable_proxy = self.model_config.get("disable_proxy", settings.llm_disable_proxy)
            no_proxy = self.model_config.get("no_proxy") or settings.llm_no_proxy

            # 获取模型实例
            client_config = ModelClientConfig(
                client_provider=model_provider,
                api_key=api_key or "dummy",
                api_base=api_base or "http://dummy",
                user_id=user_id,
                verify_ssl=verify_ssl,
                ssl_cert=ssl_cert,
                disable_proxy=disable_proxy,
                no_proxy=no_proxy,
            )
            request_config = ModelRequestConfig(model=model_name)
            model = Model(model_client_config=client_config, model_config=request_config)
            
            # 调用模型
            response = await model.invoke(
                model=model_name,
                messages=messages
            )
            
            result_content = response.content
            
        except Exception as e:
            error_text = str(e)
            if "HIS Proxy Notification" in error_text or "<!DOCTYPE html" in error_text:
                friendly_error = (
                    "模型网关返回了企业代理拦截页面，请检查 model_config.base_url 是否可达，"
                    "并为该域名配置 no_proxy（或将 disable_proxy=true）。"
                )
                logger.error(f"UseridAgent 模型调用失败（代理拦截）: {friendly_error}; raw={error_text}")
                raise RuntimeError(friendly_error) from e

            logger.error(f"UseridAgent 模型调用失败: {error_text}")
            raise RuntimeError(error_text) from e

        return {
            "role": "assistant",
            "content": f"Userid Agent Processed: {result_content}"
        }

    async def execute(self, user_id: str, session_id: str, input_data: Dict[str, Any], timeout: int = 300):
        """
        实现 BaseAgent 隐式要求的 execute 方法，支持流式调用的默认回退
        """
        # 手动注入 user_id 到 input_data，以便复用 invoke
        input_with_user = input_data.copy()
        if "user_id" not in input_with_user:
            input_with_user["user_id"] = user_id
            
        return await self.invoke(input_with_user)
