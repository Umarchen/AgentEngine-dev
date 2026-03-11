import json
from typing import Dict, List, Any

from jinja2 import Template
from loguru import logger
from openjiuwen.core.foundation.llm.model import Model
from openjiuwen.core.foundation.llm.schema.config import ModelClientConfig

from src.core.base import AgentRegistry, BaseAgent


def _normalize_prompt_config(prompt_config: Any) -> Dict[str, str]:
    if isinstance(prompt_config, dict):
        return {
            key: (value.get("prompt_content") if isinstance(value, dict) else str(value))
            for key, value in prompt_config.items()
        }
    if isinstance(prompt_config, list):
        out: Dict[str, str] = {}
        for item in prompt_config:
            name = item.get("name") if isinstance(item, dict) else None
            if not name:
                continue
            out[name] = item.get("default") or item.get("prompt_content") or ""
        return out
    return {}


@AgentRegistry.register("risk_ctrl_agent")
class RiskCtrlAgent(BaseAgent):
    def __init__(self, config: str):
        super().__init__(config)
        config_dict = json.loads(config)

        model_conf_map = config_dict.get("model_config", {})
        if isinstance(model_conf_map, list):
            first_conf = model_conf_map[0] if model_conf_map else {}
            self.model_provider = first_conf.get("model_provider") or "openai"
            self.api_key = first_conf.get("api_key")
            self.api_base = first_conf.get("base_url")
            self.model_name = first_conf.get("model_name") or "gpt-4o-mini"
        else:
            risk_model = model_conf_map.get("risk_control_model", {})
            self.model_provider = risk_model.get("model_provider") or "openai"
            self.api_key = risk_model.get("api_key")
            self.api_base = risk_model.get("base_url")
            self.model_name = risk_model.get("model_name") or "gpt-4o-mini"

        prompt_map = _normalize_prompt_config(config_dict.get("prompt_config"))
        self.system_prompt = prompt_map.get("system") or "你是一位资深风控审批官，请给出风险评估结论。"
        self.inspector_prompt = (
            prompt_map.get("inspector")
            or "请基于输入的贷款档案信息进行风险评估，输出结构化结论。"
        )
        self.manager_prompt = prompt_map.get("manager") or "【补充信息】{{补充信息}}"

        client_config = ModelClientConfig(
            client_provider=self.model_provider,
            api_key=self.api_key or "dummy",
            api_base=self.api_base or "http://dummy",
            verify_ssl=False,
        )
        self._model = Model(model_client_config=client_config)

    async def invoke(self, input_data: Dict[str, Any], history: List[Dict] = None):
        history = history or []
        output_messages: List[Dict[str, str]] = []

        role = input_data.get("role")
        content = input_data.get("content") or input_data.get("query") or ""

        messages: List[Dict[str, str]] = [{"role": "system", "content": self.system_prompt}]
        for message in history:
            msg_role = message.get("role", "user")
            msg_content = message.get("content", "")
            if msg_role == "risk control agent":
                messages.append({"role": "assistant", "content": msg_content})
            else:
                messages.append({"role": "user", "content": msg_content})

        if role == "manager":
            manager_input = Template(self.manager_prompt).render({"补充信息": content})
            messages.append({"role": "user", "content": manager_input})
            output_messages.append({"role": "manager", "content": content})
        else:
            inspector_input = Template(self.inspector_prompt).render({"贷款信息": content, "query": content})
            messages.append({"role": "user", "content": inspector_input})
            output_messages.append({"role": "inspector", "content": content})

        try:
            result = await self._model.invoke(model=self.model_name, messages=messages)
            reply = result.content
        except Exception as e:
            logger.error(f"RiskCtrlAgent 调用模型失败: {e}")
            reply = f"模型调用失败: {e}"

        output_messages.append({"role": "risk control agent", "content": reply})
        return output_messages
