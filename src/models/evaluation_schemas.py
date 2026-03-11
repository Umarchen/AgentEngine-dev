"""
评估相关的数据模型
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ==================== 评估相关模型 ====================

class StepEvaluation(BaseModel):
    """单步骤评估结果"""
    step: int = Field(..., description="步骤编号，从0开始")
    score: int = Field(..., ge=0, le=10, description="步骤得分(0-10)")
    reason: str = Field(..., description="步骤打分依据")
    
    class Config:
        json_schema_extra = {
            "example": {
                "step": 0,
                "score": 7,
                "reason": "执行结果正常，信号捕捉准确"
            }
        }


class OverallEvaluation(BaseModel):
    """整体评估结果"""
    score: int = Field(..., ge=0, le=10, description="整体得分(0-10)")
    reason: str = Field(..., description="整体打分依据")
    
    class Config:
        json_schema_extra = {
            "example": {
                "score": 7,
                "reason": "整体逻辑合理，风险识别准确"
            }
        }


class Evaluation(BaseModel):
    """完整评估结果"""
    overall: OverallEvaluation = Field(..., description="整体打分结果")
    steps: List[StepEvaluation] = Field(..., description="每个步骤的打分结果")
    
    class Config:
        json_schema_extra = {
            "example": {
                "overall": {
                    "score": 7,
                    "reason": "整体逻辑合理"
                },
                "steps": [
                    {
                        "step": 0,
                        "score": 7,
                        "reason": "执行结果正常"
                    }
                ]
            }
        }


class TrajectoryEvaluationRecord(BaseModel):
    """轨迹评估记录（用于数据库存储）"""
    id: Optional[int] = Field(default=None, description="记录ID（数据库自增）")
    agent_id: str = Field(..., description="Agent的唯一标识符")
    user_id: str = Field(..., description="用户ID")
    session_id: str = Field(..., description="会话ID")
    trajectory: Dict[str, Any] = Field(..., description="智能体运行轨迹（从数据库查询汇总）")
    evaluation: Evaluation = Field(..., description="评估结果")
    evaluated_at: datetime = Field(default_factory=datetime.now, description="评估时间")
    evaluator_model: str = Field(default="", description="使用的评估模型名称")
    evaluation_prompt_version: str = Field(default="v1.0", description="评估Prompt版本")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "agent_id": "agent-550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user-12345",
                "session_id": "agent-session-550e8400",
                "trajectory": {
                    "steps": [
                        {
                            "step": 0,
                            "state": "初始状态：收到风险评估请求",
                            "action": "查询企业基本信息",
                            "reward": 0,
                            "next_state": "获取到企业注册信息",
                            "is_terminal": False
                        }
                    ]
                },
                "evaluation": {
                    "overall": {
                        "score": 7,
                        "reason": "整体逻辑合理"
                    },
                    "steps": [
                        {
                            "step": 0,
                            "score": 7,
                            "reason": "执行结果正常"
                        }
                    ]
                },
                "evaluated_at": "2026-01-23T10:00:00",
                "evaluator_model": "deepseek-chat",
                "evaluation_prompt_version": "v1.0"
            }
        }


class EvaluationRequest(BaseModel):
    """评估请求模型"""
    agent_id: str = Field(..., description="Agent的唯一标识符")
    user_id: str = Field(..., description="用户ID")
    session_id: str = Field(..., description="会话ID")
    force_reevaluate: bool = Field(default=False, description="是否强制重新评估（即使已存在评估结果）")
    
    class Config:
        json_schema_extra = {
            "example": {
                "agent_id": "agent-550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user-12345",
                "session_id": "agent-session-550e8400",
                "force_reevaluate": False
            }
        }


class EvaluationResponse(BaseModel):
    """评估响应模型"""
    success: bool = Field(..., description="评估是否成功")
    message: str = Field(..., description="响应消息")
    evaluation_id: Optional[int] = Field(default=None, description="评估记录ID")
    evaluation: Optional[Evaluation] = Field(default=None, description="评估结果")
    error: Optional[str] = Field(default=None, description="错误信息")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "评估完成",
                "evaluation_id": 1,
                "evaluation": {
                    "overall": {
                        "score": 7,
                        "reason": "整体逻辑合理"
                    },
                    "steps": [
                        {
                            "step": 0,
                            "score": 7,
                            "reason": "执行结果正常"
                        }
                    ]
                },
                "error": None
            }
        }


# ==================== LLM 配置模型 ====================

class LLMConfig(BaseModel):
    """LLM 配置"""
    provider: str = Field(..., description="模型提供商: gateway/openai/deepseek/qwen/gemini")
    model_name: str = Field(..., description="模型名称")
    api_key: Optional[str] = Field(default=None, description="API密钥")
    api_base: Optional[str] = Field(default=None, description="API基础URL")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")
    max_tokens: int = Field(default=2000, ge=1, description="最大token数")
    timeout: int = Field(default=60, ge=1, description="超时时间（秒）")
    
    class Config:
        json_schema_extra = {
            "example": {
                "provider": "deepseek",
                "model_name": "deepseek-chat",
                "api_key": "sk-xxx",
                "api_base": "https://api.deepseek.com/v1",
                "temperature": 0.7,
                "max_tokens": 2000,
                "timeout": 60
            }
        }
