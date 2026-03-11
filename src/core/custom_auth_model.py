import os
from typing import Optional
from loguru import logger

# 引入基类和工具类
from openjiuwen.core.foundation.llm.model_clients.openai_model_client import OpenAIModelClient
from openjiuwen.core.foundation.llm.schema.config import ModelRequestConfig, ModelClientConfig
from src.config import get_settings

class CustomAuthModel(OpenAIModelClient):
    """
    自定义鉴权模型，支持传递 user_id
    """
    def __init__(self, model_config: ModelRequestConfig, model_client_config: ModelClientConfig):
        if model_config is None:
            model_config = ModelRequestConfig(model="")
        super().__init__(model_config, model_client_config)
        # user_id 可以从 model_client_config 的额外属性中获取
        self.user_id = getattr(model_client_config, "user_id", None)
        if not self.user_id and hasattr(model_client_config, "model_extra") and model_client_config.model_extra:
            self.user_id = model_client_config.model_extra.get("user_id")
        logger.debug(f"CustomAuthModel init: user_id={self.user_id}")

    def _create_async_openai_client(self, timeout: Optional[float] = None):
        """重写以注入自定义 headers"""
        from openai import AsyncOpenAI
        from openjiuwen.core.common.security.ssl_utils import SslUtils
        from openjiuwen.core.common.security.url_utils import UrlUtils
        import httpx
        
        settings = get_settings()
        
        ssl_verify, ssl_cert = self.model_client_config.verify_ssl, self.model_client_config.ssl_cert
        verify = SslUtils.create_strict_ssl_context(ssl_cert) if ssl_verify else ssl_verify

        model_extra = self.model_client_config.model_extra or {}
        disable_proxy = bool(model_extra.get("disable_proxy", settings.llm_disable_proxy))
        no_proxy_value = model_extra.get("no_proxy") or settings.llm_no_proxy

        if no_proxy_value:
            existing_no_proxy = os.getenv("NO_PROXY", "")
            merged_items = []
            seen = set()
            for raw in (existing_no_proxy, str(no_proxy_value)):
                for item in raw.replace(";", ",").replace(" ", ",").split(","):
                    host = item.strip()
                    if not host:
                        continue
                    host_lower = host.lower()
                    if host_lower not in seen:
                        seen.add(host_lower)
                        merged_items.append(host)
            os.environ["NO_PROXY"] = ",".join(merged_items)

        proxy_url = None if disable_proxy else UrlUtils.get_global_proxy_url(self.model_client_config.api_base)
        logger.debug(f"CustomAuthModel proxy config: disable_proxy={disable_proxy}, proxy_url={proxy_url}")

        http_client = httpx.AsyncClient(
            proxy=proxy_url,
            verify=verify
        )

        final_timeout = timeout if timeout is not None else self.model_client_config.timeout

        default_headers = {}
        if self.user_id:
            default_headers["User-Id"] = str(self.user_id)

        return AsyncOpenAI(
            api_key=self.model_client_config.api_key,
            base_url=self.model_client_config.api_base,
            http_client=http_client,
            timeout=final_timeout,
            max_retries=self.model_client_config.max_retries,
            default_headers=default_headers if default_headers else None
        )