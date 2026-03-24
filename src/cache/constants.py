"""
缓存常量定义模块
定义缓存键前缀、TTL 等常量
"""

from typing import Dict


class CacheKeys:
    """缓存键构建常量"""
    
    # 全局命名空间前缀
    PREFIX = "agent_engine"
    
    # 缓存键命名空间
    NAMESPACE_AGENT = "agent"
    NAMESPACE_SESSION = "session"
    NAMESPACE_TEMPLATE = "template"
    NAMESPACE_SKILL = "skill"
    NAMESPACE_EVAL = "eval"
    
    @staticmethod
    def agent_config(agent_id: str) -> str:
        """
        Agent 配置缓存键
        
        Args:
            agent_id: Agent 包ID
            
        Returns:
            完整缓存键
        """
        return f"{CacheKeys.PREFIX}:agent:config:{agent_id}"
    
    @staticmethod
    def agent_template(template_id: str) -> str:
        """
        Agent 模板缓存键
        
        Args:
            template_id: 模板ID
            
        Returns:
            完整缓存键
        """
        return f"{CacheKeys.PREFIX}:template:config:{template_id}"
    
    @staticmethod
    def session_history(session_id: str) -> str:
        """
        会话历史缓存键
        
        Args:
            session_id: 会话ID
            
        Returns:
            完整缓存键
        """
        return f"{CacheKeys.PREFIX}:session:history:{session_id}"
    
    @staticmethod
    def skill_info(skill_name: str) -> str:
        """
        技能信息缓存键
        
        Args:
            skill_name: 技能名称
            
        Returns:
            完整缓存键
        """
        return f"{CacheKeys.PREFIX}:skill:info:{skill_name}"
    
    @staticmethod
    def agent_type(type_id: str) -> str:
        """
        Agent 类型缓存键
        
        Args:
            type_id: 类型ID
            
        Returns:
            完整缓存键
        """
        return f"{CacheKeys.PREFIX}:agent_type:{type_id}"


class CacheTTL:
    """缓存 TTL 常量（单位：秒）"""
    
    # Agent 配置：1 小时
    AGENT_CONFIG = 3600
    
    # Agent 模板：24 小时
    AGENT_TEMPLATE = 86400
    
    # 会话历史：30 分钟
    SESSION_HISTORY = 1800
    
    # 技能信息：1 小时
    SKILL_INFO = 3600
    
    # 评估结果：7 天
    EVALUATION_RESULT = 604800
    
    # Agent 类型：24 小时
    AGENT_TYPE = 86400
    
    # 空值缓存：5 分钟
    NULL_VALUE = 300
    
    # 分布式锁：10 秒
    LOCK = 10


class CacheConfig:
    """缓存配置常量"""
    
    # Redis 连接池配置
    MAX_CONNECTIONS = 50
    SOCKET_TIMEOUT = 5  # 秒
    SOCKET_CONNECT_TIMEOUT = 3  # 秒
    
    # 重试配置
    MAX_RETRIES = 3
    RETRY_WAIT_BASE = 1  # 秒
    RETRY_WAIT_MAX = 10  # 秒
    
    # 缓存键配置
    MAX_KEY_LENGTH = 1024  # 1KB 限制
    
    # TTL 随机偏移百分比
    TTL_JITTER_PERCENT = 10  # ±10%
    
    # 降级超时
    DEGRADATION_TIMEOUT = 3  # 秒
    
    # 预热配置
    WARMUP_DELAY_SECONDS = 30  # 启动后延迟 30 秒开始预热


# 缓存键命名空间映射
CACHE_NAMESPACES: Dict[str, str] = {
    "config": CacheKeys.NAMESPACE_AGENT,
    "template": CacheKeys.NAMESPACE_TEMPLATE,
    "session": CacheKeys.NAMESPACE_SESSION,
    "skill": CacheKeys.NAMESPACE_SKILL,
    "eval": CacheKeys.NAMESPACE_EVAL,
}
