"""
缓存序列化器测试
"""

import pytest
from pydantic import BaseModel
from src.cache.serializer import CacheSerializer, default_serializer


class TestModel(BaseModel):
    """测试模型"""
    id: str
    name: str
    value: int


class TestCacheSerializer:
    """缓存序列化器测试类"""
    
    def test_serialize_dict(self):
        """测试字典序列化"""
        serializer = CacheSerializer()
        
        data = {"id": "test", "name": "Test", "value": 123}
        serialized = serializer.serialize(data)
        
        assert isinstance(serialized, str)
        assert "test" in serialized
        assert "Test" in serialized
    
    def test_deserialize_dict(self):
        """测试字典反序列化"""
        serializer = CacheSerializer()
        
        data = '{"id": "test", "name": "Test", "value": 123}'
        deserialized = serializer.deserialize(data)
        
        assert deserialized["id"] == "test"
        assert deserialized["name"] == "Test"
        assert deserialized["value"] == 123
    
    def test_serialize_pydantic_model(self):
        """测试 Pydantic 模型序列化"""
        serializer = CacheSerializer()
        
        model = TestModel(id="test", name="Test", value=123)
        serialized = serializer.serialize(model)
        
        assert isinstance(serialized, str)
        assert "test" in serialized
        assert "Test" in serialized
    
    def test_deserialize_pydantic_model(self):
        """测试 Pydantic 模型反序列化"""
        serializer = CacheSerializer()
        
        data = '{"id": "test", "name": "Test", "value": 123}'
        deserialized = serializer.deserialize(data, model_class=TestModel)
        
        assert isinstance(deserialized, TestModel)
        assert deserialized.id == "test"
        assert deserialized.name == "Test"
        assert deserialized.value == 123
    
    def test_serialize_list(self):
        """测试列表序列化"""
        serializer = CacheSerializer()
        
        data = [1, 2, 3, "test"]
        serialized = serializer.serialize(data)
        
        assert isinstance(serialized, str)
        assert "[1, 2, 3" in serialized
    
    def test_deserialize_list(self):
        """测试列表反序列化"""
        serializer = CacheSerializer()
        
        data = '[1, 2, 3, "test"]'
        deserialized = serializer.deserialize(data)
        
        assert isinstance(deserialized, list)
        assert len(deserialized) == 4
        assert deserialized[0] == 1
        assert deserialized[3] == "test"
    
    def test_serialize_none(self):
        """测试 None 序列化"""
        serializer = CacheSerializer()
        
        serialized = serializer.serialize(None)
        assert serialized == ""
    
    def test_deserialize_none(self):
        """测试 None 反序列化"""
        serializer = CacheSerializer()
        
        deserialized = serializer.deserialize("")
        assert deserialized is None
        
        deserialized = serializer.deserialize(None)
        assert deserialized is None
    
    def test_serialize_chinese(self):
        """测试中文序列化"""
        serializer = CacheSerializer()
        
        data = {"name": "测试", "desc": "这是一个测试"}
        serialized = serializer.serialize(data)
        
        assert "测试" in serialized
        assert "这是一个测试" in serialized
    
    def test_roundtrip_dict(self):
        """测试字典往返序列化"""
        serializer = CacheSerializer()
        
        original = {
            "id": "test_001",
            "name": "Test Agent",
            "config": {
                "timeout": 30,
                "retry": 3
            }
        }
        
        serialized = serializer.serialize(original)
        deserialized = serializer.deserialize(serialized)
        
        assert deserialized == original
    
    def test_roundtrip_pydantic_model(self):
        """测试 Pydantic 模型往返序列化"""
        serializer = CacheSerializer()
        
        original = TestModel(id="test_001", name="Test", value=999)
        
        serialized = serializer.serialize(original)
        deserialized = serializer.deserialize(serialized, model_class=TestModel)
        
        assert deserialized.id == original.id
        assert deserialized.name == original.name
        assert deserialized.value == original.value
    
    def test_is_serializable_valid(self):
        """测试可序列化检查（有效）"""
        serializer = CacheSerializer()
        
        assert serializer.is_serializable({"key": "value"}) is True
        assert serializer.is_serializable([1, 2, 3]) is True
        assert serializer.is_serializable("string") is True
    
    def test_default_serializer_instance(self):
        """测试默认序列化器实例"""
        assert default_serializer is not None
        assert isinstance(default_serializer, CacheSerializer)
        assert default_serializer.use_pickle is False
    
    # Pickle 序列化测试（可选，默认禁用）
    
    @pytest.mark.skip(reason="Pickle 序列化默认禁用，仅用于特殊场景")
    def test_serialize_with_pickle(self):
        """测试 Pickle 序列化"""
        serializer = CacheSerializer(use_pickle=True)
        
        data = {"complex": object()}  # 无法 JSON 序列化的对象
        serialized = serializer.serialize(data)
        
        assert isinstance(serialized, str)
        # 应该可以反序列化
        deserialized = serializer.deserialize(serialized)
        assert "complex" in deserialized
