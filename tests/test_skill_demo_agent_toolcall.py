import json
from pathlib import Path

import pytest

from src.agents.skill_demo_agent import skill_demo_agent as skill_demo_agent_module
from src.agents.skill_demo_agent.skill_demo_agent import SkillDemoAgent
from src.skills.skillmgr import SkillMgr


class _DummyToolCall:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _DummyLLMResponse:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.content = ""


class _DummyModel:
    async def invoke(self, *args, **kwargs):
        return _DummyLLMResponse([
            _DummyToolCall(
                name="web_calc_skill",
                arguments=json.dumps({"numbers": [1, 2, 3, 4]}, ensure_ascii=False),
            )
        ])


@pytest.mark.asyncio
async def test_skill_demo_agent_use_openjiuwen_tool_calls(monkeypatch, tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    mgr = SkillMgr(skills_root=skills_root)
    await mgr.initialize()
    monkeypatch.setattr(skill_demo_agent_module, "get_skill_manager", lambda: mgr)

    agent = SkillDemoAgent("{}")
    agent._model = _DummyModel()

    result = await agent.invoke({"action": "llm_select_and_call_skill", "numbers": [1, 2, 3, 4]}, history=[])
    payload = json.loads(result["content"])

    assert payload["selected_skill"] == "web_calc_skill"
    assert payload["execution_result"]["executed"] is True
    assert payload["execution_result"]["skill"] == "web_calc_skill"
