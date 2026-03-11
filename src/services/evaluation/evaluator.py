"""
轨迹评估器
核心评估逻辑实现
"""

import asyncio
import json
import re
from typing import Dict, Any, Optional, List
from datetime import datetime

from loguru import logger

from src.models.evaluation_schemas import (
    EvaluationRequest,
    EvaluationResponse,
    TrajectoryEvaluationRecord,
    Evaluation,
    OverallEvaluation,
    StepEvaluation,
    LLMConfig
)
from src.database.database import DatabaseManager, get_database_manager
from .llm_client import LLMClientFactory, BaseLLMClient, load_llm_config_from_yaml
from .prompt_manager import PromptManager


class TrajectoryEvaluator:
    """
    轨迹评估器
    
    功能：
    1. 接收评估请求（agent_id, session_id, user_id）
    2. 从数据库查询轨迹信息
    3. 调用 LLM 进行评估
    4. 将评估结果存入数据库
    """
    
    _instance: Optional["TrajectoryEvaluator"] = None
    
    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        llm_config: Optional[LLMConfig] = None,
        config_path: str = "config/evaluation_config.yaml"
    ):
        """
        初始化评估器
        
        Args:
            db_manager: 数据库管理器
            llm_config: LLM 配置（如果为 None，从配置文件加载）
            config_path: 配置文件路径
        """
        self._db_manager = db_manager or get_database_manager()
        
        # 加载 LLM 配置
        if llm_config is None:
            llm_config = load_llm_config_from_yaml(config_path)
        
        # 创建 LLM 客户端
        self._llm_client: BaseLLMClient = LLMClientFactory.create_client(llm_config)
        self._llm_config = llm_config
        
        # 加载 Prompt 管理器
        self._prompt_manager = PromptManager(config_path)
        
        logger.info(
            f"轨迹评估器初始化完成 - "
            f"Provider: {llm_config.provider}, "
            f"Model: {llm_config.model_name}"
        )
    
    @classmethod
    def get_instance(
        cls,
        db_manager: Optional[DatabaseManager] = None,
        llm_config: Optional[LLMConfig] = None,
        config_path: str = "config/evaluation_config.yaml"
    ) -> "TrajectoryEvaluator":
        """获取评估器单例"""
        if cls._instance is None:
            cls._instance = cls(db_manager, llm_config, config_path)
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._instance = None
    
    async def notify_trajectory_ready(
        self,
        agent_id: str,
        user_id: str,
        session_id: str,
        force_reevaluate: bool = False
    ) -> Dict[str, Any]:
        """
        通知轨迹已写入数据库（异步通知接口）
        
        这是提供给其他组件调用的通知接口。
        其他组件在轨迹写入数据库完成后，调用此接口通知评估器。
        
        接口特点：
        1. 立即返回，不等待评估完成
        2. 评估在后台异步进行
        3. 评估结果写入 T_AGENT_TRAJECTORY_EVALUATION 表
        4. 其他组件通过查询该表获取评估结果
        
        Args:
            agent_id: Agent ID
            user_id: 用户 ID
            session_id: 会话 ID
            force_reevaluate: 是否强制重新评估（默认 False）
            
        Returns:
            通知响应（立即返回）
            {
                "success": True,
                "message": "评估任务已启动",
                "agent_id": "...",
                "user_id": "...",
                "session_id": "..."
            }
        """
        logger.info(
            f"收到轨迹就绪通知 - agent_id: {agent_id}, "
            f"user_id: {user_id}, session_id: {session_id}"
        )
        
        # 创建后台评估任务，不等待完成
        asyncio.create_task(
            self._evaluate_trajectory_background(
                agent_id=agent_id,
                user_id=user_id,
                session_id=session_id,
                force_reevaluate=force_reevaluate
            )
        )
        
        # 立即返回
        return {
            "success": True,
            "message": "评估任务已启动，结果将写入数据库",
            "agent_id": agent_id,
            "user_id": user_id,
            "session_id": session_id
        }
    
    async def _evaluate_trajectory_background(
        self,
        agent_id: str,
        user_id: str,
        session_id: str,
        force_reevaluate: bool = False
    ) -> None:
        """
        后台评估任务
        
        在后台异步执行评估，不阻塞调用方。
        评估完成后将结果写入数据库。
        """
        try:
            logger.info(f"开始后台评估 - session_id: {session_id}")
            
            # 1. 检查是否已存在评估结果
            if not force_reevaluate:
                existing = await self._db_manager.get_trajectory_evaluation(
                    agent_id=agent_id,
                    user_id=user_id,
                    session_id=session_id
                )
                if existing:
                    logger.info(f"评估结果已存在，跳过评估 - evaluation_id: {existing.id}")
                    return
            
            # 2. 从数据库查询轨迹信息
            trajectories = await self._fetch_trajectories(agent_id, user_id, session_id)
            
            if not trajectories:
                logger.warning(f"未找到轨迹数据 - session_id: {session_id}")
                return
            
            # 3. 汇总轨迹步骤
            aggregated_trajectory = self._aggregate_trajectories(trajectories)
            
            # 4. 调用 LLM 进行评估
            evaluation = await self._evaluate_with_llm(
                agent_id=agent_id,
                user_id=user_id,
                session_id=session_id,
                trajectory=aggregated_trajectory
            )
            
            # 5. 保存评估结果到数据库
            evaluation_record = TrajectoryEvaluationRecord(
                agent_id=agent_id,
                user_id=user_id,
                session_id=session_id,
                trajectory=aggregated_trajectory,
                evaluation=evaluation,
                evaluated_at=datetime.now(),
                evaluator_model=self._llm_config.model_name,
                evaluation_prompt_version=self._prompt_manager.get_prompt_version()
            )
            
            evaluation_id = await self._db_manager.save_trajectory_evaluation(evaluation_record)
            
            logger.info(
                f"后台评估完成 - session_id: {session_id}, "
                f"evaluation_id: {evaluation_id}, "
                f"score: {evaluation.overall.score}/10"
            )
            
        except Exception as e:
            logger.error(f"后台评估失败 - session_id: {session_id}: {e}")
            logger.exception("详细错误信息:")
    
    async def evaluate_trajectory(
        self,
        agent_id: str,
        user_id: str,
        session_id: str,
        force_reevaluate: bool = False
    ) -> EvaluationResponse:
        """
        评估轨迹（主入口函数）
        
        这是提供给其他组件调用的接口函数。
        其他组件在轨迹写入数据库完成后，调用此函数通知评估器进行评估。
        
        Args:
            agent_id: Agent ID
            user_id: 用户 ID
            session_id: 会话 ID
            force_reevaluate: 是否强制重新评估
            
        Returns:
            评估响应
        """
        logger.info(
            f"收到评估请求 - agent_id: {agent_id}, "
            f"user_id: {user_id}, session_id: {session_id}"
        )
        
        try:
            # 1. 检查是否已存在评估结果
            if not force_reevaluate:
                existing = await self._db_manager.get_trajectory_evaluation(
                    agent_id=agent_id,
                    user_id=user_id,
                    session_id=session_id
                )
                if existing:
                    logger.info(f"评估结果已存在，直接返回: {existing.id}")
                    return EvaluationResponse(
                        success=True,
                        message="评估结果已存在",
                        evaluation_id=existing.id,
                        evaluation=existing.evaluation
                    )
            
            # 2. 从数据库查询轨迹信息
            trajectories = await self._fetch_trajectories(agent_id, user_id, session_id)
            
            if not trajectories:
                return EvaluationResponse(
                    success=False,
                    message="未找到轨迹信息",
                    error="数据库中不存在对应的轨迹记录"
                )
            
            # 3. 汇总轨迹步骤
            aggregated_trajectory = self._aggregate_trajectories(trajectories)
            
            # 4. 调用 LLM 进行评估
            evaluation = await self._evaluate_with_llm(
                agent_id=agent_id,
                user_id=user_id,
                session_id=session_id,
                trajectory=aggregated_trajectory
            )
            
            # 5. 保存评估结果到数据库
            evaluation_record = TrajectoryEvaluationRecord(
                agent_id=agent_id,
                user_id=user_id,
                session_id=session_id,
                trajectory=aggregated_trajectory,
                evaluation=evaluation,
                evaluated_at=datetime.now(),
                evaluator_model=self._llm_config.model_name,
                evaluation_prompt_version=self._prompt_manager.get_prompt_version()
            )
            
            evaluation_id = await self._db_manager.save_trajectory_evaluation(evaluation_record)
            
            logger.info(f"评估完成并保存 - evaluation_id: {evaluation_id}")
            
            return EvaluationResponse(
                success=True,
                message="评估完成",
                evaluation_id=evaluation_id,
                evaluation=evaluation
            )
            
        except Exception as e:
            logger.error(f"评估失败: {e}", exc_info=True)
            return EvaluationResponse(
                success=False,
                message="评估失败",
                error=str(e)
            )
    
    async def _fetch_trajectories(
        self,
        agent_id: str,
        user_id: str,
        session_id: str
    ) -> List[Dict[str, Any]]:
        """
        从数据库查询轨迹信息
        
        Args:
            agent_id: Agent ID
            user_id: 用户 ID
            session_id: 会话 ID
            
        Returns:
            轨迹记录列表
        """
        try:
            # 调用数据库管理器查询轨迹
            trajectories = await self._db_manager.get_trajectory_history(
                agent_id=agent_id,
                session_id=session_id,
                limit=1000  # 获取所有相关轨迹
            )
            
            # 过滤出匹配 user_id 的记录
            filtered = [
                t for t in trajectories
                if t.user_id == user_id
            ]
            
            logger.info(f"查询到 {len(filtered)} 条轨迹记录")
            return [t.model_dump() for t in filtered]
            
        except Exception as e:
            logger.error(f"查询轨迹失败: {e}")
            raise
    
    def _aggregate_trajectories(
        self,
        trajectories: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        汇总轨迹步骤
        
        将多条轨迹记录的 steps 合并成一个完整的轨迹
        
        Args:
            trajectories: 轨迹记录列表
            
        Returns:
            汇总后的轨迹数据
        """
        all_steps = []
        
        for traj in trajectories:
            trajectory_obj = traj.get("trajectory", {})
            steps = trajectory_obj.get("steps", [])
            all_steps.extend(steps)
        
        # 按 step 编号排序
        all_steps.sort(key=lambda x: x.get("step", 0))
        
        # 重新编号（确保连续）
        for idx, step in enumerate(all_steps):
            step["step"] = idx
        
        aggregated = {
            "steps": all_steps
        }
        
        logger.info(f"汇总轨迹步骤: 共 {len(all_steps)} 步")
        return aggregated
    
    async def _evaluate_with_llm(
        self,
        agent_id: str,
        user_id: str,
        session_id: str,
        trajectory: Dict[str, Any]
    ) -> Evaluation:
        """
        使用 LLM 进行评估
        
        Args:
            agent_id: Agent ID
            user_id: 用户 ID
            session_id: 会话 ID
            trajectory: 轨迹数据
            
        Returns:
            评估结果
        """
        try:
            # 1. 构建 Prompt
            system_prompt = self._prompt_manager.get_system_prompt()
            
            user_prompt = self._prompt_manager.build_user_prompt(
                agent_id=agent_id,
                user_id=user_id,
                session_id=session_id,
                trajectory=trajectory
            )
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            # 2. 调用 LLM
            response_text = await self._llm_client.chat_completion(messages)
            
            # 3. 解析 LLM 响应
            evaluation = self._parse_llm_response(response_text, trajectory)
            
            return evaluation
            
        except Exception as e:
            logger.error(f"LLM 评估失败: {e}")
            logger.exception("详细错误信息:")
            raise
    
    def _parse_llm_response(
        self,
        response_text: str,
        trajectory: Dict[str, Any]
    ) -> Evaluation:
        """
        解析 LLM 响应
        
        Args:
            response_text: LLM 返回的文本
            trajectory: 原始轨迹数据（用于补全缺失的步骤评估）
            
        Returns:
            评估结果对象
        """
        try:
            # 尝试提取 JSON 内容
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 尝试查找 JSON 对象（以 { 开始，以 } 结束）
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    # 尝试直接解析整个响应
                    json_str = response_text.strip()
            
            # 清理 JSON 字符串（移除可能的注释和多余空白）
            json_str = re.sub(r'//.*?\n', '\n', json_str)  # 移除单行注释
            json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)  # 移除多行注释
            
            # 尝试修复被截断的 JSON
            # 如果 JSON 以不完整的字符串结尾，尝试补全
            if not json_str.rstrip().endswith('}'):
                logger.warning("检测到 JSON 可能被截断，尝试修复...")
                
                # 策略1: 找到最后一个完整的步骤对象
                last_complete_step = json_str.rfind('},')
                if last_complete_step > 0:
                    # 检查是否在 steps 数组中
                    if '"steps"' in json_str[:last_complete_step]:
                        # 截取到最后一个完整的步骤，并补全结构
                        json_str = json_str[:last_complete_step + 1] + ']}'
                        logger.warning(f"已修复 JSON：截取到最后一个完整的步骤对象")
                    else:
                        # 可能在 overall 部分被截断
                        # 尝试找到 overall 的结束
                        overall_end = json_str.find('},"steps"')
                        if overall_end > 0:
                            json_str = json_str[:overall_end + 1] + ',"steps":[]}'
                            logger.warning(f"已修复 JSON：overall 被截断，使用空 steps")
                
                # 策略2: 如果是字符串值被截断（缺少结束引号）
                # 查找最后一个 "reason": " 后面是否缺少结束引号
                reason_pattern = r'"reason"\s*:\s*"([^"]*?)$'
                match = re.search(reason_pattern, json_str)
                if match:
                    # 补全结束引号和后续结构
                    json_str = json_str + '"}]}'
                    logger.warning(f"已修复 JSON：补全被截断的 reason 字段")
            
            # 解析 JSON
            evaluation_data = json.loads(json_str)
            
            # 验证和补全
            overall_data = evaluation_data.get("overall", {})
            steps_data = evaluation_data.get("steps", [])
            
            # 确保所有步骤都有评估
            expected_steps = len(trajectory.get("steps", []))
            if len(steps_data) < expected_steps:
                logger.warning(f"LLM 返回的步骤评估不完整: {len(steps_data)}/{expected_steps}")
                # 补全缺失的步骤评估
                for i in range(len(steps_data), expected_steps):
                    steps_data.append({
                        "step": i,
                        "score": 5,
                        "reason": "LLM 未提供评估，使用默认分数"
                    })
            
            # 构建评估对象
            evaluation = Evaluation(
                overall=OverallEvaluation(
                    score=overall_data.get("score", 5),
                    reason=overall_data.get("reason", "无评估理由")
                ),
                steps=[
                    StepEvaluation(
                        step=step_data.get("step", idx),
                        score=step_data.get("score", 5),
                        reason=step_data.get("reason", "无评估理由")
                    )
                    for idx, step_data in enumerate(steps_data)
                ]
            )
            
            logger.info(
                f"解析评估结果成功 - 总分: {evaluation.overall.score}, "
                f"步骤数: {len(evaluation.steps)}"
            )
            
            return evaluation
            
        except json.JSONDecodeError as e:
            logger.error(f"解析 LLM 响应 JSON 失败: {e}")
            
            # 保存原始响应到文件，方便调试
            import os
            from datetime import datetime
            debug_dir = "debug_llm_responses"
            os.makedirs(debug_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{debug_dir}/llm_response_{timestamp}.txt"
            
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write("=" * 80 + "\n")
                    f.write(f"时间: {datetime.now()}\n")
                    f.write(f"错误: {e}\n")
                    f.write("=" * 80 + "\n\n")
                    f.write("完整 LLM 响应:\n\n")
                    f.write(response_text)
                    f.write("\n\n" + "=" * 80 + "\n")
                
                logger.error(f"LLM 原始响应已保存到文件: {filename}")
            except Exception as save_error:
                logger.error(f"保存 LLM 响应到文件失败: {save_error}")
            
            # 返回默认评估
            return self._create_default_evaluation(trajectory)
        except Exception as e:
            logger.error(f"解析 LLM 响应失败: {e}")
            return self._create_default_evaluation(trajectory)
    
    def _create_default_evaluation(self, trajectory: Dict[str, Any]) -> Evaluation:
        """创建默认评估结果（当解析失败时）"""
        steps = trajectory.get("steps", [])
        return Evaluation(
            overall=OverallEvaluation(
                score=5,
                reason="评估失败，使用默认分数"
            ),
            steps=[
                StepEvaluation(
                    step=idx,
                    score=5,
                    reason="评估失败，使用默认分数"
                )
                for idx in range(len(steps))
            ]
        )


# 全局评估器实例
_trajectory_evaluator: Optional[TrajectoryEvaluator] = None


def get_trajectory_evaluator() -> TrajectoryEvaluator:
    """获取全局评估器实例"""
    global _trajectory_evaluator
    if _trajectory_evaluator is None:
        _trajectory_evaluator = TrajectoryEvaluator.get_instance()
    return _trajectory_evaluator


async def init_trajectory_evaluator(
    db_manager: Optional[DatabaseManager] = None,
    llm_config: Optional[LLMConfig] = None,
    config_path: str = "config/evaluation_config.yaml"
) -> TrajectoryEvaluator:
    """
    初始化评估器
    
    Args:
        db_manager: 数据库管理器
        llm_config: LLM 配置
        config_path: 配置文件路径
        
    Returns:
        评估器实例
    """
    global _trajectory_evaluator
    _trajectory_evaluator = TrajectoryEvaluator(db_manager, llm_config, config_path)
    return _trajectory_evaluator
