# Agent Engine Service 设计文档

## 1. 概述

### 1.1 项目简介

Agent Engine Service 是一个基于 **FastAPI + Uvicorn** 构建的 Agent 运行服务框架，用于管理和运行各种 AI Agent 实例。本系统提供 Agent 的动态注册、任务执行（同步/流式）、状态监控和轨迹追踪等功能。

### 1.2 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| Web 框架 | FastAPI | 高性能异步 Web 框架 |
| ASGI 服务器 | Uvicorn | 支持异步和多 worker |
| 数据验证 | Pydantic | 数据模型和验证 |
| 并发模型 | asyncio | 协程异步编程 |
| 流式响应 | SSE | Server-Sent Events |
| 日志 | Loguru | 结构化日志 |
| 配置管理 | pydantic-settings | 环境变量配置 |

### 1.3 核心功能

1. **Agent 动态注册** - 通过装饰器模式动态注册 Agent 类型
2. **任务执行** - 支持同步和流式两种执行模式
3. **配置管理** - 从数据库加载配置，支持本地缓存
4. **健康监控** - 定期检查并上报 Agent 健康状态
5. **轨迹追踪** - 记录 Agent 执行轨迹，支持异步上报

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Layer                             │
│              (HTTP Requests / SSE Streams)                      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        API Layer                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  /agent/execute │  │  /agent/config  │  │  /agent/health  │  │
│  │  (stream参数)    │  │                 │  │                 │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   /agent/list   │  │ /agent/stop     │  │ /service/status │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Core Layer                                │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    AgentManager                         │    │
│  │      (Singleton: Agent 实例管理、任务调度、轨迹上报)       │    │
│  └─────────────────────────────────────────────────────────┘    │
│           │                    │                    │           │
│           ▼                    ▼                    ▼           │
│  ┌──────────────────┐  ┌───────────────┐  ┌──────────────────┐ │
│  │AgentConfigManager│  │ AgentRegistry │  │ HealthReporter   │ │
│  │  (配置缓存)       │  │  (类型注册表)  │  │ (健康状态上报)    │ │
│  └──────────────────┘  └───────────────┘  └──────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Agent Layer                                │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    BaseAgent                            │    │
│  │  - invoke() [必须实现]                                   │    │
│  │  - execute_stream() [可选覆盖，默认调用 invoke]          │    │
│  │  - get_session(), save_to_session() [会话管理]          │    │
│  │  - start(), stop() [生命周期]                           │    │
│  └─────────────────────────────────────────────────────────┘    │
│           │                                    │                │
│           ▼                                    ▼                │
│  ┌───────────────────┐              ┌───────────────────────┐   │
│  │    EchoAgent      │              │  RiskAssessmentAgent  │   │
│  │   (示例 Agent)     │              │    (业务 Agent)        │   │
│  └───────────────────┘              └───────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Database Layer                               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  DatabaseManager                        │    │
│  │  - get_all_agent_configs()                              │    │
│  │  - get_agent_config()                                   │    │
│  │  - save_agent_task()                                    │    │
│  │  - save_trajectory()                                    │    │
│  │  - get_session_info()                                   │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
AgentEngine/
├── src/                        # 主服务包
│   ├── __init__.py
│   ├── app.py                  # FastAPI 应用实例
│   ├── config.py               # 配置管理
│   ├── main.py                 # 主入口
│   ├── api/                    # API 路由
│   │   ├── __init__.py
│   │   └── router.py           # RESTful API 定义
│   ├── core/                   # 核心模块
│   │   ├── __init__.py
│   │   ├── base.py             # Agent 基类和注册机制
│   │   ├── config_manager.py   # 配置信息管理
│   │   └── agent_manager.py    # Agent 对象管理
│   ├── database/               # 数据库模块
│   │   ├── __init__.py
│   │   └── database.py         # 数据库操作
│   ├── models/                 # 数据模型
│   │   ├── __init__.py
│   │   └── schemas.py          # Pydantic 模型
│   ├── services/               # 服务模块
│   │   ├── __init__.py
│   │   └── health_reporter.py  # 健康状态上报
│   └── agents/                 # Agent 实现
│       ├── __init__.py
│       └── echo/echo_agent.py       # 示例 Agent
├── tests/                      # 测试目录
├── docs/                       # 文档目录
│   ├── API.md                  # API 接口文档
│   └── DESIGN.md               # 设计文档
├── requirements.txt
├── pyproject.toml
├── run.py                      # 启动脚本
└── README.md
```

---

## 3. 核心组件设计

### 3.1 AgentRegistry（Agent 注册表）

使用装饰器模式实现 Agent 类型的动态注册。

```python
from typing import Dict, Type, Optional

class AgentRegistry:
    """Agent 注册表"""
    _registry: Dict[str, Type["ABC"]] = {}
    
    @classmethod
    def register(cls, agent_type_name: str):
        """
        装饰器：注册 Agent 类
        
        注册时会进行接口校验：要求被注册类必须实现可调用的 `invoke` 方法，
        否则注册会失败并抛出 TypeError。
        
        Args:
            agent_type_name: Agent 类型标识符
            
        Raises:
            TypeError: 当 Agent 类未实现 invoke 方法时
        """
        def decorator(agent_class: Type["ABC"]):
            # 接口校验：确保实现了 invoke 方法
            invoke_attr = getattr(agent_class, "invoke", None)
            if invoke_attr is None or not callable(invoke_attr):
                raise TypeError(
                    f"Agent class {agent_class.__name__} must implement a callable 'invoke' method"
                )
            
            if agent_type_name in cls._registry:
                logger.warning(f"Agent类型 '{agent_type_name}' 已存在，将被覆盖")
            cls._registry[agent_type_name] = agent_class
            logger.info(f"Agent类型 '{agent_type_name}' 注册成功: {agent_class.__name__}")
            return agent_class
        return decorator
    
    @classmethod
    def get(cls, agent_type_name: str) -> Optional[Type["ABC"]]:
        """获取已注册的 Agent 类"""
        return cls._registry.get(agent_type_name)
    
    @classmethod
    def get_all(cls) -> Dict[str, Type["ABC"]]:
        """获取所有已注册的 Agent 类"""
        return cls._registry.copy()
    
    @classmethod
    def is_registered(cls, agent_type_name: str) -> bool:
        """检查 Agent 类型是否已注册"""
        return agent_type_name in cls._registry

    @classmethod
    def unregister(cls, agent_type_name: str) -> bool:
        """
        注销 Agent 类型
        
        Args:
            agent_type_name: Agent 类型标识符
            
        Returns:
            是否成功注销
        """
        if agent_type_name in cls._registry:
            del cls._registry[agent_type_name]
            logger.info(f"Agent类型 '{agent_type_name}' 已注销")
            return True
        return False
```

**使用示例：**
```python
@AgentRegistry.register("echo_agent")
class EchoAgent(BaseAgent):
    def __init__(self, config: str):
        super().__init__(config)
    
    async def invoke(self, input_data: Dict[str, Any], history: List[Dict] = None) -> Any:
        # 实现具体业务逻辑
        return {"result": "echo"}

@AgentRegistry.register("risk-assessment")
class RiskAssessmentAgent(BaseAgent):
    def __init__(self, config: str):
        super().__init__(config)
    
    async def invoke(self, input_data: Dict[str, Any], history: List[Dict] = None) -> Any:
        # 实现具体业务逻辑
        return {"result": "assessment"}
```

**重要约定：**
- 注册器在注册时会进行接口校验：必须实现可调用的 `invoke` 方法（同步或异步均可），否则注册会失败并抛出 `TypeError`
- Agent 构造器必须接受一个字符串参数 `config: str`（JSON 字符串形式的配置），框架会先尝试 `agent_class(config_str)`，失败时回退到 `agent_class()`
- `invoke` 方法签名：`async def invoke(self, input_data: Dict[str, Any], history: List[Dict] = None) -> Any`

### 3.2 BaseAgent（Agent 基类）

所有 Agent 的抽象基类，定义了 Agent 必须实现的接口。

```python
from abc import ABC
from typing import Any, Dict, List, Optional, AsyncIterator
import time
from datetime import datetime

class BaseAgent(ABC):
    """
    Agent 基类
    所有 Agent 实现都应继承此类
    
    运行时约定：
    1. 构造器接受一个字符串参数 config（JSON 字符串形式的配置）
    2. 必须实现 async def invoke(self, input_data: Dict[str, Any], history: List[Dict] = None) -> Any
    3. 可选实现 async def execute_stream(...) 支持流式输出
    4. 框架会通过 invoke 方法执行任务，返回值可以是任意类型
    """
    
    def __init__(self, config: str):
        """
        初始化 Agent
        
        Args:
            config: Agent 配置信息（JSON 字符串）
        """
        # 运行状态
        self._start_time = time.time()
        self._is_alive = True
        self._is_responsive = True
        self._task_queue_healthy = True
        self._current_task_count = 0

        # 会话管理
        self._sessions: Dict[str, Dict[str, Any]] = {}
    
    @property
    def uptime_seconds(self) -> float:
        """获取运行时间（秒）"""
        return time.time() - self._start_time
    
    # ==================== 核心方法（必须实现） ====================
    
    async def invoke(
        self,
        input_data: Dict[str, Any],
        history: List[Dict] = None
    ) -> Any:
        """
        执行任务的核心方法（必须实现）
        
        框架在 AgentManager.execute_task 中调用此方法执行任务。
        
        Args:
            input_data: 任务输入数据
            history: 会话历史记录（可选）
            
        Returns:
            任务输出，可以是任意类型：
            - 单个值
            - Dict
            - List[Dict]（包含 role/content 的消息列表，用于构建 Trajectory）
        """
        raise NotImplementedError("子类必须实现 invoke 方法")
    
    # ==================== 可选方法 ====================
        
    async def execute_stream(
        self,
        user_id: str,
        session_id: str,
        input_data: Dict[str, Any],
        timeout: int = 300
    ) -> AsyncIterator[StreamChunk]:
        """
        流式执行 Agent 任务（异步生成器，可选实现）
        
        子类可重写此方法实现自定义流式输出。
        默认实现会调用 invoke 并将结果作为单个块返回。
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            input_data: 任务输入数据
            timeout: 超时时间（秒）
            
        Yields:
            StreamChunk: 流式数据块
        """
        from src.models.schemas import StreamChunk, StreamEventType
        
        chunk_index = 0
        
        # 发送开始事件
        yield StreamChunk(
            event=StreamEventType.START,
            data={"message": "开始处理"},
            agent_id=self.agent_id,
            session_id=session_id,
            chunk_index=chunk_index
        )
        chunk_index += 1
        
        try:
            # 调用 invoke 方法
            result = await self.invoke(input_data=input_data, history=None)
            
            # 发送内容块
            yield StreamChunk(
                event=StreamEventType.CONTENT,
                data=result,
                agent_id=self.agent_id,
                session_id=session_id,
                chunk_index=chunk_index
            )
            chunk_index += 1
            
            # 发送完成事件
            yield StreamChunk(
                event=StreamEventType.DONE,
                data={"message": "处理完成"},
                agent_id=self.agent_id,
                session_id=session_id,
                chunk_index=chunk_index
            )
            
        except Exception as e:
            yield StreamChunk(
                event=StreamEventType.ERROR,
                data={"error": str(e)},
                agent_id=self.agent_id,
                session_id=session_id,
                chunk_index=chunk_index
            )
    
    # ==================== 会话管理 ====================
    
    def get_session(self, session_id: str) -> Dict[str, Any]:
        """获取或创建会话"""
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "history": [],
                "memory": {},
                "created_at": datetime.now()
            }
        return self._sessions[session_id]
    
    def save_to_session(self, session_id: str, key: str, value: Any) -> None:
        """保存数据到会话"""
        session = self.get_session(session_id)
        session["memory"][key] = value
    
    def get_from_session(self, session_id: str, key: str, default: Any = None) -> Any:
        """从会话获取数据"""
        session = self.get_session(session_id)
        return session["memory"].get(key, default)
    
    # ==================== 生命周期 ====================
    
    async def start(self) -> None:
        """启动 Agent（子类可覆盖）"""
        pass
    
    async def stop(self) -> None:
        """停止 Agent（子类可覆盖）"""
        self._is_alive = False
```

**设计说明：**

BaseAgent 的设计遵循以下原则：

1. **最小化接口约束**：只要求实现 `invoke` 方法，不强制实现轨迹管理
2. **灵活的返回值**：`invoke` 可以返回任意类型，由 AgentManager 负责规范化
3. **会话状态管理**：基类提供会话管理的基础设施，但不强制使用
4. **流式输出支持**：提供默认的流式实现，子类可根据需要覆盖

### 3.3 AgentManager（Agent 管理器）

系统的核心管理组件，采用单例模式。

```python
class AgentManager:
    """Agent 管理器 (单例)"""
    _instance: Optional["AgentManager"] = None
    
    def __init__(
        self,
        config_manager: Optional[AgentConfigManager] = None,
        db_manager: Optional[DatabaseManager] = None,
        evaluator: Optional[TrajectoryEvaluator] = None
    ):
        """
        初始化 Agent 管理器
        
        Args:
            config_manager: 配置管理器实例
            db_manager: 数据库管理器实例
            evaluator: 轨迹评估器实例
        """
        self._agents: Dict[str, ABC] = {}
        self._config_manager = config_manager or AgentConfigManager()
        self._db_manager = db_manager or DatabaseManager()
        self._evaluator = evaluator or TrajectoryEvaluator()
```

**主要职责：**
- Agent 实例的创建和缓存
- 任务执行调度（同步/流式）
- 轨迹数据异步上报
- Agent 生命周期管理（停止、重启）

**多进程注意事项：**

当使用多个 Uvicorn worker 时，每个 worker 进程都有独立的 `AgentManager` 实例，它们之间不共享状态。这意味着：

1. 同一个 `agent_id` 的 Agent 可能在多个 worker 中被创建
2. Agent 状态在 worker 之间不同步
3. 如需状态共享，需要引入外部存储（如 Redis）

建议生产环境使用 `WORKERS=1` 或实现分布式状态管理。

**AgentManager 实现细节（重要，反映当前代码）**

- Agent 创建流程：
    1. 通过 `AgentConfigManager.get_config(agent_id)` 获取 `AgentConfig`。  
    2. 使用 `config.agent_type_name` 作为查找键去 `AgentRegistry.get(lookup_key)` 获取 Agent 类。  
    3. 尝试把 `config.config_schema` 序列化为 JSON 字符串并以该字符串调用构造器 `agent_class(cfg_str)`；当构造器不接受参数时回退到无参构造 `agent_class()`。若两者都失败，则创建失败并返回 None。  
    4. 成功构造后将实例缓存到内部字典 `_agents`（以 `agent_id` 为键）。

- 输出与 Trajectory 构建规则：
    - 框架允许 Agent 返回多种格式（None、单值、dict、或消息列表）。管理器会尝试把返回值规范化为“消息序列”（例如包含 `role`/`content` 的 dict 列表），再调用 `_build_trajectory(messages, session_ended)` 来构造 `Trajectory`。
    - `_build_trajectory` 的默认策略：把消息序列的第一条映射为 `TrajectoryStep.state`，第二条映射为 `TrajectoryStep.action`，并以 `session_ended` 设置 `is_terminal`。
    - `_build_output_result` 的默认策略：从 Agent 返回的 output 中提取**最后一条记录**作为最终 `AgentTaskResponse.output`（若最后一条为 dict 并包含 `content` 字段则返回其值；否则直接返回最后一条的原始值；若列表为空则返回 None）。

- 流式执行与轨迹上报：
    - 在流式模式下，Agent 的 `execute_stream` 产生 `StreamChunk`，管理器会收集 `CONTENT` 与 `DONE` 中的实际输出到 `collected_output` 列表。最终会把收集到的输出转换/包装为 `Trajectory` 并异步上报（调用 `_report_trajectory`）。注意：流式处理实现中在收集阶段使用了列表类型作为临时容器，上报接口实际期待 `Trajectory`，上报前会进行必要的包装。
    - 流式模式同样会遵循 `_build_output_result` 的最后一条抽取策略作为最终返回（若使用同步 JSON 返回模式则使用该策略生成 `AgentTaskResponse`）。

- 后台任务与评估：
    - 任务执行后，管理器会异步创建后台任务以保存任务信息、会话历史并上报轨迹；当 `session_ended=True` 时还会触发轨迹评估器 `TrajectoryEvaluator` 进行评估，评估结果写入数据库供后续查询。


### 3.4 AgentConfigManager（配置管理器）

负责管理 Agent 配置信息的缓存和获取。

```python
class AgentConfigManager:
    """
    Agent 配置信息管理器
    负责：
    1. 从数据库加载配置到本地缓存
    2. 提供配置的快速查询
    3. 配置的增删改查
    """
    
    _instance: Optional["AgentConfigManager"] = None
    
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """
        初始化配置管理器
        
        Args:
            db_manager: 数据库管理器实例
        """
        self._db_manager = db_manager or get_database_manager()
        self._config_cache: Dict[str, AgentConfig] = {}
        self._initialized = False
        self._lock = asyncio.Lock()
    
    @classmethod
    def get_instance(cls, db_manager: Optional[DatabaseManager] = None) -> "AgentConfigManager":
        """获取配置管理器单例"""
        if cls._instance is None:
            cls._instance = cls(db_manager)
        return cls._instance
    
    async def initialize(self) -> bool:
        """
        初始化配置管理器
        从数据库加载所有 Agent 配置到本地缓存
        
        Returns:
            是否初始化成功
        """
        ...
    
    async def get_config(self, agent_id: str) -> Optional[AgentConfig]:
        """获取缓存的配置"""
        return self._config_cache.get(agent_id)
    
    async def add_config(self, config: AgentConfig) -> bool:
        """添加/更新配置"""
        self._config_cache[config.agent_id] = config
        return True
```

### 3.5 HealthReporter（健康上报器）

```python
class HealthReporter:
    """Agent 健康状态定期上报"""
    
    _instance: Optional["HealthReporter"] = None
    
    def __init__(
        self,
        agent_manager: Optional[AgentManager] = None,
        db_manager: Optional[DatabaseManager] = None,
        report_interval: int = 60  # 默认60秒上报一次
    ):
        """
        初始化健康状态上报器
        
        Args:
            agent_manager: Agent 管理器实例
            db_manager: 数据库管理器实例
            report_interval: 上报间隔（秒）
        """
        self._agent_manager = agent_manager or get_agent_manager()
        self._db_manager = db_manager or get_database_manager()
        self._report_interval = report_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    @classmethod
    def get_instance(
        cls,
        agent_manager: Optional[AgentManager] = None,
        db_manager: Optional[DatabaseManager] = None,
        report_interval: int = 60
    ) -> "HealthReporter":
        """获取健康状态上报器单例"""
        if cls._instance is None:
            cls._instance = cls(agent_manager, db_manager, report_interval)
        return cls._instance
    
    async def start(self) -> None:
        """启动定时上报任务"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._report_loop())
    
    async def stop(self) -> None:
        """停止定时上报任务"""
        self._running = False
        if self._task:
            self._task.cancel()
    
    async def _report_loop(self) -> None:
        """上报循环"""
        while self._running:
            await self._report_all_health()
            await asyncio.sleep(self._report_interval)
```

---

## 4. 数据模型

### 4.1 核心模型

```python
class AgentConfig(BaseModel):
    """Agent 配置"""
    agent_config_id: str = Field(..., description="配置记录的主键ID")
    agent_id: str = Field(..., description="Agent唯一标识符")
    agent_type_id: str = Field(..., description="Agent类型唯一标识符")
    agent_type_name: str = Field(..., description="Agent显示名称（用于注册表查找）")
    description: str = Field(default="", description="功能描述")
    config_schema: Dict[str, Any] = Field(default_factory=dict, description="配置参数的JSON Schema")
    create_time: datetime = Field(default_factory=datetime.now, description="创建时间")
    update_time: Optional[datetime] = Field(default=None, description="更新时间")

class TrajectoryStep(BaseModel):
    """轨迹步骤"""
    step: int = Field(..., description="步骤序号")
    state: Any = Field(default=None, description="当前环境的观测值")
    action: Any = Field(default=None, description="智能体采取的操作")
    reward: float = Field(default=0.0, description="奖励值")
    next_state: Any = Field(default=None, description="执行动作后的观测值")
    is_terminal: bool = Field(default=False, description="是否为终止状态")

class Trajectory(BaseModel):
    """完整轨迹"""
    steps: List[TrajectoryStep] = Field(default_factory=list, description="轨迹步骤列表")

class AgentHealthStatus(BaseModel):
    """Agent 健康状态"""
    agent_id: str = Field(..., description="Agent ID")
    agent_type_name: str = Field(..., description="Agent类型名称")
    status: str = Field(default="healthy", description="状态: healthy, unhealthy, unknown")
    checks: HealthChecks = Field(default_factory=HealthChecks, description="健康检查详情")
    uptime_seconds: float = Field(default=0.0, description="运行时间(秒)")
    checked_at: datetime = Field(default_factory=datetime.now, description="检查时间")
```

### 4.2 流式响应模型

```python
class StreamEventType(str, Enum):
    """流式事件类型"""
    START = "start"           # 开始处理
    THINKING = "thinking"     # 思考中
    CONTENT = "content"       # 内容块
    TOOL_CALL = "tool_call"   # 工具调用
    TOOL_RESULT = "tool_result"  # 工具结果
    ERROR = "error"           # 错误
    DONE = "done"             # 完成

class StreamChunk(BaseModel):
    """流式数据块"""
    event: StreamEventType    # 事件类型
    data: Any                 # 数据内容
    agent_id: str             # Agent ID
    session_id: str           # 会话 ID
    chunk_index: int = 0      # 块序号
    timestamp: datetime       # 时间戳

    def to_sse(self) -> str:
        """转换为 SSE 格式"""
        return f"data: {json.dumps(self.model_dump(), ensure_ascii=False)}\n\n"
```

### 4.3 请求/响应模型

```python
class AgentTaskRequest(BaseModel):
    """任务请求"""
    agent_id: str = Field(..., description="Agent ID")
    user_id: str = Field(..., description="用户ID")
    user_name: Optional[str] = Field(default=None, description="用户名称")
    session_id: Optional[str] = Field(default=None, description="会话ID")
    input: Dict[str, Any] = Field(..., description="输入数据")
    timeout: int = Field(default=300, ge=1, le=3600, description="超时时间(秒)")
    stream: bool = Field(default=False, description="是否流式返回")
    session_ended: bool = Field(default=False, description="会话是否结束")

class AgentTaskResponse(BaseModel):
    """任务响应"""
    success: bool = Field(..., description="是否成功")
    agent_id: str = Field(..., description="Agent ID")
    session_id: str = Field(..., description="会话ID")
    output: Any = Field(default=None, description="输出结果")
    error: Optional[str] = Field(default=None, description="错误信息")
    execution_time: float = Field(default=0.0, description="执行时间(秒)")
```

---

## 5. API 设计

### 5.1 RESTful API 端点

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/agent/execute` | 执行任务（通过 `stream` 参数控制同步/流式） |
| GET | `/api/v1/agent/configs` | 获取所有配置 |
| GET | `/api/v1/agent/config/{agent_id}` | 获取单个配置 |
| POST | `/api/v1/agent/config` | 添加/更新配置 |
| DELETE | `/api/v1/agent/config/{agent_id}` | 删除配置 |
| GET | `/api/v1/agent/health` | 获取所有健康状态 |
| GET | `/api/v1/agent/health/{agent_id}` | 获取单个健康状态 |
| GET | `/api/v1/agent/list` | 获取活跃 Agent 列表 |
| POST | `/api/v1/agent/stop/{agent_id}` | 停止 Agent |
| POST | `/api/v1/agent/restart/{agent_id}` | 重启 Agent |
| GET | `/api/v1/agent/trajectories` | 获取轨迹历史 |
| GET | `/api/v1/service/status` | 获取服务状态 |
| POST | `/api/v1/service/health-report` | 触发健康上报 |

> 详细的 API 接口文档请参见 [API.md](./API.md)

### 5.2 流式响应协议

流式和非流式使用**同一个 API**：`POST /api/v1/agent/execute`，通过请求参数 `stream` 控制：

| stream 参数 | 返回方式 | Content-Type |
|-------------|----------|--------------|
| `false`（默认） | JSON 响应 | `application/json` |
| `true` | SSE 流式响应 | `text/event-stream` |

**流式响应格式（SSE）：**

```
data: {"event": "start", "data": {"message": "开始处理"}, "agent_id": "xxx", "session_id": "xxx", "chunk_index": 0, "timestamp": "..."}

data: {"event": "thinking", "data": {"message": "正在分析..."}, "agent_id": "xxx", "session_id": "xxx", "chunk_index": 1, "timestamp": "..."}

data: {"event": "content", "data": {"text": "结果内容"}, "agent_id": "xxx", "session_id": "xxx", "chunk_index": 2, "timestamp": "..."}

data: {"event": "done", "data": {"message": "处理完成"}, "agent_id": "xxx", "session_id": "xxx", "chunk_index": 3, "timestamp": "..."}
```

**StreamChunk 事件类型：**
- `start`: 任务开始
- `thinking`: 思考/推理过程
- `content`: 实际输出内容
- `tool_call`: 调用工具
- `tool_result`: 工具返回结果
- `error`: 发生错误
- `done`: 任务完成

---

## 6. 执行流程

### 6.1 任务执行流程

```
┌─────────┐     ┌─────────────┐     ┌─────────────┐     ┌───────────┐
│ Client  │────▶│   Router    │────▶│AgentManager │────▶│   Agent   │
└─────────┘     └─────────────┘     └─────────────┘     └───────────┘
                                           │
    1. POST /execute                       │
    2. 解析请求参数                          │
    3. 检查 stream 参数                     │
                       4. execute_task()    │
                       ─────────────────────▶
                          5. 检查 Agent 缓存
                          6. 如不存在，创建 Agent
                                           │
                          7. agent.invoke(input_data, history)
                          ─────────────────────────────▶
                                                       8. 执行业务逻辑
                                                       9. 返回结果
                          ◀─────────────────────────────
                          10. 规范化输出
                          11. 构建 Trajectory
                          12. 异步上报轨迹
                                           │
    ◀──────────────────────────────────────┘
    13. 返回响应 (JSON 或 SSE 流)
```

### 6.2 Agent 创建流程

```
execute_task(agent_id)
    │
    ▼
┌─────────────────────┐
│ 检查 _agents 缓存    │
└─────────────────────┘
    │
    ├── 存在 ──▶ 直接使用
    │
    └── 不存在
            │
            ▼
    ┌──────────────────────────┐
    │ AgentConfigManager.get() │
    └──────────────────────────┘
        │
        ├── 有配置 ──▶ AgentRegistry.get(agent_type_name)
        │                        │
        │                        ▼
        │                 ┌──────────────────────┐
        │                 │ agent_class(cfg_str) │
        │                 │ 或 agent_class()     │
        │                 └──────────────────────┘
        │                        │
        │                        ▼
        │                 ┌─────────────────────┐
        │                 │ 缓存到 _agents       │
        └─────────────────└─────────────────────┘
                │
                └── 无配置 ──▶ 返回错误
```

### 6.3 服务启动流程

```
1. 初始化
   ├── 加载环境配置
   ├── 初始化数据库连接
   ├── 从数据库加载 Agent 配置信息
   ├── 保存到 AgentConfigManager 缓存
   └── 启动 HealthReporter 定时任务

2. 运行中
   ├── 接收请求 → 执行任务 → 返回结果
   ├── 定期上报健康状态
   └── 异步上报轨迹信息

3. 关闭
   ├── 停止 HealthReporter
   ├── 停止所有 Agent
   └── 关闭数据库连接
```

---

## 7. 扩展指南

### 7.1 添加新 Agent 类型

1. **创建 Agent 类文件**（如 `src/agents/my_agent.py`）：

```python
from src.core.base import BaseAgent, AgentRegistry
from src.models.schemas import StreamChunk, StreamEventType
from typing import Any, Dict, List, AsyncIterator
import asyncio

@AgentRegistry.register("my-agent-type")
class MyAgent(BaseAgent):
    def __init__(self, config: str):
        """
        初始化 Agent
        
        Args:
            config: JSON 字符串形式的配置
        """
        super().__init__(config)
    
    async def invoke(
        self,
        input_data: Dict[str, Any],
        history: List[Dict] = None
    ) -> Any:
        """
        执行任务的核心逻辑
        
        返回值可以是：
        - 单个值
        - Dict
        - List[Dict] 包含 role/content 的消息列表
        """
        # 实现业务逻辑
        result = await self._do_work(input_data)
        
        # 返回消息列表格式（用于构建 Trajectory）
        return [
            {"role": "user", "content": input_data},
            {"role": "assistant", "content": result}
        ]
    
    async def execute_stream(
        self,
        user_id: str,
        session_id: str,
        input_data: Dict[str, Any],
        timeout: int = 300
    ) -> AsyncIterator[StreamChunk]:
        """自定义流式输出"""
        chunk_index = 0
        
        yield StreamChunk(
            event=StreamEventType.START,
            data={"message": "开始处理"},
            agent_id=self.agent_id,
            session_id=session_id,
            chunk_index=chunk_index
        )
        chunk_index += 1
        
        # 处理逻辑...
        result = await self._do_work(input_data)
        
        yield StreamChunk(
            event=StreamEventType.CONTENT,
            data={"text": str(result)},
            agent_id=self.agent_id,
            session_id=session_id,
            chunk_index=chunk_index
        )
        chunk_index += 1
        
        yield StreamChunk(
            event=StreamEventType.DONE,
            data={"message": "处理完成"},
            agent_id=self.agent_id,
            session_id=session_id,
            chunk_index=chunk_index
        )
    
    async def _do_work(self, input_data: dict) -> Any:
        # 实际业务逻辑
        await asyncio.sleep(0.1)
        return {"processed": input_data}
```

2. **确保模块被导入**：

在 `src/agents/__init__.py` 中导入新 Agent：

```python
from .echo.echo_agent import EchoAgent
from .risk_assessment.risk_assessment_agent import RiskAssessmentAgent
from .my_agent import MyAgent  # 添加这行
```

3. **添加配置**：

通过 API 或数据库添加 Agent 配置：

```json
{
    "agent_id": "my-agent-001",
    "agent_type_id": "uuid-my-agent-type",
    "agent_type_name": "my-agent-type",
    "description": "自定义 Agent 描述",
}
```

### 7.2 返回值格式与 Trajectory 构建

AgentManager 会将 Agent 的返回值规范化并构建 Trajectory：

**推荐的返回格式（用于构建 Trajectory）：**

```python
async def invoke(self, input_data: Dict[str, Any], history: List[Dict] = None) -> Any:
    # 返回包含 role/content 的消息列表
    return [
        {"role": "user", "content": input_data},
        {"role": "assistant", "content": "处理结果"}
    ]
```

**Trajectory 构建规则：**
- 第一条消息 → `TrajectoryStep.state`
- 第二条消息 → `TrajectoryStep.action`
- 最后一条消息的 content → `AgentTaskResponse.output`

**其他返回格式也支持：**
- 单个值：会被包装为单条消息
- Dict：会被包装为单条消息
- None：返回空 output

---

## 8. 部署配置

### 8.1 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| APP_NAME | Agent Engine Service | 服务名称 |
| DEBUG | false | 调试模式 |
| HOST | 0.0.0.0 | 监听地址 |
| PORT | 8000 | 监听端口 |
| WORKERS | 1 | Worker 进程数 |
| DATABASE_URL | - | 数据库连接串 |
| LOG_LEVEL | INFO | 日志级别 |

### 8.2 生产环境建议

1. **Worker 数量**：建议使用单 worker（`WORKERS=1`），除非实现了外部状态存储
2. **数据库**：生产环境建议使用 PostgreSQL 或 MySQL
3. **监控**：集成 Prometheus metrics 进行监控
4. **日志**：配置结构化日志输出，便于日志收集

### 8.3 Docker 部署

```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["python", "run.py"]
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  agent-engine:
    build: .
    ports:
      - "8000:8000"
    environment:
      - HOST=0.0.0.0
      - PORT=8000
      - WORKERS=1
      - LOG_LEVEL=INFO
```

---

## 9. 测试

### 9.1 单元测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_agent_service.py -v

# 带覆盖率报告
pytest tests/ --cov=src --cov-report=html
```

### 9.2 端到端测试

```bash
# 启动服务
python run.py &

# 运行 E2E 测试
python tests/test_agent_service.py
```

### 9.3 流式接口测试

```bash
curl -X POST "http://localhost:8000/api/v1/agent/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "echo-agent-001",
    "user_id": "test",
    "input": {"message": "hello"},
    "stream": true
  }'
```

---

## 10. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-01 | 初始版本 |
| 1.1.0 | 2026-01 | 添加流式响应支持（SSE） |
| 1.2.0 | 2026-01 | 统一字段名 `agent_id`，合并流式/非流式为同一接口 |
| 1.3.0 | 2026-02 | 更新文档以反映当前实现，移除过时的抽象方法约束 |

---

*本文档最后更新时间：2026年2月3日*
