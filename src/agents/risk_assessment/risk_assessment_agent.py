"""
Risk Assessment Agent implementation
"""

import asyncio
from typing import Any, Dict, List

from loguru import logger

from src.core.base import BaseAgent, AgentRegistry
from src.models.schemas import AgentConfig, ContextContent, Trajectory, TrajectoryStep


@AgentRegistry.register("risk-assessment")
class RiskAssessmentAgent(BaseAgent):
    """
    风险评估 Agent 示例
    用于演示更复杂的 Agent 实现
    """

    def __init__(self, config: str):
        """初始化 RiskAssessmentAgent"""
        super().__init__(config)

    async def invoke(
        self,
        input_data: Dict[str, Any],
        history: List[Dict] = None
    ) -> Any:
        """
        执行风险评估任务
        """
        logger.info(f"RiskAssessmentAgent 执行任务")

        query = input_data
        enterprise_name = "未知企业"

        await asyncio.sleep(0.2)

        await asyncio.sleep(0.2)

        # 模拟风险评估结果
        import random
        risk_score = random.randint(1, 100)

        if risk_score < 30:
            risk_level = "低风险"
            recommendation = "该企业财务状况良好，建议正常合作"
        elif risk_score < 70:
            risk_level = "中等风险"
            recommendation = "该企业存在一定风险，建议谨慎评估后决策"
        else:
            risk_level = "高风险"
            recommendation = "该企业风险较高，建议加强尽职调查"

        response = {"role": "risk assessment agent", "content": f"Risk Assessment Agent 收到您的消息: {query}"}

        # 最终步骤

        logger.info(f"RiskAssessmentAgent 任务完成: {enterprise_name} - {risk_level}")

        return [query, response]
