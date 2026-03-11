import json
from typing import get_type_hints
from typing import List, Dict, Any
from pydantic import BaseModel

class ModelConfig(BaseModel):
    model_provider: str = "openai",
    api_base: str = None
    api_key: str = None
    model: str = None
    max_tokens: int = 32768,
    temperature: float = 1,
    top_p: float = 0.9,
    frequency_penalty: float = 0,
    presence_penalty: float = 0,
    response_format: Dict[str, str] = None,
    stop: List[str] = None,
    timeout: int = 30,

class MCPToolConfig(BaseModel):
    api_base: str = None
    api_key: str = None
    tool: str = None

class PromptConfig(BaseModel):
    role: str = None
    content: str = None

class AgentConfig:
    model_list: Dict[str, Dict[str, Any]] = []
    mcp_tool_list: Dict[str, Dict[str, Any]] = []
    prompt_list: Dict[str, Dict[str, Any]] = []