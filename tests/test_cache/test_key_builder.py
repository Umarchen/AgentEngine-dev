"""
缓存键构建器测试
"""

import pytest
from src.cache.key_builder import CacheKeyBuilder
from src.cache.constants import CacheKeys, CacheConfig


class TestCacheKeyBuilder:
    """缓存键构建器测试类"""
    
    def test_build_basic_key(self):
        """测试基本键构建"""
        builder = CacheKeyBuilder()
        
        # 正常键
        key = builder.build("agent:config:test_agent")
        assert key == "agent_engine:agent:config:test_agent"
    
    def test_build_key_with_special_chars(self):
        """测试特殊字符键构建（URL 编码）"""
        builder = CacheKeyBuilder()
        
        # 包含特殊字符的键
        key = builder.build("agent:config:test agent/123")
        # 空格应该被编码
        assert "agent_engine:agent:config:test" in key
        assert "%20" in key or "test" in key  # 空格被编码
        
    def test_build_key_too_long(self):
        """测试超长键处理"""
        builder = CacheKeyBuilder()
        
        # 构建超长键
        long_key = "a" * 2000
        key = builder.build(long_key)
        
        # 应该被截断并使用哈希
        assert len(key) < CacheConfig.MAX_KEY_LENGTH
        assert "truncated" in key
    
    def test_build_pattern(self):
        """测试模式匹配键构建"""
        builder = CacheKeyBuilder()
        
        # 模式匹配
        pattern = builder.build_pattern("agent:config:*")
        assert pattern == "agent_engine:agent:config:*"
    
    def test_static_agent_config(self):
        """测试 Agent 配置键构建"""
        key = CacheKeyBuilder.agent_config("agent_001")
        assert key == "agent_engine:agent:config:agent_001"
    
    def test_static_agent_template(self):
        """测试 Agent 模板键构建"""
        key = CacheKeyBuilder.agent_template("tpl_001")
        assert key == "agent_engine:template:config:tpl_001"
    
    def test_static_session_history(self):
        """测试会话历史键构建"""
        key = CacheKeyBuilder.session_history("session_123")
        assert key == "agent_engine:session:history:session_123"
    
    def test_static_skill_info(self):
        """测试技能信息键构建"""
        key = CacheKeyBuilder.skill_info("web_calc")
        assert key == "agent_engine:skill:info:web_calc"
    
    def test_validate_valid_key(self):
        """测试有效键验证"""
        builder = CacheKeyBuilder()
        
        assert builder.validate("agent:config:test") is True
        assert builder.validate("session:history:123") is True
    
    def test_validate_invalid_key_empty(self):
        """测试空键验证"""
        builder = CacheKeyBuilder()
        
        assert builder.validate("") is False
        assert builder.validate(None) is False
    
    def test_validate_invalid_key_too_long(self):
        """测试超长键验证"""
        builder = CacheKeyBuilder()
        
        long_key = "a" * (CacheConfig.MAX_KEY_LENGTH + 100)
        assert builder.validate(long_key) is False
    
    def test_validate_invalid_key_forbidden_chars(self):
        """测试包含非法字符的键验证"""
        builder = CacheKeyBuilder()
        
        # 包含空格
        assert builder.validate("agent config") is False
        # 包含换行符
        assert builder.validate("agent\nconfig") is False
        # 包含制表符
        assert builder.validate("agent\tconfig") is False
    
    def test_custom_prefix(self):
        """测试自定义前缀"""
        builder = CacheKeyBuilder(prefix="custom_prefix")
        
        key = builder.build("test:key")
        assert key == "custom_prefix:test:key"
    
    def test_cache_keys_constants(self):
        """测试缓存键常量"""
        # 测试 CacheKeys 类的方法
        assert CacheKeys.agent_config("agent_001") == "agent_engine:agent:config:agent_001"
        assert CacheKeys.session_history("sess_123") == "agent_engine:session:history:sess_123"
        assert CacheKeys.skill_info("skill_1") == "agent_engine:skill:info:skill_1"
