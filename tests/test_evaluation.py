"""
轨迹评估系统测试
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.schemas import AgentTrajectory, Trajectory, TrajectoryStep
from src.models.evaluation_schemas import EvaluationRequest
from src.database.database import init_database, close_database
from src.services.evaluation import init_trajectory_evaluator


async def test_evaluation_system():
    """测试评估系统完整流程"""
    
    # 临时启用 DEBUG 日志
    from loguru import logger
    import sys
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
               "<level>{message}</level>"
    )
    
    print("=" * 60)
    print("轨迹评估系统测试")
    print("=" * 60)
    
    # 1. 初始化数据库
    print("\n[1] 初始化数据库...")
    db_manager = await init_database()
    
    # 2. 模拟写入轨迹数据
    print("\n[2] 模拟写入轨迹数据...")
    
    test_trajectory = AgentTrajectory(
        agent_id="risk-agent-001",
        user_id="user-12345",
        session_id="session-test-001",
        trajectory=Trajectory(
            steps=[
                TrajectoryStep(
                    step=0,
                    state="初始状态：收到风险评估请求",
                    action="查询企业基本信息",
                    reward=0.0,
                    next_state="获取到企业注册信息",
                    is_terminal=False
                ),
                TrajectoryStep(
                    step=1,
                    state="获取到企业注册信息",
                    action="分析财务数据",
                    reward=0.5,
                    next_state="完成财务分析",
                    is_terminal=False
                ),
                TrajectoryStep(
                    step=2,
                    state="完成财务分析",
                    action="生成风险评估报告",
                    reward=1.0,
                    next_state="报告生成完毕",
                    is_terminal=True
                )
            ]
        )
    )
    
    # 保存轨迹到数据库
    await db_manager.save_agent_trajectory(test_trajectory)
    print(f"✓ 轨迹已保存: agent_id={test_trajectory.agent_id}")
    
    # 等待异步写入完成
    await asyncio.sleep(0.5)
    
    # 3. 初始化评估器
    print("\n[3] 初始化评估器...")
    try:
        evaluator = await init_trajectory_evaluator(db_manager=db_manager)
        print(f"✓ 评估器初始化成功")
    except Exception as e:
        print(f"✗ 评估器初始化失败: {e}")
        print("\n提示：请确保已配置 EVALUATION_LLM_API_KEY 环境变量")
        print("或修改 config/evaluation_config.yaml 中的 LLM 配置")
        await close_database()
        return
    
    # 4. 触发评估
    print("\n[4] 触发轨迹评估...")
    print(f"   - agent_id: {test_trajectory.agent_id}")
    print(f"   - user_id: {test_trajectory.user_id}")
    print(f"   - session_id: {test_trajectory.session_id}")
    
    response = await evaluator.evaluate_trajectory(
        agent_id=test_trajectory.agent_id,
        user_id=test_trajectory.user_id,
        session_id=test_trajectory.session_id,
        force_reevaluate=False
    )
    
    # 5. 显示评估结果
    print("\n[5] 评估结果:")
    print("-" * 60)
    
    if response.success:
        print(f"✓ 评估成功")
        print(f"   评估记录 ID: {response.evaluation_id}")
        print(f"\n   【整体评分】")
        print(f"   分数: {response.evaluation.overall.score}/10")
        print(f"   理由: {response.evaluation.overall.reason}")
        
        print(f"\n   【分步评分】")
        for step_eval in response.evaluation.steps:
            print(f"   Step {step_eval.step}: {step_eval.score}/10")
            print(f"   理由: {step_eval.reason}")
            print()
    else:
        print(f"✗ 评估失败")
        print(f"   错误: {response.error}")
    
    # 6. 查询评估结果
    print("\n[6] 从数据库查询评估结果...")
    
    if response.success:
        stored_result = await db_manager.get_trajectory_evaluation(
            evaluation_id=response.evaluation_id
        )
        
        if stored_result:
            print(f"✓ 查询成功")
            print(f"   评估时间: {stored_result.evaluated_at}")
            print(f"   评估模型: {stored_result.evaluator_model}")
            print(f"   Prompt 版本: {stored_result.evaluation_prompt_version}")
        else:
            print(f"✗ 查询失败")
    
    # 7. 清理
    print("\n[7] 清理资源...")
    await close_database()
    print("✓ 测试完成")
    
    print("\n" + "=" * 60)


async def test_api_integration():
    """测试 API 集成"""
    
    print("\n" + "=" * 60)
    print("API 集成测试")
    print("=" * 60)
    
    print("\n提示：请先启动服务（python run.py），然后运行以下命令测试 API：")
    print("\n1. 触发评估：")
    print("""
curl -X POST "http://localhost:8000/api/v1/evaluation/evaluate" \\
  -H "Content-Type: application/json" \\
  -d '{
    "agent_id": "risk-agent-001",
    "user_id": "user-12345",
    "session_id": "session-test-001",
    "force_reevaluate": false
  }'
""")
    
    print("\n2. 查询评估结果：")
    print("""
curl -X GET "http://localhost:8000/api/v1/evaluation/result/1"
""")
    
    print("\n3. 查询评估结果列表：")
    print("""
curl -X GET "http://localhost:8000/api/v1/evaluation/results?agent_id=risk-agent-001"
""")


if __name__ == "__main__":
    print("\n选择测试模式：")
    print("1. 完整流程测试（需要配置 LLM API）")
    print("2. API 集成测试说明")
    
    choice = input("\n请输入选项 (1/2): ").strip()
    
    if choice == "1":
        asyncio.run(test_evaluation_system())
    elif choice == "2":
        asyncio.run(test_api_integration())
    else:
        print("无效选项")
