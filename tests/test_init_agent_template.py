"""测试 AgentManager 初始化 AgentType / AgentTemplate 表逻辑

覆盖：
- AgentManager.init_agent_type_data
- AgentManager.init_agent_template_data

说明：
- 依赖 src/agents/agent_templates_config.json 作为初始化数据源
- 使用 SQLite 内存库，避免污染本地文件
"""

import json

import pytest
from sqlalchemy import select

from src.core.agent_manager import AgentManager
from src.core.config_manager import AgentConfigManager
from src.database.database import DatabaseManager
from src.database.models import AgentTemplateDBModel, AgentTypeDBModel


class _NoopEvaluator:
    async def evaluate_trajectory(self, *args, **kwargs):  # pragma: no cover
        raise RuntimeError("not used in these tests")


async def _create_agent_manager(connection_string: str) -> tuple[AgentManager, DatabaseManager]:
    """Convenience helper to build manager + db stack for a given connection string."""
    db_manager = DatabaseManager(connection_string)
    await db_manager.connect()

    config_manager = AgentConfigManager(db_manager)

    agent_manager = AgentManager(
        config_manager=config_manager,
        db_manager=db_manager,
        evaluator=_NoopEvaluator(),
    )

    return agent_manager, db_manager


def _assert_json_payloads(template_row: AgentTemplateDBModel) -> None:
    """Ensure JSON text columns remain deserializable to list payloads."""
    assert isinstance(json.loads(template_row.model_config or "[]"), list)
    assert isinstance(json.loads(template_row.prompt_config or "[]"), list)
    assert isinstance(json.loads(template_row.mcp_tool_config or "[]"), list)
    assert isinstance(json.loads(template_row.mcp_server_config or "[]"), list)


def _assert_template_matches_type(
    template_row: AgentTemplateDBModel,
    type_row: AgentTypeDBModel,
) -> None:
    assert template_row.agent_template_id == type_row.agent_template_id
    assert template_row.agent_type_id == type_row.agent_type_id
    assert template_row.agent_type_name == type_row.agent_type_name


@pytest.fixture
async def agent_manager_and_db():
    agent_manager, db_manager = await _create_agent_manager("sqlite+aiosqlite:///:memory:")

    try:
        yield agent_manager, db_manager
    finally:
        await db_manager.disconnect()


@pytest.mark.asyncio
async def test_init_agent_type_data_writes_expected_rows(agent_manager_and_db):
    agent_manager, db_manager = agent_manager_and_db

    templates = agent_manager.get_agent_template_raw_data()
    expected = len(templates)
    assert expected > 0

    ok = await agent_manager.init_agent_type_data()
    assert ok is True

    async with db_manager.get_session() as session:
        rows = (await session.execute(select(AgentTypeDBModel))).scalars().all()

    assert len(rows) == expected

    # 关键字段应当被填充（uuid / timestamps）
    for row in rows:
        assert row.agent_type_id
        assert row.agent_type_name
        assert row.agent_template_id
        assert row.create_time is not None
        assert row.update_time is not None


@pytest.mark.asyncio
async def test_init_agent_template_data_writes_expected_rows_and_matches_type_table(agent_manager_and_db):
    agent_manager, db_manager = agent_manager_and_db

    templates = agent_manager.get_agent_template_raw_data()
    expected = len(templates)
    assert expected > 0

    ok_type = await agent_manager.init_agent_type_data()
    assert ok_type is True

    ok_tpl = await agent_manager.init_agent_template_data()
    assert ok_tpl is True

    async with db_manager.get_session() as session:
        type_rows = (await session.execute(select(AgentTypeDBModel))).scalars().all()
        tpl_rows = (await session.execute(select(AgentTemplateDBModel))).scalars().all()

    assert len(type_rows) == expected
    assert len(tpl_rows) == expected

    type_by_template = {r.agent_template_id: r for r in type_rows}

    for tpl in tpl_rows:
        assert tpl.agent_template_id
        assert tpl.agent_type_id
        assert tpl.agent_type_name
        assert tpl.create_time is not None
        assert tpl.update_time is not None

        # JSON 字段应可反序列化为 list
        _assert_json_payloads(tpl)

        # 与 AgentType 表保持一致
        assert tpl.agent_template_id in type_by_template
        type_row = type_by_template[tpl.agent_template_id]
        _assert_template_matches_type(tpl, type_row)


@pytest.mark.asyncio
async def test_init_agent_tables_with_sqlite_file(tmp_path):
    """
    端到端覆盖：使用真实的 sqlite 文件，确保初始化流程可写入磁盘并能读取完整数据。
    """

    db_file = tmp_path / "agent_init_demo.db"
    agent_manager, db_manager = await _create_agent_manager(
        f"sqlite+aiosqlite:///{db_file.as_posix()}"
    )

    ok_type = await agent_manager.init_agent_type_data()
    ok_tpl = await agent_manager.init_agent_template_data()

    async with db_manager.get_session() as session:
        type_rows = (await session.execute(select(AgentTypeDBModel))).scalars().all()
        template_rows = (await session.execute(select(AgentTemplateDBModel))).scalars().all()

    await db_manager.disconnect()

    assert ok_type is True
    assert ok_tpl is True
    assert len(type_rows) > 0
    assert len(template_rows) == len(type_rows)

    type_by_template = {row.agent_template_id: row for row in type_rows}

    for tpl in template_rows:
        assert tpl.agent_template_id
        assert tpl.agent_type_id
        assert tpl.create_time is not None
        assert tpl.update_time is not None

        assert tpl.agent_template_id in type_by_template
        type_row = type_by_template[tpl.agent_template_id]
        _assert_template_matches_type(tpl, type_row)

        # JSON字段仍应可反序列化
        _assert_json_payloads(tpl)
