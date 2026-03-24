"""
缓存键构建器模块
负责构建和验证缓存键
"""

import hashlib
from urllib.parse import quote
from typing import Optional

from loguru import logger

from .constants import CacheKeys, CacheConfig


class CacheKeyBuilder:
    """
    安全的缓存键构建器
    
    功能：
    1. 添加全局前缀
    2. URL 编码特殊字符（避免冲突）
    3. 长度限制验证
    """
    
    def __init__(self, prefix: Optional[str] = None):
        """
        初始化缓存键构建器
        
        Args:
            prefix: 自定义前缀（默认使用 CacheKeys.PREFIX）
        """
        self.prefix = prefix or CacheKeys.PREFIX
        self.max_length = CacheConfig.MAX_KEY_LENGTH
    
    def build(self, raw_key: str) -> str:
        """
        构建安全的缓存键
        
        Args:
            raw_key: 原始键
            
        Returns:
            完整的安全缓存键
        """
        # 1. URL 编码（避免特殊字符冲突）
        # 保留冒号（:）因为它是 Redis 层级分隔符
        encoded_key = quote(raw_key, safe=':')
        
        # 2. 添加前缀
        full_key = f"{self.prefix}:{encoded_key}"
        
        # 3. 长度验证
        if len(full_key) > self.max_length:
            # 超过限制，使用哈希后缀
            hash_suffix = hashlib.md5(full_key.encode()).hexdigest()[:16]
            full_key = f"{self.prefix}:truncated:{hash_suffix}"
            
            logger.warning(
                f"缓存键过长（{len(full_key)} > {self.max_length}），已截断: "
                f"{full_key[:100]}..."
            )
        
        return full_key
    
    def build_pattern(self, pattern: str) -> str:
        """
        构建模式匹配键（用于批量操作）
        
        Args:
            pattern: 匹配模式（如 agent:config:*）
            
        Returns:
            完整的模式键
        """
        # 模式匹配时，只编码非通配符部分
        if '*' in pattern:
            # 简单处理：直接添加前缀
            return f"{self.prefix}:{pattern}"
        else:
            return self.build(pattern)
    
    @staticmethod
    def agent_config(agent_id: str) -> str:
        """
        构建 Agent 配置缓存键
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            缓存键
        """
        return CacheKeys.agent_config(agent_id)
    
    @staticmethod
    def agent_template(template_id: str) -> str:
        """
        构建 Agent 模板缓存键
        
        Args:
            template_id: 模板ID
            
        Returns:
            缓存键
        """
        return CacheKeys.agent_template(template_id)
    
    @staticmethod
    def session_history(session_id: str) -> str:
        """
        构建会话历史缓存键
        
        Args:
            session_id: 会话ID
            
        Returns:
            缓存键
        """
        return CacheKeys.session_history(session_id)
    
    @staticmethod
    def skill_info(skill_name: str) -> str:
        """
        构建技能信息缓存键
        
        Args:
            skill_name: 技能名称
            
        Returns:
            缓存键
        """
        return CacheKeys.skill_info(skill_name)
    
    @staticmethod
    def agent_type(type_id: str) -> str:
        """
        构建 Agent 类型缓存键
        
        Args:
            type_id: 类型ID
            
        Returns:
            缓存键
        """
        return CacheKeys.agent_type(type_id)
    
    def validate(self, key: str) -> bool:
        """
        验证缓存键是否有效
        
        Args:
            key: 缓存键
            
        Returns:
            是否有效
        """
        if not key:
            return False
        
        # 检查长度
        if len(key) > self.max_length:
            return False
        
        # 检查是否包含非法字符
        # Redis 键可以包含大部分字符，但建议避免空格和控制字符
        forbidden_chars = ['\n', '\r', '\t', ' ']
        if any(char in key for char in forbidden_chars):
            return False
        
        return True
