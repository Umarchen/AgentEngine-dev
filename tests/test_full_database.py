"""
Agent Engine Service 测试用例
"""

import json
import pytest
import asyncio
from datetime import datetime
from tenacity import retry, stop_after_delay, wait_fixed

from src.models.schemas import (
    AgentConfig,
    AgentTaskRequest,
    AgentHealthStatus,
    AgentTrajectory,
    ContextContent,
    HealthChecks,
    TrajectoryStep,
    Trajectory,
)
from src.database.database import DatabaseManager
from src.core.base import AgentRegistry
from src.core.config_manager import AgentConfigManager
from src.core.agent_manager import AgentManager


# ==================== 数据库模块测试 ====================

class TestFullDatabase:
    """数据库管理器测试"""
    
    @pytest.fixture
    def db_manager(self):
        """创建数据库管理器实例"""
        return DatabaseManager("sqlite+aiosqlite:///:memory:")
    
    @pytest.mark.asyncio
    async def test_connect_disconnect(self, db_manager:DatabaseManager):
        """测试连接和断开"""
        # 连接
        result = await db_manager.connect()
        assert result is True
        assert db_manager.is_connected is True
        
        # 断开
        await db_manager.disconnect()
        assert db_manager.is_connected is False
    
    @pytest.mark.asyncio
    async def test_save_and_get_config(self, db_manager:DatabaseManager):
        """测试保存和获取配置"""
        await db_manager.connect()
        
        config = AgentConfig(
            agent_config_id="cfg-test-package-002",
            agent_id="test-package-002",
            agent_type_id="test",
            agent_type_name="Test Agent"
        )
        
        # 保存配置
        result = await db_manager.save_agent_config(config)
        assert result is True
        
        # 获取配置
        retrieved = await db_manager.get_agent_config("test-package-002")
        assert retrieved is not None
        assert retrieved.agent_id == "test-package-002"
        
        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_get_all_agent_configs(self, db_manager:DatabaseManager):
        """测试获取所有配置"""
        await db_manager.connect()
        
        config1 = AgentConfig(
            agent_config_id="cfg-test-package-004",
            agent_id="test-package-004",
            agent_type_id="test",
            agent_type_name="Test Agent 1"
        )
        
        config2 = AgentConfig(
            agent_config_id="cfg-test-package-005",
            agent_id="test-package-005",
            agent_type_id="echo",
            agent_type_name="Test Agent 2"
        )
        
        # 保存配置
        await db_manager.save_agent_config(config1)
        await db_manager.save_agent_config(config2)
        
        # 获取所有配置
        all_configs = await db_manager.get_all_agent_configs()
        
        # 验证结果
        assert len(all_configs) >= 2  # 可能包含其他测试插入的数据
        retrieved_ids = {c.agent_id for c in all_configs}
        assert "test-package-004" in retrieved_ids
        assert "test-package-005" in retrieved_ids
        
        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_save_and_get_agent_config_full(self, db_manager: DatabaseManager):
        """测试保存和获取Agent配置信息（涉及所有字段）"""
        await db_manager.connect()
        
        # 创建一个完整的AgentConfig对象，包含所有字段
        config = AgentConfig(
            agent_config_id="cfg-test-config-001",
            agent_id="test-config-001",
            agent_type_id="full-test-agent",
            agent_type_name="Full Test Agent",
            description="这是一个完整的测试Agent配置",
            config_schema={
                "type": "object",
                "properties": {
                    "param1": {"type": "string"},
                    "param2": {"type": "integer"}
                }
            },
            create_time=datetime(2023, 1, 1, 12, 0, 0),
        )
        
        # 保存配置
        result = await db_manager.save_agent_config(config)
        assert result is True
        
        # 获取配置
        retrieved = await db_manager.get_agent_config("test-config-001")
        assert retrieved is not None
        
        # 验证所有字段
        assert retrieved.agent_id == config.agent_id
        assert retrieved.agent_type_id == config.agent_type_id
        assert retrieved.agent_type_name == config.agent_type_name
        assert retrieved.description == config.description
        assert retrieved.config_schema == config.config_schema
        assert retrieved.create_time == config.create_time
        
        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_save_and_get_agent_status(self, db_manager: DatabaseManager):
        """测试保存和获取Agent健康状态信息"""
        await db_manager.connect()
        
        # 创建一个完整的AgentHealthStatus对象
        status = AgentHealthStatus(
            agent_id="test-agent-001",
            agent_type_name="echo_agent",
            status="healthy",
            checks=HealthChecks(
                alive=True,
                responsive=True,
                task_queue_healthy=True
            ),
            uptime_seconds=3600.5,
            checked_at=datetime.now()
        )
        
        # 保存状态
        result = await db_manager.save_agent_status(status)
        assert result is True
        
        # 获取状态历史记录
        @retry(stop=stop_after_delay(5), wait=wait_fixed(0.5))
        async def wait_for_data():
            result = await db_manager.get_status_history(agent_id="test-agent-001")
            assert len(result) > 0, "数据尚未写入"
            return result
                
        status_history = await wait_for_data()
        assert len(status_history) > 0
        
        # 验证获取的状态信息
        retrieved_status = status_history[0]
        assert retrieved_status.agent_id == status.agent_id
        assert retrieved_status.agent_type_name == status.agent_type_name
        assert retrieved_status.status == status.status
        assert retrieved_status.uptime_seconds == status.uptime_seconds
        assert retrieved_status.checked_at == status.checked_at
        assert retrieved_status.checks == status.checks

        # 等待队列处理完成，确保后台任务代码被执行并被覆盖率跟踪
        await db_manager._write_queue.join()

        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_update_agent_config(self, db_manager: DatabaseManager):
        """测试更新Agent配置信息"""
        await db_manager.connect()
        
        # 1. 首先创建一个初始配置
        initial_config = AgentConfig(
            agent_config_id="cfg-test-update-001",
            agent_id="test-update-001",
            agent_type_id="echo",
            agent_type_name="Initial Name",
            description="Initial description",
            config_schema={"param": "value"},
        )
        
        # 保存初始配置
        assert await db_manager.save_agent_config(initial_config)
        
        # 2. 获取并验证初始配置
        retrieved = await db_manager.get_agent_config("test-update-001")
        assert retrieved.agent_type_name == "Initial Name"
        assert retrieved.config_schema == {"param": "value"}
        
        # 3. 更新配置信息
        updated_config = AgentConfig(
            agent_config_id="cfg-test-update-001",
            agent_id="test-update-001",  # 相同agent_id表示更新
            agent_type_id="echo",
            agent_type_name="Updated Name",  # 更新名称
            description="Updated description",  # 更新描述
            config_schema={"new_param": "new_value"},  # 更新配置
        )
        
        # 保存更新后的配置
        assert await db_manager.save_agent_config(updated_config)
        
        # 4. 获取并验证更新后的配置
        updated = await db_manager.get_agent_config("test-update-001")
        assert updated.agent_type_name == "Updated Name"
        assert updated.config_schema == {"new_param": "new_value"}
        
        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_save_and_get_agent_trajectory(self, db_manager: DatabaseManager):
        """测试保存和获取Agent运行轨迹信息"""
        await db_manager.connect()
        
        # 创建一个完整的AgentTrajectory对象
        trajectory = AgentTrajectory(
            agent_id="test-agent-002",
            user_id="user-001",
            session_id="session-001",
            trajectory=Trajectory(
                steps=[
                    TrajectoryStep(
                        step=0,
                        state="初始状态",
                        action="执行动作",
                        reward=1.0,
                        next_state="下一状态",
                        is_terminal=False
                    )
                ]
            ),
        )
        
        # 保存轨迹
        result = await db_manager.save_agent_trajectory(trajectory)
        assert result is True
        
        # 获取轨迹历史记录
        @retry(stop=stop_after_delay(5), wait=wait_fixed(0.5))
        async def wait_for_data():
            result = await db_manager.get_trajectory_history()
            assert len(result) > 0, "数据尚未写入"
            return result

        trajectory_history = await wait_for_data()
        assert len(trajectory_history) > 0
        
        # 验证获取的轨迹信息
        retrieved_trajectory = trajectory_history[0]
        assert retrieved_trajectory.agent_id == trajectory.agent_id
        assert retrieved_trajectory.user_id == trajectory.user_id
        assert retrieved_trajectory.session_id == trajectory.session_id
        assert retrieved_trajectory.trajectory == trajectory.trajectory
        
        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_save_and_get_with_agent_id_agent_trajectory(self, db_manager: DatabaseManager):
        """测试保存和获取Agent运行轨迹信息"""
        await db_manager.connect()
        
        # 创建一个完整的AgentTrajectory对象
        trajectory = AgentTrajectory(
            agent_id="test-agent-002",
            user_id="user-001",
            session_id="session-001",
            trajectory=Trajectory(
                steps=[
                    TrajectoryStep(
                        step=0,
                        state="初始状态",
                        action="执行动作",
                        reward=1.0,
                        next_state="下一状态",
                        is_terminal=False
                    )
                ]
            ),
        )
        
        # 保存轨迹
        result = await db_manager.save_agent_trajectory(trajectory)
        assert result is True
        
        # 获取轨迹历史记录
        @retry(stop=stop_after_delay(5), wait=wait_fixed(0.5))
        async def wait_for_data():
            result = await db_manager.get_trajectory_history(agent_id="test-agent-002")
            assert len(result) > 0, "数据尚未写入"
            return result

        trajectory_history = await wait_for_data()
        assert len(trajectory_history) > 0
        
        # 验证获取的轨迹信息
        retrieved_trajectory = trajectory_history[0]
        assert retrieved_trajectory.agent_id == trajectory.agent_id
        assert retrieved_trajectory.user_id == trajectory.user_id
        assert retrieved_trajectory.session_id == trajectory.session_id
        assert retrieved_trajectory.trajectory == trajectory.trajectory
        
        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_save_and_get_with_agent_id_not_found_agent_trajectory(self, db_manager: DatabaseManager):
        """测试保存和获取Agent运行轨迹信息"""
        await db_manager.connect()
        
        # 创建一个完整的AgentTrajectory对象
        trajectory = AgentTrajectory(
            agent_id="test-agent-002",
            user_id="user-001",
            session_id="session-001",
            trajectory=Trajectory(
                steps=[
                    TrajectoryStep(
                        step=0,
                        state="初始状态",
                        action="执行动作",
                        reward=1.0,
                        next_state="下一状态",
                        is_terminal=False
                    )
                ]
            ),
        )
        
        # 保存轨迹
        result = await db_manager.save_agent_trajectory(trajectory)
        assert result is True
        
        # 获取轨迹历史记录
        @retry(stop=stop_after_delay(5), wait=wait_fixed(0.5))
        async def wait_for_data():
            result = await db_manager.get_trajectory_history()
            assert len(result) > 0, "数据尚未写入"
            return result

        await wait_for_data()
        trajectory_history = await db_manager.get_trajectory_history(agent_id="test-agent-005")
        assert len(trajectory_history) == 0
        
        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_save_and_get_with_session_agent_trajectory(self, db_manager: DatabaseManager):
        """测试保存和获取Agent运行轨迹信息"""
        await db_manager.connect()
        
        # 创建一个完整的AgentTrajectory对象
        trajectory = AgentTrajectory(
            agent_id="test-agent-002",
            user_id="user-001",
            session_id="session-001",
            trajectory=Trajectory(
                steps=[
                    TrajectoryStep(
                        step=0,
                        state="初始状态",
                        action="执行动作",
                        reward=1.0,
                        next_state="下一状态",
                        is_terminal=False
                    )
                ]
            ),
            created_at=datetime.now()
        )
        
        # 保存轨迹
        result = await db_manager.save_agent_trajectory(trajectory)
        assert result is True
        
        # 获取轨迹历史记录
        @retry(stop=stop_after_delay(5), wait=wait_fixed(0.5))
        async def wait_for_data():
            result = await db_manager.get_trajectory_history(agent_id="test-agent-002",session_id="session-001")
            assert len(result) > 0, "数据尚未写入"
            return result

        trajectory_history = await wait_for_data()
        assert len(trajectory_history) > 0
        
        # 验证获取的轨迹信息
        retrieved_trajectory = trajectory_history[0]
        assert retrieved_trajectory.agent_id == trajectory.agent_id
        assert retrieved_trajectory.user_id == trajectory.user_id
        assert retrieved_trajectory.session_id == trajectory.session_id
        assert retrieved_trajectory.trajectory == trajectory.trajectory
        
        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_save_task(self, db_manager: DatabaseManager):
        """测试保存任务"""
        await db_manager.connect()

        # 准备测试数据
        task_id = "test-task-001"
        agent_id = "test-agent-001"
        session_id = "test-session-001"
        task_new_context = [{"type" : "user", "content" : "请评估风险"}]
        user_id = "test-user-001"
        task_status = "completed"
        token_count = 100

        # 保存任务
        result = await db_manager.save_task(
            task_id=task_id,
            agent_id=agent_id,
            session_id=session_id,
            task_new_context=task_new_context,
            user_id=user_id,
            task_status=task_status,
            token_count=token_count
        )
        assert result is True

        # 验证任务是否已保存
        saved_task = await db_manager.get_task(task_id)
        assert saved_task is not None
        assert saved_task.agent_id == agent_id
        assert saved_task.task_status == task_status
        assert saved_task.token_count == token_count
        assert json.dumps(saved_task.context_content.context) == json.dumps(task_new_context)
        assert saved_task.user_id == user_id
        assert saved_task.session_id == session_id

        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_update_task(self, db_manager: DatabaseManager):
        """测试更新任务"""
        await db_manager.connect()

        task_id = "test-task-001"
        agent_id = "test-agent-001"
        session_id = "test-session-001"
        context = [{"type" : "user", "content" : "请评估风险"}]

        new_context = [{"type" : "user", "content" : "New请评估风险"}]
        
        task_status = "in_progress"
        token_count = 200

        # 首先保存任务
        await db_manager.save_task(
            task_id=task_id,
            agent_id=agent_id,
            session_id=session_id,
            task_new_context=context,
            task_status="completed",
            token_count=100
        )

        # 更新任务
        result = await db_manager.save_task(
            task_id=task_id,
            agent_id=agent_id,
            session_id=session_id,
            task_new_context=new_context,
            task_status=task_status,
            token_count=token_count
        )
        assert result is True

        # 验证任务是否已更新
        updated_task = await db_manager.get_task(task_id)
        assert updated_task is not None
        assert json.dumps(updated_task.context_content.context) == json.dumps(context + new_context)
        assert updated_task.task_status == task_status
        assert updated_task.token_count == token_count

        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_save_session_info(self, db_manager: DatabaseManager):
        """测试保存或更新会话信息"""
        await db_manager.connect()

        # 准备测试数据
        session_id = "test-session-001"
        agent_id = "test-agent-001"
        user_id = "test-user-001"
        task_id = "test-task-001"
        initial_messages = [
            {"type" : "user", "content" : "你好"},
            {"type" : "agent", "content" : "你好，有什么我可以帮你的吗？"}
        ]

        # 测试首次保存会话
        result = await db_manager.save_session_info(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            task_id=task_id,
            new_messages=initial_messages
        )
        assert result is True

        # 验证会话是否已保存
        saved_session = await db_manager.get_session_info(session_id)
        assert saved_session is not None
        assert saved_session.session_id == session_id
        assert agent_id in saved_session.agent_ids
        assert user_id in saved_session.user_ids
        assert task_id in saved_session.task_ids
        expected_history = ContextContent(context=initial_messages)
        assert saved_session.conversation_history.model_dump_json() == expected_history.model_dump_json()

        # 测试更新会话（追加新消息）
        new_agent_id = "test-agent-002"
        new_user_id = "test-user-002"
        new_task_id = "test-task-002"
        append_messages = [
            {"type" : "user", "content" : "谢谢"},
            {"type" : "agent", "content" : "不客气，再见"},
        ]

        result = await db_manager.save_session_info(
            session_id=session_id,
            agent_id=new_agent_id,
            user_id=new_user_id,
            task_id=new_task_id,
            new_messages=append_messages
        )
        assert result is True

        # 验证会话是否已更新（history 应包含所有消息）
        updated_session = await db_manager.get_session_info(session_id)
        assert updated_session is not None
        assert new_agent_id in updated_session.agent_ids
        assert agent_id in updated_session.agent_ids  # 原有agent_id应保留
        assert new_user_id in updated_session.user_ids
        assert user_id in updated_session.user_ids  # 原有user_id应保留
        assert new_task_id in updated_session.task_ids
        assert task_id in updated_session.task_ids  # 原有task_id应保留
        full_history = ContextContent(context=initial_messages + append_messages)
        assert updated_session.conversation_history.model_dump_json() == full_history.model_dump_json()

        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_concurrent_save_session_no_data_loss(self, db_manager: DatabaseManager):
        """
        并发竞态条件测试：两个协程同时向同一 session 追加消息，验证不会互相覆盖。

        模拟场景（修复前会丢数据）：
          Worker A: read → [msg1]       → append outputA → write [msg1, A1, A2]
          Worker B: read → [msg1]       → append outputB → write [msg1, B1, B2]  ← outputA 丢失

        修复后预期结果：DB 中应包含 msg1 + outputA + outputB 全部 5 条消息。
        """
        await db_manager.connect()

        session_id = "race-condition-session"
        seed_message = [{"role": "user", "content": "初始消息"}]

        # 先写入一条种子消息
        await db_manager.save_session_info(
            session_id=session_id,
            agent_id="agent-seed",
            user_id="user-seed",
            task_id="task-seed",
            new_messages=seed_message,
        )

        # 两组不同的追加消息
        output_a = [
            {"role": "user", "content": "问题A"},
            {"role": "assistant", "content": "回答A"},
        ]
        output_b = [
            {"role": "user", "content": "问题B"},
            {"role": "assistant", "content": "回答B"},
        ]

        # 并发追加
        results = await asyncio.gather(
            db_manager.save_session_info(
                session_id=session_id,
                agent_id="agent-A",
                user_id="user-A",
                task_id="task-A",
                new_messages=output_a,
            ),
            db_manager.save_session_info(
                session_id=session_id,
                agent_id="agent-B",
                user_id="user-B",
                task_id="task-B",
                new_messages=output_b,
            ),
        )
        assert all(results), "两次 save 都应成功"

        # 验证：DB 中应包含全部 5 条消息（1 条种子 + 2 条 A + 2 条 B）
        session_info = await db_manager.get_session_info(session_id)
        assert session_info is not None

        history = session_info.conversation_history.context
        contents = [m["content"] for m in history]

        assert "初始消息" in contents, "种子消息丢失"
        assert "问题A" in contents, "Worker A 的消息丢失"
        assert "回答A" in contents, "Worker A 的消息丢失"
        assert "问题B" in contents, "Worker B 的消息丢失"
        assert "回答B" in contents, "Worker B 的消息丢失"
        assert len(history) == 5, f"应有 5 条消息，实际 {len(history)} 条: {contents}"

        # 验证 agent_ids / user_ids / task_ids 也都保留
        assert "agent-A" in session_info.agent_ids
        assert "agent-B" in session_info.agent_ids
        assert "user-A" in session_info.user_ids
        assert "user-B" in session_info.user_ids
        assert "task-A" in session_info.task_ids
        assert "task-B" in session_info.task_ids

        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_concurrent_save_task_no_data_loss(self, db_manager: DatabaseManager):
        """
        并发竞态条件测试：两个协程同时向同一 task 追加上下文，验证不会互相覆盖。
        """
        await db_manager.connect()

        session_id = "race-task-session"
        agent_id = "race-task-agent"

        # 先写入种子 context
        seed_context = [{"role": "user", "content": "种子"}]
        await db_manager.save_task(
            task_id="task-race",
            agent_id=agent_id,
            session_id=session_id,
            task_new_context=seed_context,
            user_id="u1",
            task_status="running",
        )

        context_a = [{"role": "assistant", "content": "回复A"}]
        context_b = [{"role": "assistant", "content": "回复B"}]

        results = await asyncio.gather(
            db_manager.save_task(
                agent_id=agent_id,
                session_id=session_id,
                task_new_context=context_a,
                task_status="running",
            ),
            db_manager.save_task(
                agent_id=agent_id,
                session_id=session_id,
                task_new_context=context_b,
                task_status="running",
            ),
        )
        assert all(results), "两次 save_task 都应成功"

        task = await db_manager.get_task("task-race")
        assert task is not None
        contents = [m["content"] for m in task.context_content.context]

        assert "种子" in contents, "种子上下文丢失"
        assert "回复A" in contents, "Worker A 上下文丢失"
        assert "回复B" in contents, "Worker B 上下文丢失"
        assert len(task.context_content.context) == 3, (
            f"应有 3 条，实际 {len(task.context_content.context)} 条: {contents}"
        )

        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_save_agent_status_batch(self, db_manager: DatabaseManager):
        """测试批量保存Agent健康状态"""
        await db_manager.connect()

        # 创建批量状态
        statuses = [
            AgentHealthStatus(
                agent_id=f"test-batch-agent-{i}",
                agent_type_name="echo_agent",
                status="healthy",
                checks=HealthChecks(
                    alive=True,
                    responsive=True,
                    task_queue_healthy=True
                ),
                uptime_seconds=100.0 + i,
                checked_at=datetime.now()
            )
            for i in range(3)
        ]

        # 批量保存
        result = await db_manager.save_agent_status_batch(statuses)
        assert result is True

        # 等待队列处理完成
        await db_manager._write_queue.join()

        # 验证所有状态都已保存
        for i in range(3):
            history = await db_manager.get_status_history(agent_id=f"test-batch-agent-{i}")
            assert len(history) > 0, f"Agent {i} 的状态未保存"

        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_write_queue_processing(self, db_manager: DatabaseManager):
        """直接测试写入队列处理机制"""
        await db_manager.connect()

        # 验证后台任务已启动
        assert db_manager._write_task is not None
        assert not db_manager._write_task.done()

        # 写入多条状态，验证队列 FIFO 处理
        statuses = []
        for i in range(5):
            status = AgentHealthStatus(
                agent_id=f"queue-test-{i}",
                agent_type_name="test",
                status="healthy",
                uptime_seconds=i,
                checked_at=datetime.now()
            )
            statuses.append(status)
            await db_manager.save_agent_status(status)

        # 等待队列处理完成
        await db_manager._write_queue.join()

        # 验证所有数据都已写入
        for i in range(5):
            history = await db_manager.get_status_history(agent_id=f"queue-test-{i}")
            assert len(history) > 0, f"Agent queue-test-{i} 的状态未保存"

        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_do_write_status_directly(self, db_manager: DatabaseManager):
        """直接测试 _do_write_status 方法，确保覆盖率工具能跟踪"""
        await db_manager.connect()

        status = AgentHealthStatus(
            agent_id="direct-write-test",
            agent_type_name="test_agent",
            status="healthy",
            checks=HealthChecks(alive=True, responsive=True),
            uptime_seconds=123.45,
            checked_at=datetime.now()
        )

        # 直接调用私有方法，绕过队列
        await db_manager._do_write_status(status)

        # 验证数据已写入
        history = await db_manager.get_status_history(agent_id="direct-write-test")
        assert len(history) == 1
        assert history[0].agent_id == "direct-write-test"
        assert history[0].uptime_seconds == 123.45

        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_do_write_trajectory_directly(self, db_manager: DatabaseManager):
        """直接测试 _do_write_trajectory 和 _upsert_trajectory 方法"""
        await db_manager.connect()

        trajectory = AgentTrajectory(
            agent_id="direct-traj-test",
            user_id="user-test",
            session_id="session-test",
            trajectory=Trajectory(steps=[
                TrajectoryStep(
                    step=0,
                    state="初始状态",
                    action="测试动作",
                    reward=0.5,
                    next_state="下一状态"
                )
            ]),
            create_time=datetime.now(),
            update_time=datetime.now()
        )

        # 直接调用私有方法
        await db_manager._do_write_trajectory(trajectory)

        # 验证数据已写入
        traj_history = await db_manager.get_trajectory_history(agent_id="direct-traj-test")
        assert len(traj_history) == 1
        assert traj_history[0].agent_id == "direct-traj-test"

        # 测试追加模式（_upsert_trajectory 的更新逻辑）
        trajectory2 = AgentTrajectory(
            agent_id="direct-traj-test",
            user_id="user-test",
            session_id="session-test",
            trajectory=Trajectory(steps=[
                TrajectoryStep(
                    step=1,
                    state="下一状态",
                    action="追加动作",
                    reward=1.0,
                    next_state="最终状态"
                )
            ]),
            create_time=datetime.now(),
            update_time=datetime.now()
        )

        await db_manager._upsert_trajectory(trajectory2)

        # 验证两条记录都存在
        traj_history = await db_manager.get_trajectory_history(agent_id="direct-traj-test")
        assert len(traj_history) == 1
        # 追加模式会合并轨迹步骤
        assert len(traj_history[0].trajectory.steps) == 2

        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_write_queue_cancel_on_disconnect(self, db_manager: DatabaseManager):
        """测试 disconnect 时队列任务被正确取消"""
        await db_manager.connect()

        # 验证后台任务已启动
        assert db_manager._write_task is not None
        assert not db_manager._write_task.done()

        # 写入数据到队列
        status = AgentHealthStatus(
            agent_id="cancel-test",
            agent_type_name="test",
            status="healthy",
            checks=HealthChecks(alive=True),
            uptime_seconds=100,
            checked_at=datetime.now()
        )
        await db_manager.save_agent_status(status)

        # 立即断开（队列可能还有未处理的数据）
        # 这会触发 asyncio.CancelledError 分支
        await db_manager.disconnect()

        # 验证任务已完成
        assert db_manager._write_task.done()

    @pytest.mark.asyncio
    async def test_upsert_trajectory_append_mode(self, db_manager: DatabaseManager):
        """测试 _upsert_trajectory 的追加模式逻辑（覆盖 631-645 行）"""
        await db_manager.connect()

        # 第一次写入：创建新记录
        trajectory1 = AgentTrajectory(
            agent_id="append-mode-test",
            user_id="user-test",
            session_id="session-test",
            trajectory=Trajectory(steps=[
                TrajectoryStep(step=0, state="S0", action="A0", reward=0.1, next_state="S1"),
                TrajectoryStep(step=1, state="S1", action="A1", reward=0.2, next_state="S2"),
            ]),
            create_time=datetime.now(),
            update_time=datetime.now()
        )
        await db_manager._upsert_trajectory(trajectory1)

        # 第二次写入：追加到已有记录
        trajectory2 = AgentTrajectory(
            agent_id="append-mode-test",
            user_id="user-test",
            session_id="session-test",
            trajectory=Trajectory(steps=[
                TrajectoryStep(step=2, state="S2", action="A2", reward=0.3, next_state="S3"),
            ]),
            create_time=datetime.now(),
            update_time=datetime.now()
        )
        await db_manager._upsert_trajectory(trajectory2)

        # 验证：两条记录合并成一条，steps 数量为 3
        traj_history = await db_manager.get_trajectory_history(agent_id="append-mode-test")
        assert len(traj_history) == 1
        assert len(traj_history[0].trajectory.steps) == 3

        # 验证步骤顺序
        steps = traj_history[0].trajectory.steps
        assert steps[0].action == "A0"
        assert steps[1].action == "A1"
        assert steps[2].action == "A2"

        await db_manager.disconnect()

    @pytest.mark.asyncio
    async def test_do_write_trajectory_empty_trajectory(self, db_manager: DatabaseManager):
        """测试 _do_write_trajectory 处理空轨迹的情况"""
        await db_manager.connect()

        # 空轨迹（使用默认的空 Trajectory）
        trajectory = AgentTrajectory(
            agent_id="empty-traj-test",
            user_id="user-test",
            session_id="session-test",
            trajectory=Trajectory(steps=[]),  # 空步骤列表
            create_time=datetime.now(),
            update_time=datetime.now()
        )

        # 直接调用私有方法
        await db_manager._do_write_trajectory(trajectory)

        # 验证数据已写入
        traj_history = await db_manager.get_trajectory_history(agent_id="empty-traj-test")
        assert len(traj_history) == 1

        await db_manager.disconnect()
