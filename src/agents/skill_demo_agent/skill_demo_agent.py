"""Skill Demo Agent.

能力：
1. 调用 src/skills 下的样例 skill；
2. 按 openjiuwen ``tools + tool_calls`` 形式完成 skill 选择与调用。
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from openjiuwen.core.foundation.llm.model import Model
from openjiuwen.core.foundation.llm.schema.config import ModelClientConfig

from src.core.base import AgentRegistry, BaseAgent
from src.skills.skillmgr import get_skill_manager
from src.skills.web_calc_skill import summarize_numbers


@AgentRegistry.register("skill_demo_agent")
class SkillDemoAgent(BaseAgent):
    def __init__(self, config: str):
        super().__init__(config)
        self.config_data = self._load_config(config)
        self.model_config = self._extract_model_config(self.config_data)
        self.model_name = self.model_config.get("model_name", "gpt-4o-mini")
        self._model = self._build_model()

        self.skill_manager = get_skill_manager()
        self.skill_manager.register_builtin_skill(
            name="web_calc_skill",
            handler=self._run_web_calc_skill,
            description="对 numbers 做汇总统计（count/sum/mean/min/max）",
            input_schema={
                "type": "object",
                "properties": {
                    "numbers": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "需要计算的一组数字",
                    }
                },
                "required": ["numbers"],
            },
        )

    @staticmethod
    def _load_config(config_str: str) -> Dict[str, Any]:
        try:
            payload = json.loads(config_str or "{}")
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _extract_model_config(config_data: Dict[str, Any]) -> Dict[str, Any]:
        model_conf_map = config_data.get("model_config", {})
        if isinstance(model_conf_map, list):
            return model_conf_map[0] if model_conf_map else {}
        if isinstance(model_conf_map, dict):
            return (
                model_conf_map.get("skill_demo_model")
                or model_conf_map.get("main_model")
                or next(iter(model_conf_map.values()), {})
            )
        return {}

    def _build_model(self) -> Optional[Model]:
        api_key = self.model_config.get("auth_token") or self.model_config.get("api_key")
        api_base = self.model_config.get("base_url")
        provider = self._normalize_model_provider(self.model_config.get("model_provider", "openai"))

        if not api_key and not api_base:
            logger.warning("SkillDemoAgent 未配置模型，LLM 路由能力不可用")
            return None

        client_config = ModelClientConfig(
            client_provider=provider,
            api_key=api_key or "dummy",
            api_base=api_base or "http://dummy",
            verify_ssl=False,
        )
        return Model(model_client_config=client_config)

    @staticmethod
    def _normalize_model_provider(provider: Any) -> str:
        value = str(provider or "openai").strip()
        lowered = value.lower()
        mapping = {
            "openai": "OpenAI",
            "siliconflow": "SiliconFlow",
            "dashscope": "DashScope",
        }
        return mapping.get(lowered, value)

    async def invoke(self, input_data: Dict[str, Any], history: List[Dict] = None) -> Any:
        await self.skill_manager.initialize()
        action = (input_data or {}).get("action", "llm_select_and_call_skill")

        if action == "call_sample_skill":
            numbers = (input_data or {}).get("numbers", [1, 2, 3, 4])
            result = summarize_numbers(numbers)
            return {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "action": action,
                        "skill": "web_calc_skill",
                        "result": result,
                    },
                    ensure_ascii=False,
                ),
            }

        if action == "llm_select_and_call_skill":
            decision, execution_result = await self._llm_select_and_call_skill(input_data or {}, history or [])
            return {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "action": action,
                        "selected_skill": decision.get("skill_name"),
                        "arguments": decision.get("arguments", {}),
                        "reason": decision.get("reason", ""),
                        "execution_result": execution_result,
                    },
                    ensure_ascii=False,
                ),
            }

        raise ValueError(f"不支持的 action: {action}")

    async def _llm_select_and_call_skill(
        self,
        payload: Dict[str, Any],
        history: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        # 统一按 openjiuwen tools 协议暴露可执行 skill
        tools = self.skill_manager.list_available_skills(executable_only=True)
        if not self._model:
            raise RuntimeError("未配置模型，无法执行 llm_select_and_call_skill")
        if not tools:
            return (
                {
                    "skill_name": "none",
                    "arguments": {},
                    "reason": "没有可执行 skill",
                },
                {
                    "executed": False,
                    "message": "没有可执行 skill",
                },
            )

        response = await self._route_by_llm(payload, history, tools)
        decision = self._extract_decision_from_tool_calls(response)
        execution_result = await self._execute_selected_skill(decision, payload)
        return decision, execution_result

    async def _route_by_llm(
        self,
        payload: Dict[str, Any],
        history: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Any:
        query = payload.get("query") or payload.get("content") or ""
        if not query and payload.get("numbers"):
            query = f"请对数字做统计: {payload.get('numbers')}"

        system_prompt = (
            "你是一个 skill 路由器。\n"
            "你只能使用提供的 tools 进行调用。\n"
            "当需要调用 skill 时，请通过 openjiuwen tool_calls 返回，arguments 必须是合法 JSON。\n"
            "当不需要调用时，直接回复简短说明。"
        )

        user_payload = {
            "query": query,
            "input_data": payload,
            "history": history,
            "available_tools": tools,
        }

        return await self._model.invoke(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            tools=tools,
        )

    @staticmethod
    def _extract_decision_from_tool_calls(response: Any) -> Dict[str, Any]:
        # 兼容 openjiuwen/模型返回的多种 tool_call 结构
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            return {
                "skill_name": "none",
                "arguments": {},
                "reason": str(getattr(response, "content", "") or "LLM 未触发 tool_calls"),
            }

        first_call = tool_calls[0]
        raw_name = getattr(first_call, "name", None)
        raw_arguments = getattr(first_call, "arguments", None)

        if not raw_name and isinstance(first_call, dict):
            raw_name = first_call.get("name") or ((first_call.get("function") or {}).get("name"))
        if raw_arguments is None and isinstance(first_call, dict):
            raw_arguments = first_call.get("arguments") or ((first_call.get("function") or {}).get("arguments"))

        arguments: Dict[str, Any] = {}
        if isinstance(raw_arguments, dict):
            arguments = raw_arguments
        elif isinstance(raw_arguments, str) and raw_arguments.strip():
            try:
                parsed = json.loads(raw_arguments)
                if isinstance(parsed, dict):
                    arguments = parsed
            except Exception:
                arguments = {}

        return {
            "skill_name": str(raw_name or "none"),
            "arguments": arguments,
            "reason": "openjiuwen_tool_call",
        }

    async def _execute_selected_skill(self, decision: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        skill_name = str(decision.get("skill_name") or "none")
        if skill_name.lower() == "none":
            return {
                "executed": False,
                "message": "LLM 判定不调用任何 skill",
            }

        arguments = decision.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}

        if skill_name == "web_calc_skill" and "numbers" not in arguments and "numbers" in payload:
            arguments["numbers"] = payload.get("numbers")

        return await self.skill_manager.execute_skill(skill_name, arguments)

    async def _run_web_calc_skill(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        numbers = arguments.get("numbers", [])
        if not isinstance(numbers, list):
            raise ValueError("web_calc_skill 参数 numbers 必须是数组")

        clean_numbers = []
        for item in numbers:
            if isinstance(item, (int, float)):
                clean_numbers.append(item)
            else:
                try:
                    clean_numbers.append(float(item))
                except Exception as exc:
                    raise ValueError(f"numbers 中存在非数字项: {item}") from exc

        result = summarize_numbers(clean_numbers)
        return {
            "executed": True,
            "skill": "web_calc_skill",
            "arguments": {"numbers": clean_numbers},
            "result": result,
        }
