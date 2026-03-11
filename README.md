# Agent Engine Service

基于 FastAPI + Uvicorn 的 Agent 运行服务框架，支持 Agent 生命周期管理、任务执行、轨迹记录和健康监控。

## 特性

- **动态 Agent 注册**：支持通过装饰器动态注册 Agent 类
- **配置管理**：从数据库加载 Agent 配置，支持本地缓存
- **任务执行**：支持同步和流式任务执行，自动管理 Agent 生命周期
- **流式响应**：支持 SSE（Server-Sent Events）流式输出
- **健康状态上报**：定期查询并上报所有 Agent 的健康状态
- **轨迹信息上报**：由 Agent 子类自主管理轨迹数据，异步上报不阻塞任务返回
- **RESTful API**：提供完整的 REST API 接口

## Trajectory / Agent 输出行为（重要）

- Agent 的执行方法 `execute()` 可以返回任意类型，框架会尝试将其标准化为内部消息序列（例如包含 role/content 的字典列表）以便后续处理。
- 框架会把 Agent 的输出消息转换为 `Trajectory`（由 `TrajectoryStep` 组成）用于异步上报与持久化。通常第一条消息描述状态（state），第二条消息表示动作/决策（action），并作为最终的 `AgentTaskResponse.output` 返回给客户端。
- 因此自定义 Agent 时请确保 `get_trajectory()` 返回的 `Trajectory` 或者 `execute()` 的返回值能被框架安全转换为包含字段：`state`、`action`、`reward`（float）、`next_state`、`is_terminal`（bool）等的轨迹步骤；若无法保证，建议在 Agent 内部显式构建 `TrajectoryStep` 列表并返回。

框架实现细节与契约位于 `src/models/schemas.py`（`Trajectory` / `TrajectoryStep` / `AgentTaskResponse`），建议在实现 Agent 前先阅读这些定义以保证兼容性。

## 项目结构

```
AgentEngine/
├── src/           # 主服务包
│   ├── __init__.py
│   ├── app.py              # FastAPI 应用实例
│   ├── config.py           # 配置管理
│   ├── main.py             # 主入口
│   ├── api/                # API 路由
│   │   ├── __init__.py
│   │   └── router.py
│   ├── core/               # 核心模块
│   │   ├── __init__.py
│   │   ├── base.py         # Agent 基类和注册机制
│   │   ├── config_manager.py  # 配置信息管理
│   │   └── agent_manager.py   # Agent 对象管理
│   ├── database/           # 数据库模块
│   │   ├── __init__.py
│   │   └── database.py
│   ├── models/             # 数据模型
│   │   ├── __init__.py
│   │   └── schemas.py
│   ├── services/           # 服务模块
│   │   ├── __init__.py
│   │   └── health_reporter.py
│   └── agents/             # Agent 实现
│       ├── __init__.py
│       └── echo/echo_agent.py
├── .env.example            # 环境配置示例
├── requirements.txt        # 依赖列表
├── pyproject.toml          # 项目配置
├── run.py                  # 启动脚本
└── README.md
```

## 安装

```bash
# 克隆项目
cd AgentEngine

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 或使用 pip 安装项目
pip install -e .
```

## 配置

复制环境配置文件并修改：

```bash
cp .env.example .env
```

配置项说明：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| APP_NAME | Agent Engine Service | 服务名称 |
| DEBUG | false | 调试模式 |
| HOST | 0.0.0.0 | 监听地址 |
| PORT | 8000 | 监听端口 |
| WORKERS | 1 | Uvicorn worker 进程数 |
| DATABASE_URL | sqlite+aiosqlite:///:memory: | 数据库连接 |
| HEALTH_REPORT_INTERVAL | 60 | 健康状态上报间隔(秒) |
| LOG_LEVEL | INFO | 日志级别 |

> **注意**: 由于 Agent 管理器使用单例模式，多个 worker 进程之间不共享状态。建议在生产环境中使用 `WORKERS=1`，或通过外部存储（如 Redis）实现状态共享。

## 示例：`run_loan_analysis.py` 的配置文件

脚本 `examples/run_loan_analysis.py` 支持通过 TOML 或 JSON 文件一次性提供一组参数，使用 `--config <path>` 指定配置文件。下面给出一个 TOML 示例（也可改为 JSON 格式）：

示例 `examples/run_loan_analysis.example.toml`:

```toml
# 数据库连接（mysql 或 opengauss）
db_host = "127.0.0.1"
db_port = 3306
db_user = "root"
db_password = "secret"
db_name = "loans_db"
db_type = "mysql"          # mysql 或 opengauss

# 要查询的表与列（仅允许字母/数字/下划线）
sql_table = "t_ent_loan"
sql_column = "loannr_chkdgt"

# Agent 调用相关
agent_id = "risk-agent-001"
user_id = "example-user"
api_url = "http://127.0.0.1:8000/api/v1/agent/execute"

# 其它
max_records = 100
out_csv = "agent_calls.csv"
```

使用方法示例：

```bash
python examples/run_loan_analysis.py --config examples/run_loan_analysis.example.toml
```

也可以传入 JSON 文件（文件名后缀为 .json），脚本会按相同的键读取并覆盖命令行参数。

## 运行

```bash
# 方式1: 使用启动脚本
python run.py

# 方式2: 直接运行模块
python -m src.main

# 方式3: 使用 uvicorn
uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload

# 方式4: 使用仓库内的 E2E 脚本（推荐用于本地复现 E2E 测试）
chmod +x scripts/run_e2e.sh
./scripts/run_e2e.sh
```

## API 文档

服务启动后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

重要提示：端到端（E2E）测试依赖服务在本地可用。运行包含 E2E 的测试前，请确保已在另一终端启动服务（例如使用 `uvicorn src.app:app --reload` 或运行仓库中的 `./scripts/run_e2e.sh`），否则测试将因无法连接到 http://localhost:8000 而失败（ConnectionRefusedError）。
开发者提示：仓库已包含一个小脚本 `scripts/run_e2e.sh`，它会使用项目虚拟环境中的 Python 启动 uvicorn、等待服务就绪然后运行端到端测试，最后停止服务。该脚本默认使用 `.venv/bin/python`（如果你的虚拟环境名称不同，请修改脚本中的 `VENV_DIR`）。

## API 接口

### Agent 任务执行

**POST /api/v1/agent/execute**

执行 Agent 任务。

请求参数：
| 参数 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| agent_id | string | 是 | - | 用于找到对应的agent对象 |
| user_id | string | 是 | - | 用户的唯一标识 |
| session_id | string | 否 | - | 会话ID |
| session_ended | boolean | 否 | false | 会话是否已结束（若 true，Agent 可清理会话相关资源） |
| input | object | 是 | - | 任务输入数据 |
| timeout | integer | 否 | 300 | 超时时间(秒) |

请求示例：
```json
{
  "agent_id": "echo-agent-001",
  "user_id": "user-12345",
  "session_id": "session-67890",
  "input": {"query": "请评估企业风险"},
  "timeout": 300
}
```

响应示例：
```json
{
  "success": true,
  "agent_id": "echo-agent-001",
  "session_id": "session-67890",
  "output": "企业风险等级较高",
  "error": null,
  "execution_time": 1.5
}
```

### 其他接口

- `GET /api/v1/agent/configs` - 获取所有 Agent 配置
- `GET /api/v1/agent/config/{agent_id}` - 获取指定 Agent 配置
- `POST /api/v1/agent/config` - 添加/更新 Agent 配置
    - 注意：请求体现在要求包含 `agent_config_id`（配置记录主键），若客户端未提供，服务端内部会生成，但为了可追溯性和测试一致性，建议调用方显式提供该字段。
- `DELETE /api/v1/agent/config/{agent_id}` - 删除 Agent 配置
- `GET /api/v1/agent/health` - 获取所有 Agent 健康状态
- `GET /api/v1/agent/health/{agent_id}` - 获取指定 Agent 健康状态
- `GET /api/v1/agent/list` - 获取活跃 Agent 列表
- `POST /api/v1/agent/stop/{agent_id}` - 停止指定 Agent
- `POST /api/v1/agent/restart/{agent_id}` - 重启指定 Agent
- `GET /api/v1/agent/trajectories` - 获取 Agent 轨迹历史
- `GET /api/v1/service/status` - 获取服务状态
- `POST /api/v1/service/health-report` - 触发健康状态上报

### 流式任务执行

流式和非流式任务执行使用**同一个 API**：`POST /api/v1/agent/execute`，通过请求参数 `stream` 控制返回方式：

| stream 参数 | 返回方式 | Content-Type |
|-------------|----------|--------------|
| `false`（默认） | JSON 响应 | `application/json` |
| `true` | SSE 流式响应 | `text/event-stream` |

请求参数（增加 stream 字段）：
| 参数 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| agent_id | string | 是 | - | 用于找到对应的agent对象 |
| user_id | string | 是 | - | 用户的唯一标识 |
| session_id | string | 否 | - | 会话ID |
| input | object | 是 | - | 任务输入数据 |
| timeout | integer | 否 | 300 | 超时时间(秒) |
| stream | boolean | 否 | false | 是否流式返回 |

使用 curl 测试流式接口：
```bash
curl -X POST "http://localhost:8000/api/v1/agent/execute" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "echo-agent-001", "user_id": "user-001", "input": {"message": "你好"}, "stream": true}'
```

流式响应示例（SSE 格式）：
```
data: {"event": "start", "data": {"message": "开始处理"}, "chunk_index": 0, "timestamp": 1234567890.123}

data: {"event": "thinking", "data": {"message": "正在分析输入..."}, "chunk_index": 1, "timestamp": 1234567890.456}

data: {"event": "content", "data": {"text": "Echo: 你好"}, "chunk_index": 2, "timestamp": 1234567890.789}

data: {"event": "done", "data": {"message": "处理完成"}, "chunk_index": 3, "timestamp": 1234567891.012}
```

## 自定义 Agent

创建自定义 Agent 需要继承 `BaseAgent` 抽象类并使用 `@AgentRegistry.register()` 装饰器注册。

注意：注册时请使用唯一的type name作为key（例如 `echo` 或 `risk-agent`），以便在配置和测试中引用。测试套件通常根据注册键（`agent_id`）查找 Agent 实现，若注册名与调用方不一致会导致创建/查找失败。

### 必须实现的抽象方法

| 方法 | 描述 |
|------|------|
| `execute()` | 执行 Agent 任务的主逻辑 |
| `get_trajectory()` | 获取 Agent 执行轨迹 |
| `clear_trajectory()` | 清空轨迹记录 |

### 可选实现的方法

| 方法 | 描述 |
|------|------|
| `execute_stream()` | 流式执行任务，返回 `AsyncIterator[StreamChunk]` |
| `get_health()` | 获取 Agent 健康状态 |
| `stop()` | 停止 Agent |

### 示例代码

```python
from src.core.base import BaseAgent, AgentRegistry
from src.models.schemas import AgentConfig, Trajectory, TrajectoryStep, StreamChunk
from typing import AsyncIterator

@AgentRegistry.register("my-agent")
class MyAgent(BaseAgent):
    def __init__(self, config: AgentConfig):
        super().__init__(config)
        # 子类自主管理轨迹数据
        self._trajectory_steps: list[TrajectoryStep] = []
    
    async def execute(
        self,
        user_id: str,
        session_id: str,
        input_data: dict,
        timeout: int = 300
    ) -> any:
        # 记录轨迹步骤
        self._trajectory_steps.append(TrajectoryStep(
            state="开始处理",
            action="执行任务",
            reward=0.0,
            next_state="处理中",
            is_terminal=False
        ))
        
        # 实现业务逻辑
        result = await self.process(input_data)
        
        # 记录完成步骤
        self._trajectory_steps.append(TrajectoryStep(
            state="处理完成",
            action="返回结果",
            reward=1.0,
            next_state="完成",
            is_terminal=True
        ))
        
        return result
    
    async def execute_stream(
        self,
        user_id: str,
        session_id: str,
        input_data: dict,
        timeout: int = 300
    ) -> AsyncIterator[StreamChunk]:
        """流式执行任务"""
        import time
        
        yield StreamChunk(type="start", content="开始执行...", timestamp=time.time())
        
        # 处理逻辑...
        result = await self.process(input_data)
        
        yield StreamChunk(type="content", content=result, timestamp=time.time())
        yield StreamChunk(type="done", content="完成", timestamp=time.time())
    
    def get_trajectory(self) -> Trajectory:
        """返回当前轨迹"""
        return Trajectory(steps=self._trajectory_steps.copy())
    
    def clear_trajectory(self) -> None:
        """清空轨迹记录"""
        self._trajectory_steps.clear()
```

## 服务运行流程

### 1. 初始化
- 从数据库拉取 Agent 配置信息
- 保存到 Agent 配置信息管理模块
- 启动健康状态上报服务

### 2. Agent 请求响应
1. 收到任务请求时，检查 Agent 对象是否存在
2. 如存在，直接执行任务
3. 如不存在，从配置管理模块获取配置创建 Agent
4. 如配置不存在，从数据库获取
5. 执行任务并返回结果（支持同步和流式两种模式）
6. 异步上报轨迹信息

### 3. Agent 状态信息上报
- 定期（默认60秒）查询所有 Agent 健康状态
- 异步上传至数据库

### 4. Agent 运行轨迹信息上报
- 每次任务执行完成后
- 调用 Agent 子类的 `get_trajectory()` 方法获取轨迹数据
- 异步上报轨迹信息到数据库
- 不阻塞任务结果返回

## 测试

运行单元测试：
```bash
pytest tests/ -v
```

运行端到端测试：
```bash
# 推荐使用仓库脚本（会自动启动/停止服务并运行 E2E）
./scripts/run_e2e.sh
```

开发者说明（短）:
- 我们最近将 Pydantic 模型的 `class Config` 迁移为 v2 风格的 `model_config = ConfigDict(...)`，以消除 v2 的弃用警告；同时同步了模块级与类级单例的初始化以避免多处缓存/实例不同步的问题。若你在本地看到与文档不一致的行为，请先运行测试确认，然后参考 `docs/DESIGN.md` 中的 "多进程注意事项" 部分。

## License

MIT License
