"""
Prompt 管理器
负责加载和管理评估 Prompt
"""

import json
import os
from pathlib import Path
from typing import Dict, Any

import yaml
from loguru import logger


class PromptManager:
    """
    Prompt 管理器
    从配置文件加载评估 Prompt 模板
    """
    
    def __init__(self, config_path: str = "config/evaluation_config.yaml"):
        """
        初始化 Prompt 管理器
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self) -> None:
        """从配置文件加载配置"""
        try:
            # 支持相对路径和绝对路径
            if not os.path.isabs(self.config_path):
                # 相对于项目根目录
                project_root = Path(__file__).parent.parent.parent.parent
                config_file = project_root / self.config_path
            else:
                config_file = Path(self.config_path)
            
            if not config_file.exists():
                logger.warning(f"配置文件不存在: {config_file}，使用默认配置")
                self._use_default_config()
                return
            
            with open(config_file, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
            
            logger.info(f"成功加载评估配置: {config_file}")
            
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}，使用默认配置")
            self._use_default_config()
    
    def _use_default_config(self) -> None:
        """使用默认配置"""
        self.config = {
            "evaluation_prompt": {
                "version": "v1.0",
                "system_prompt": "你是一位银行贷后资产保全专家，负责评估AI智能体的执行轨迹。",
                "user_prompt_template": """
请对以下智能体的执行轨迹进行评估和打分。

## 智能体信息
- Agent ID: {agent_id}
- User ID: {user_id}
- Session ID: {session_id}

## 执行轨迹
{trajectory_json}

## 评估要求
1. 对每个步骤（step）进行评估，给出0-10分的评分和评分理由
2. 对整体执行过程进行评估，给出0-10分的总分和总体评价

## 输出格式
请严格按照以下 JSON 格式输出评估结果：

```json
{
  "overall": {
    "score": <0-10的整数>,
    "reason": "<整体评价理由>"
  },
  "steps": [
    {
      "step": 0,
      "score": <0-10的整数>,
      "reason": "<该步骤的评分理由>"
    }
  ]
}
```
"""
            }
        }
    
    def get_system_prompt(self) -> str:
        """获取系统 Prompt"""
        return self.config.get("evaluation_prompt", {}).get("system_prompt", "")
    
    def get_user_prompt_template(self) -> str:
        """获取用户 Prompt 模板"""
        return self.config.get("evaluation_prompt", {}).get("user_prompt_template", "")
    
    def get_prompt_version(self) -> str:
        """获取 Prompt 版本"""
        return self.config.get("evaluation_prompt", {}).get("version", "v1.0")
    
    def build_user_prompt(
        self,
        agent_id: str,
        user_id: str,
        session_id: str,
        trajectory: Dict[str, Any]
    ) -> str:
        """
        构建用户 Prompt
        
        Args:
            agent_id: Agent ID
            user_id: 用户 ID
            session_id: 会话 ID
            trajectory: 轨迹数据
            
        Returns:
            构建好的用户 Prompt
        """
        template = self.get_user_prompt_template()
        
        # 将轨迹转换为格式化的 JSON 字符串
        trajectory_json = json.dumps(trajectory, ensure_ascii=False, indent=2)
        
        # 使用 replace 方法替换占位符,避免 format() 对花括号的解析问题
        user_prompt = template.replace("{agent_id}", agent_id)
        user_prompt = user_prompt.replace("{user_id}", user_id)
        user_prompt = user_prompt.replace("{session_id}", session_id)
        user_prompt = user_prompt.replace("{trajectory_json}", trajectory_json)
        
        return user_prompt
    
    def reload_config(self) -> None:
        """重新加载配置"""
        logger.info("重新加载评估配置...")
        self._load_config()
