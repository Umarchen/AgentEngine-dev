"""
LLM 客户端封装
支持多种 LLM 提供商：模型网关、OpenAI、DeepSeek、Qwen、Gemini 等
"""

import json
import os
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod

import httpx
from loguru import logger

from src.models.evaluation_schemas import LLMConfig


class BaseLLMClient(ABC):
    """LLM 客户端基类"""
    
    def __init__(self, config: LLMConfig):
        """
        初始化 LLM 客户端
        
        Args:
            config: LLM 配置
        """
        self.config = config
    
    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> str:
        """
        调用 LLM 进行对话补全
        
        Args:
            messages: 消息列表，格式: [{"role": "system/user/assistant", "content": "..."}]
            **kwargs: 其他参数
            
        Returns:
            LLM 返回的文本内容
        """
        pass


class OpenAICompatibleClient(BaseLLMClient):
    """
    OpenAI 兼容的客户端
    支持 OpenAI、DeepSeek、Qwen 等使用 OpenAI API 格式的模型
    """
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> str:
        """调用 OpenAI 兼容的 API"""
        try:
            # 构建请求头
            headers = {
                "Content-Type": "application/json",
            }
            
            # 只在 API Key 存在且非空时添加 Authorization header
            if self.config.api_key and self.config.api_key.strip():
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            
            payload = {
                "model": self.config.model_name,
                "messages": messages,
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            }
            
            # 发送请求
            # 对内网地址自动禁用代理
            proxies = None
            trust_env = True  # 默认信任环境变量（允许使用代理）
            
            # 检查是否是内网地址（100.x.x.x 或 192.168.x.x 或 10.x.x.x）
            import re
            if re.match(r'https?://(100\.|192\.168\.|10\.)', self.config.api_base):
                # 内网地址：禁用代理
                proxies = {}  # 空字典表示不使用任何代理
                trust_env = False  # 不信任环境变量中的代理设置
                logger.info(f"检测到内网地址，禁用代理: {self.config.api_base}")
            
            # 或者通过环境变量强制禁用
            if os.getenv("EVALUATION_NO_PROXY", "false").lower() == "true":
                proxies = {}
                trust_env = False
                logger.info("通过环境变量强制禁用代理")
            
            # 创建客户端
            async with httpx.AsyncClient(
                timeout=self.config.timeout, 
                #proxies=proxies,
                trust_env=trust_env  # 根据地址类型决定是否信任环境变量
            ) as client:
                # 如果 api_base 已经包含完整路径，直接使用；否则添加 /chat/completions
                if self.config.api_base.endswith('/chat/completions'):
                    url = self.config.api_base
                else:
                    url = f"{self.config.api_base}/chat/completions"
                
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload
                )
                
                response.raise_for_status()
                
                result = response.json()
                
                # 检查响应格式
                if "choices" not in result:
                    logger.error(f"响应中没有 choices 字段: {result}")
                    raise Exception(f"API 响应格式错误: 缺少 choices 字段")
                
                if not result["choices"]:
                    logger.error(f"choices 数组为空: {result}")
                    raise Exception(f"API 响应格式错误: choices 数组为空")
                
                if "message" not in result["choices"][0]:
                    logger.error(f"choices[0] 中没有 message 字段: {result['choices'][0]}")
                    raise Exception(f"API 响应格式错误: 缺少 message 字段")
                
                if "content" not in result["choices"][0]["message"]:
                    logger.error(f"message 中没有 content 字段: {result['choices'][0]['message']}")
                    raise Exception(f"API 响应格式错误: 缺少 content 字段")
                
                content = result["choices"][0]["message"]["content"]
                
                return content
                
        except httpx.ConnectError as e:
            logger.error(f"LLM 服务连接失败: {self.config.api_base}")
            logger.error(f"请检查: 1) 服务是否启动 2) 地址是否正确 3) 网络是否通畅")
            raise Exception(f"LLM 服务连接失败: {self.config.api_base}")
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API 请求失败: {e.response.status_code} - {e.response.text}")
            raise Exception(f"LLM API 请求失败: {e.response.status_code}")
        except httpx.TimeoutException as e:
            logger.error(f"LLM API 请求超时: {self.config.timeout}秒")
            raise Exception(f"LLM API 请求超时")
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            raise


class GatewayClient(BaseLLMClient):
    """
    模型网关客户端
    根据实际网关 API 格式进行调整
    """
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> str:
        """调用模型网关 API"""
        try:
            # 这里根据实际的网关 API 格式进行调整
            # 示例：假设网关使用类似 OpenAI 的格式
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}"
            }
            
            payload = {
                "model": self.config.model_name,
                "messages": messages,
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            }
            
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(
                    f"{self.config.api_base}/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                
                result = response.json()
                # 根据实际网关响应格式解析
                content = result["choices"][0]["message"]["content"]
                
                return content
                
        except Exception as e:
            logger.error(f"网关 LLM 调用失败: {e}")
            raise


class GeminiClient(BaseLLMClient):
    """
    Google Gemini 客户端
    """
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> str:
        """调用 Gemini API"""
        try:
            # Gemini API 格式
            api_base = self.config.api_base or "https://generativelanguage.googleapis.com/v1beta"
            
            # 转换消息格式
            contents = []
            for msg in messages:
                role = "user" if msg["role"] in ["user", "system"] else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}]
                })
            
            payload = {
                "contents": contents,
                "generationConfig": {
                    "temperature": kwargs.get("temperature", self.config.temperature),
                    "maxOutputTokens": kwargs.get("max_tokens", self.config.max_tokens),
                }
            }
            
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(
                    f"{api_base}/models/{self.config.model_name}:generateContent?key={self.config.api_key}",
                    json=payload
                )
                response.raise_for_status()
                
                result = response.json()
                content = result["candidates"][0]["content"]["parts"][0]["text"]
                
                return content
                
        except Exception as e:
            logger.error(f"Gemini 调用失败: {e}")
            raise


class LLMClientFactory:
    """LLM 客户端工厂"""
    
    @staticmethod
    def create_client(config: LLMConfig) -> BaseLLMClient:
        """
        根据配置创建对应的 LLM 客户端
        
        Args:
            config: LLM 配置
            
        Returns:
            LLM 客户端实例
        """
        provider = config.provider.lower()
        
        if provider == "gateway":
            return GatewayClient(config)
        elif provider in ["openai", "deepseek", "qwen"]:
            return OpenAICompatibleClient(config)
        elif provider == "gemini":
            return GeminiClient(config)
        else:
            raise ValueError(f"不支持的 LLM 提供商: {provider}")


def load_llm_config_from_yaml(config_path: str = "config/evaluation_config.yaml") -> LLMConfig:
    """
    从 YAML 配置文件加载 LLM 配置
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        LLM 配置对象
    """
    import yaml
    from pathlib import Path
    
    try:
        # 支持相对路径
        if not os.path.isabs(config_path):
            project_root = Path(__file__).parent.parent.parent.parent
            config_file = project_root / config_path
        else:
            config_file = Path(config_path)
        
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        
        llm_config = config_data.get("llm", {})
        
        # 处理环境变量
        api_key = llm_config.get("api_key", "")
        if api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            api_key = os.getenv(env_var, "")
        
        return LLMConfig(
            provider=llm_config.get("provider", "deepseek"),
            model_name=llm_config.get("model_name", "deepseek-chat"),
            api_key=api_key,
            api_base=llm_config.get("api_base"),
            temperature=llm_config.get("temperature", 0.7),
            max_tokens=llm_config.get("max_tokens", 2000),
            timeout=llm_config.get("timeout", 60)
        )
        
    except Exception as e:
        logger.error(f"加载 LLM 配置失败: {e}")
        # 返回默认配置
        return LLMConfig(
            provider="deepseek",
            model_name="deepseek-chat",
            api_key=os.getenv("EVALUATION_LLM_API_KEY", ""),
            api_base="https://api.deepseek.com/v1",
            temperature=0.7,
            max_tokens=2000,
            timeout=60
        )
