import json
from typing import Dict, List, Any

from jinja2 import Template
from loguru import logger
from openjiuwen.core.foundation.llm.model import Model
from openjiuwen.core.foundation.llm.schema.config import ModelClientConfig

from src.core.base import AgentRegistry, BaseAgent


@AgentRegistry.register("risk-assistant")
class RiskAssistantAgent(BaseAgent):
    def __init__(self, config: str):
        super().__init__(config)
        config_data = json.loads(config)

        model_config = config_data.get("model_config", {}).get("risk_assistant_model", {})
        self.api_base = model_config.get("base_url")
        self.api_key = model_config.get("api_key")
        self.model_provider = model_config.get("model_provider", "openai")
        self.model_name = model_config.get("model_name", "gpt-4o-mini")

        prompt_configs = config_data.get("prompt_config", {})
        self.system_prompt_template = (
            prompt_configs.get("system_prompt_template", {}).get("prompt_content")
            or "你是一位风控助手，请结合历史报告简洁回答问题。"
        )
        self.user_prompt_template = (
            prompt_configs.get("user_prompt_template", {}).get("prompt_content")
            or "历史信息：{{user_prompt_report}}\n当前问题：{{user_prompt_question}}"
        )

        client_config = ModelClientConfig(
            client_provider=self.model_provider,
            api_key=self.api_key or "dummy",
            api_base=self.api_base or "http://dummy",
            verify_ssl=False,
        )
        self._model = Model(model_client_config=client_config)

    async def invoke(self, input_data: Dict[str, Any], history: List[Dict] = None):
        output_messages = [input_data]

        user_prompt_question = input_data.get("content") or input_data.get("query") or ""
        user_prompt_report = json.dumps(history or [], ensure_ascii=False)
        user_prompt_content = Template(self.user_prompt_template).render(
            user_prompt_question=user_prompt_question,
            user_prompt_report=user_prompt_report,
        )

        messages = [
            {"role": "system", "content": self.system_prompt_template},
            {"role": "user", "content": user_prompt_content},
        ]

        try:
            result = await self._model.invoke(model=self.model_name, messages=messages)
            content = result.content
        except Exception as e:
            logger.error(f"RiskAssistantAgent 调用模型失败: {e}")
            content = f"模型调用失败: {e}"

        output_messages.append({"role": "risk_assistant_agent", "content": content})
        return output_messages
