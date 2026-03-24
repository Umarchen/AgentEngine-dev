"""
缓存序列化器模块
负责数据的序列化和反序列化
"""

import json
from typing import Any, Optional, Type

from pydantic import BaseModel
from loguru import logger


class CacheSerializer:
    """
    安全的缓存序列化器
    
    功能：
    1. JSON 序列化（默认）
    2. Pickle 序列化（可选，默认禁用）
    3. Pydantic 模型支持
    """
    
    def __init__(self, use_pickle: bool = False):
        """
        初始化序列化器
        
        Args:
            use_pickle: 是否启用 Pickle 序列化（默认禁用）
        """
        self.use_pickle = use_pickle
        
        if use_pickle:
            logger.warning(
                "⚠️ 安全警告：已启用 Pickle 序列化！"
                "仅用于可信数据源，可能存在反序列化安全风险！"
            )
    
    def serialize(self, data: Any) -> str:
        """
        序列化数据
        
        Args:
            data: 待序列化的数据
            
        Returns:
            序列化后的字符串
        """
        if data is None:
            return ""
        
        if self.use_pickle:
            # Pickle 序列化（不推荐）
            import pickle
            import base64
            
            try:
                serialized = pickle.dumps(data)
                return base64.b64encode(serialized).decode('utf-8')
            except Exception as e:
                logger.error(f"Pickle 序列化失败: {e}")
                raise
        
        # JSON 序列化（默认）
        try:
            if isinstance(data, BaseModel):
                # Pydantic 模型
                return data.model_dump_json()
            else:
                # 普通对象
                return json.dumps(data, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"JSON 序列化失败: {e}")
            raise
    
    def deserialize(
        self,
        data: str,
        model_class: Optional[Type] = None
    ) -> Any:
        """
        反序列化数据
        
        Args:
            data: 序列化的字符串
            model_class: 可选的 Pydantic 模型类
            
        Returns:
            反序列化后的数据
        """
        if not data:
            return None
        
        if self.use_pickle:
            # Pickle 反序列化（不推荐）
            import pickle
            import base64
            
            try:
                decoded = base64.b64decode(data.encode('utf-8'))
                return pickle.loads(decoded)
            except Exception as e:
                logger.error(f"Pickle 反序列化失败: {e}")
                raise
        
        # JSON 反序列化（默认）
        try:
            if model_class and issubclass(model_class, BaseModel):
                # 反序列化为 Pydantic 模型
                return model_class.model_validate_json(data)
            else:
                # 反序列化为普通对象
                return json.loads(data)
        except Exception as e:
            logger.error(f"JSON 反序列化失败: {e}")
            raise
    
    def is_serializable(self, data: Any) -> bool:
        """
        检查数据是否可序列化
        
        Args:
            data: 待检查的数据
            
        Returns:
            是否可序列化
        """
        try:
            self.serialize(data)
            return True
        except Exception:
            return False


# 默认序列化器实例（使用 JSON）
default_serializer = CacheSerializer(use_pickle=False)
