import json
from pathlib import Path

import pytest

from src.skills.skillmgr import SkillMgr


@pytest.mark.asyncio
async def test_skillmgr_initialize_scan(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    # 本地目录应被扫描进索引
    (skills_root / "alpha_skill").mkdir()
    (skills_root / "beta_skill").mkdir()
    (skills_root / "__pycache__").mkdir()

    # 预置 registry（与本地目录一起合并）
    registry_payload = {
        "skills": [
            {
                "name": "from_registry",
                "path": "src/skills/from_registry",
                "source": "seed",
                "registered_at": "2026-02-27T00:00:00Z",
            }
        ]
    }
    (skills_root / "registry.json").write_text(json.dumps(registry_payload, ensure_ascii=False), encoding="utf-8")

    mgr = SkillMgr(skills_root=skills_root)
    await mgr.initialize()

    names = {item["name"] for item in mgr.list_available_skills(executable_only=False)}
    assert "from_registry" in names
    assert "alpha_skill" in names
    assert "beta_skill" in names
    assert "__pycache__" not in names


@pytest.mark.asyncio
async def test_skillmgr_incremental_register(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    seed = {
        "skills": [
            {
                "name": "seed_skill",
                "path": "src/skills/seed_skill",
                "source": "seed",
                "registered_at": "2026-02-27T00:00:00Z",
            }
        ]
    }
    (skills_root / "registry.json").write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")

    mgr = SkillMgr(skills_root=skills_root)
    await mgr.initialize()

    new_dir = skills_root / "new_skill"
    new_dir.mkdir(parents=True, exist_ok=True)
    await mgr.register_skill("new_skill", new_dir, source="unit-test")

    in_memory_names = {item["name"] for item in mgr.list_available_skills(executable_only=False)}
    assert in_memory_names == {"seed_skill", "new_skill"}

    written = json.loads((skills_root / "registry.json").read_text(encoding="utf-8"))
    written_names = {item["name"] for item in written["skills"]}
    assert written_names == {"seed_skill", "new_skill"}


def test_skillmgr_engine_no_download_upload_capability(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    mgr = SkillMgr(skills_root=skills_root)
    assert not hasattr(mgr, "download_and_register")
    assert not hasattr(mgr, "upload_archive_and_register")


@pytest.mark.asyncio
async def test_skillmgr_list_available_skills_openjiuwen_output(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    # 本地 skill（不可执行）
    (skills_root / "local_only").mkdir(parents=True, exist_ok=True)

    mgr = SkillMgr(skills_root=skills_root)
    await mgr.initialize()
    mgr.register_builtin_skill(
        name="web_calc_skill",
        handler=lambda arguments: {"executed": True, "result": arguments},
        description="计算器",
        input_schema={
            "type": "object",
            "properties": {"numbers": {"type": "array", "items": {"type": "number"}}},
        },
    )

    executable_tools = mgr.list_available_skills(executable_only=True)
    assert len(executable_tools) == 1
    assert executable_tools[0]["type"] == "function"
    assert executable_tools[0]["name"] == "web_calc_skill"
    assert executable_tools[0]["description"] == "计算器"
    assert executable_tools[0]["parameters"]["type"] == "object"

    all_tools = mgr.list_available_skills(executable_only=False)
    names = {item["name"] for item in all_tools}
    assert "web_calc_skill" in names
    assert "local_only" in names


@pytest.mark.asyncio
async def test_skillmgr_initialize_reads_skills_root_from_env(tmp_path: Path, monkeypatch):
    env_skills_root = tmp_path / "env_skills"
    env_skills_root.mkdir(parents=True, exist_ok=True)
    (env_skills_root / "from_env").mkdir(parents=True, exist_ok=True)

    env_file = tmp_path / ".env"
    env_file.write_text(f"SKILLS_ROOT={env_skills_root.as_posix()}\n", encoding="utf-8")

    monkeypatch.delenv("SKILLS_ROOT", raising=False)

    mgr = SkillMgr(skills_root=None)
    mgr.env_file = env_file
    await mgr.initialize()

    assert mgr.skills_root.resolve() == env_skills_root.resolve()
    names = {item["name"] for item in mgr.list_available_skills(executable_only=False)}
    assert "from_env" in names


@pytest.mark.asyncio
async def test_skillmgr_auto_bind_executable_from_skill_md(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "dyn_skill"
    skill_dir.mkdir(parents=True, exist_ok=True)

    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: dyn_skill",
                "description: 动态绑定技能",
                "entry_module: run.py",
                "entry_function: run",
                'input_schema: {"type": "object", "properties": {"x": {"type": "number"}}}',
                "---",
            ]
        ),
        encoding="utf-8",
    )
    (skill_dir / "run.py").write_text(
        "def run(arguments):\n    return {'executed': True, 'result': arguments.get('x')}\n",
        encoding="utf-8",
    )

    mgr = SkillMgr(skills_root=skills_root)
    await mgr.initialize()

    tools = mgr.list_available_skills(executable_only=True)
    assert any(item["name"] == "dyn_skill" for item in tools)

    result = await mgr.execute_skill("dyn_skill", {"x": 12})
    assert result["executed"] is True
    assert result["result"] == 12


@pytest.mark.asyncio
async def test_skillmgr_refresh_skills_incremental_load_new_skill(tmp_path: Path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    mgr = SkillMgr(skills_root=skills_root)
    await mgr.initialize()

    late_dir = skills_root / "late_skill"
    late_dir.mkdir(parents=True, exist_ok=True)

    stats = await mgr.refresh_skills_incremental()
    assert stats["added_from_local_scan"] >= 1

    names = {item["name"] for item in mgr.list_available_skills(executable_only=False)}
    assert "late_skill" in names

    written = json.loads((skills_root / "registry.json").read_text(encoding="utf-8"))
    written_names = {item["name"] for item in written["skills"]}
    assert "late_skill" in written_names
