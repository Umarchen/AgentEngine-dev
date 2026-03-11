# Agent Engine Service API 接口文档

## 概述

本文档描述 Agent Engine Service 的所有 RESTful API 接口，包括请求/响应格式和使用示例。

**基础路径**: `/api/v1`

**服务地址**: `http://localhost:8000`

---

## 目录

1. [任务执行接口](#1-任务执行接口)
2. [配置管理接口](#2-配置管理接口)
3. [健康状态接口](#3-健康状态接口)
4. [Agent 管理接口](#4-agent-管理接口)
5. [轨迹查询接口](#5-轨迹查询接口)
6. [服务状态接口](#6-服务状态接口)

---

## 1. 任务执行接口

### 1.1 执行 Agent 任务

执行 Agent 任务，支持同步返回和流式返回两种模式。

**接口路径**: `POST /api/v1/agent/execute`

**Content-Type**: `application/json`

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| agent_id | string | 是 | - | 用于找到对应的 Agent 对象 |
| user_id | string | 是 | - | 用户唯一标识，用于鉴权、统计、隔离记忆 |
| session_id | string | 否 | null | 会话ID，传入后 Agent 会加载该会话的历史记忆 |
| session_ended | boolean | 否 | false | 会话是否已结束（若 true，Agent 可以选择清理会话相关资源或不再保留会话上下文） |
| input | object | 是 | - | 任务输入数据 |
| timeout | integer | 否 | 300 | 超时时间（秒），范围 1-3600 |
| stream | boolean | 否 | false | 是否启用流式返回 |

> 注意：请求体中可包含 `session_ended`（布尔），用于告知 Agent 本次会话是否已经结束。该字段为可选项，默认值为 `false`。

#### 响应格式

**stream=false 时**（JSON 响应）:

| 字段 | 类型 | 描述 |
|------|------|------|
| success | boolean | 任务是否成功 |
| agent_id | string | Agent ID |
| session_id | string | 会话 ID |
| output | any | 任务输出结果 |
| error | string | 错误信息（失败时） |
| execution_time | float | 执行时间（秒） |

**stream=true 时**（SSE 流式响应）:

每个事件格式为 `data: {JSON}\n\n`，JSON 结构：

| 字段 | 类型 | 描述 |
|------|------|------|
| event | string | 事件类型: start/thinking/content/tool_call/tool_result/error/done |
| data | any | 事件数据 |
| agent_id | string | Agent ID |
| session_id | string | 会话 ID |
| chunk_index | integer | 数据块序号 |
| timestamp | string | 时间戳 (ISO 8601) |

#### 用例 1: 同步执行任务

**请求**:
```bash
curl -X POST "http://localhost:8000/api/v1/agent/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "echo-agent-001",
    "user_id": "user-12345",
    "session_id": "session-67890",
    "input": {"message": "你好，请介绍一下自己"},
    "timeout": 300,
    "stream": false
  }'
```

**响应** (200 OK):
```json
{
  "success": true,
  "agent_id": "echo-agent-001",
  "session_id": "session-67890",
  "output": "Echo: 你好，请介绍一下自己",
  "error": null,
  "execution_time": 0.125
}
```

#### 用例 2: 流式执行任务

**请求**:
```bash
curl -X POST "http://localhost:8000/api/v1/agent/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "echo-agent-001",
    "user_id": "user-12345",
    "input": {"message": "Hello World"},
    "stream": true
  }'
```

**响应** (200 OK, text/event-stream):
```
data: {"event": "start", "data": {"message": "开始处理"}, "agent_id": "echo-agent-001", "session_id": "auto-generated-id", "chunk_index": 0, "timestamp": "2026-01-22T10:30:00.123456"}

data: {"event": "thinking", "data": {"message": "正在分析输入..."}, "agent_id": "echo-agent-001", "session_id": "auto-generated-id", "chunk_index": 1, "timestamp": "2026-01-22T10:30:00.234567"}

data: {"event": "content", "data": {"text": "Echo: Hello World"}, "agent_id": "echo-agent-001", "session_id": "auto-generated-id", "chunk_index": 2, "timestamp": "2026-01-22T10:30:00.345678"}

data: {"event": "done", "data": {"message": "处理完成", "execution_time": 0.25}, "agent_id": "echo-agent-001", "session_id": "auto-generated-id", "chunk_index": 3, "timestamp": "2026-01-22T10:30:00.456789"}
```

#### 用例 3: 任务执行失败

**请求**:
```bash
curl -X POST "http://localhost:8000/api/v1/agent/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "non-existent-agent",
    "user_id": "user-12345",
    "input": {"message": "test"}
  }'
```

**响应** (200 OK):
```json
{
  "success": false,
  "agent_id": "non-existent-agent",
  "session_id": null,
  "output": null,
  "error": "Agent 不存在: non-existent-agent",
  "execution_time": 0.001
}
```

---

## 2. 配置管理接口

### 2.1 获取所有 Agent 配置

获取所有已加载的 Agent 配置信息。

**接口路径**: `GET /api/v1/agent/configs`

#### 请求参数

无

#### 响应格式

返回 `AgentConfig` 数组。

| 字段 | 类型 | 描述 |
|------|------|------|
| agent_id | string | Agent 唯一标识 |
| agent_type_id | string | Agent 类型标识符|
| agent_type_name | string | Agent 显示名称,如 "echo" |
| description | string | Agent 功能描述 |
| config_schema | object | 配置参数的 JSON Schema 定义 |
| create_time | string | 创建时间 (ISO 8601) |

#### 用例

**请求**:
```bash
curl -X GET "http://localhost:8000/api/v1/agent/configs"
```

**响应** (200 OK):
```json
[
  {
    "agent_id": "echo-agent-001",
    "agent_type_id": "uuid-echo-xxxx",
    "agent_type_name": "echo_agent",
    "description": "一个简单的回显 Agent，用于测试",
    "config_schema": {},
    "create_time": "2026-01-20T10:00:00Z"
  },
  {
    "agent_id": "risk-agent-001",
    "agent_type_id": "uuid-risk-assessment-xxx",
    "agent_type_name": "risk-assessment",
    "description": "企业风险评估 Agent",
    "config_schema": {},
    "create_time": "2026-01-20T10:00:00Z",
  }
]
```

---

### 2.2 获取指定 Agent 配置

根据 agent_id 获取指定的 Agent 配置信息。

**接口路径**: `GET /api/v1/agent/config/{agent_id}`

#### 路径参数

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| agent_id | string | 是 | Agent 唯一标识 |

#### 用例 1: 配置存在

**请求**:
```bash
curl -X GET "http://localhost:8000/api/v1/agent/config/echo-agent-001"
```

**响应** (200 OK):
```json
{
  "agent_id": "echo-agent-001",
  "agent_type_id": "uuid-echo-xxx",
  "agent_type_name": "echo_agent",
  "description": "一个简单的回显 Agent，用于测试",
  "config_schema": {},
  "create_time": "2026-01-20T10:00:00Z",
}
```

#### 用例 2: 配置不存在

**请求**:
```bash
curl -X GET "http://localhost:8000/api/v1/agent/config/non-existent"
```

**响应** (404 Not Found):
```json
{
  "detail": "配置不存在: non-existent"
}
```

---

### 2.3 添加/更新 Agent 配置

添加或更新 Agent 配置信息。

**接口路径**: `POST /api/v1/agent/config`

**Content-Type**: `application/json`

#### 请求参数

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| agent_config_id | string | 是 | 配置记录ID |
| agent_id | string | 是 | Agent 唯一标识 |
| agent_type_id | string | 是 | Agent 类型标识符 |
| agent_type_name | string | 是 | Agent 类型显示名称 |
| description | string | 否 | Agent 功能描述 |
| config_schema | object | 否 | 配置参数的 JSON Schema 定义 |

#### 用例

**请求**:
```bash
curl -X POST "http://localhost:8000/api/v1/agent/config" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_config_id": "cfg-my-custom-agent-001",
    "agent_id": "my-custom-agent-001",
    "agent_type_id": "uuid-echo-xxx",
    "agent_type_name": "echo_agent",
    "description": "自定义的回显 Agent"
  }'
```

**响应** (200 OK):
```json
{
  "success": true,
  "message": "配置已添加: my-custom-agent-001"
}
```

---

### 2.4 删除 Agent 配置

删除指定的 Agent 配置信息。

**接口路径**: `DELETE /api/v1/agent/config/{agent_id}`

#### 路径参数

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| agent_id | string | 是 | Agent 唯一标识 |

#### 用例 1: 删除成功

**请求**:
```bash
curl -X DELETE "http://localhost:8000/api/v1/agent/config/my-custom-agent-001"
```

**响应** (200 OK):
```json
{
  "success": true,
  "message": "配置已删除: my-custom-agent-001"
}
```

#### 用例 2: 删除失败

**请求**:
```bash
curl -X DELETE "http://localhost:8000/api/v1/agent/config/non-existent"
```

**响应** (500 Internal Server Error):
```json
{
  "detail": "删除配置失败"
}
```

---

## 3. 健康状态接口

### 3.1 获取所有 Agent 健康状态

获取所有活跃 Agent 的健康状态信息。

**接口路径**: `GET /api/v1/agent/health`

#### 响应格式

返回 `AgentHealthStatus` 数组。

| 字段 | 类型 | 描述 |
|------|------|------|
| agent_id | string | Agent 唯一标识 |
| agent_type_id | string | Agent 类型标识符 |
| agent_type_name | string | Agent 类型显示名称 |
| status | string | 状态: healthy / unhealthy / unknown |
| checks | object | 健康检查详情 |
| checks.alive | boolean | Agent 是否存活 |
| checks.responsive | boolean | Agent 是否响应 |
| checks.task_queue_healthy | boolean | 任务队列是否健康 |
| uptime_seconds | float | 运行时间（秒） |
| checked_at | string | 检查时间 (ISO 8601) |

#### 用例

**请求**:
```bash
curl -X GET "http://localhost:8000/api/v1/agent/health"
```

**响应** (200 OK):
```json
[
  {
    "agent_id": "echo-agent-001",
    "agent_type_id": "uuid-echo-xxx",
    "agent_type_name": "echo_agent",
    "status": "healthy",
    "checks": {
      "alive": true,
      "responsive": true,
      "task_queue_healthy": true
    },
    "uptime_seconds": 3600.5,
    "checked_at": "2026-01-22T11:30:00Z"
  }
]
```

---

### 3.2 获取指定 Agent 健康状态

根据 agent_id 获取指定 Agent 的健康状态。

**接口路径**: `GET /api/v1/agent/health/{agent_id}`

#### 路径参数

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| agent_id | string | 是 | Agent 唯一标识 |

#### 用例 1: Agent 存在

**请求**:
```bash
curl -X GET "http://localhost:8000/api/v1/agent/health/echo-agent-001"
```

**响应** (200 OK):
```json
{
  "agent_id": "echo-agent-001",
  "agent_type_id": "uuid-echo-xxx",
  "agent_type_name": "echo_agent",
  "status": "healthy",
  "checks": {
    "alive": true,
    "responsive": true,
    "task_queue_healthy": true
  },
  "uptime_seconds": 7200.0,
  "checked_at": "2026-01-22T12:00:00Z"
}
```

#### 用例 2: Agent 不存在

**请求**:
```bash
curl -X GET "http://localhost:8000/api/v1/agent/health/non-existent"
```

**响应** (404 Not Found):
```json
{
  "detail": "Agent 不存在: non-existent"
}
```

---

## 4. Agent 管理接口

### 4.1 获取活跃 Agent 列表

获取所有已创建的 Agent 的 agent_id 列表。

**接口路径**: `GET /api/v1/agent/list`

#### 用例

**请求**:
```bash
curl -X GET "http://localhost:8000/api/v1/agent/list"
```

**响应** (200 OK):
```json
[
  "echo-agent-001",
  "risk-agent-001",
  "my-custom-agent-001"
]
```

---

### 4.2 停止指定 Agent

停止并移除指定的 Agent。

**接口路径**: `POST /api/v1/agent/stop/{agent_id}`

#### 路径参数

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| agent_id | string | 是 | Agent 唯一标识 |

#### 用例 1: 停止成功

**请求**:
```bash
curl -X POST "http://localhost:8000/api/v1/agent/stop/echo-agent-001"
```

**响应** (200 OK):
```json
{
  "success": true,
  "message": "Agent 已停止: echo-agent-001"
}
```

#### 用例 2: Agent 不存在

**请求**:
```bash
curl -X POST "http://localhost:8000/api/v1/agent/stop/non-existent"
```

**响应** (404 Not Found):
```json
{
  "detail": "Agent 不存在或停止失败: non-existent"
}
```

---

### 4.3 重启指定 Agent

重启指定的 Agent。

**接口路径**: `POST /api/v1/agent/restart/{agent_id}`

#### 路径参数

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| agent_id | string | 是 | Agent 唯一标识 |

#### 用例 1: 重启成功

**请求**:
```bash
curl -X POST "http://localhost:8000/api/v1/agent/restart/echo-agent-001"
```

**响应** (200 OK):
```json
{
  "success": true,
  "message": "Agent 已重启: echo-agent-001"
}
```

#### 用例 2: 重启失败

**请求**:
```bash
curl -X POST "http://localhost:8000/api/v1/agent/restart/non-existent"
```

**响应** (500 Internal Server Error):
```json
{
  "detail": "Agent 重启失败: non-existent"
}
```

---

## 5. 轨迹查询接口

### 5.1 获取 Agent 轨迹历史

获取 Agent 运行轨迹历史记录。

**接口路径**: `GET /api/v1/agent/trajectories`

#### 查询参数

| 参数 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| agent_id | string | 否 | - | 按 Agent ID 筛选 |
| session_id | string | 否 | - | 按会话 ID 筛选 |
| limit | integer | 否 | 100 | 返回记录数量限制 |

#### 响应格式

返回 `AgentTrajectory` 数组。

| 字段 | 类型 | 描述 |
|------|------|------|
| agent_id | string | Agent 唯一标识 |
| session_id | string | 会话 ID |
| user_id | string | 用户 ID |
| trajectory | object | 轨迹信息 |
| trajectory.steps | array | 轨迹步骤列表 |
| create_time | string | 创建时间 (ISO 8601) |
| update_time | string | 更新时间 (ISO 8601) |

**TrajectoryStep 结构**:

| 字段 | 类型 | 描述 |
|------|------|------|
| step | integer | 步骤序号 |
| state | any | 当前环境的观测值 |
| action | any | 智能体采取的操作 |
| reward | float | 奖励值 |
| next_state | any | 执行动作后的观测值 |
| is_terminal | boolean | 是否为终止状态 |

#### 用例 1: 获取所有轨迹

**请求**:
```bash
curl -X GET "http://localhost:8000/api/v1/agent/trajectories"
```

**响应** (200 OK):
```json
[
  {
    "agent_id": "echo-agent-001",
    "session_id": "session-67890",
    "user_id": "user-12345",
    "trajectory": {
      "steps": [
        {
          "step": 0,
          "state": "接收用户输入",
          "action": "处理消息",
          "reward": 0.0,
          "next_state": "生成响应",
          "is_terminal": false
        },
        {
          "step": 1,
          "state": "生成响应",
          "action": "返回结果",
          "reward": 1.0,
          "next_state": "完成",
          "is_terminal": true
        }
      ]
    },
    "create_time": "2026-01-22T10:30:00Z",
    "update_time": "2026-01-22T10:30:00Z"
  }
]
```

#### 用例 2: 按 agent_id 筛选

**请求**:
```bash
curl -X GET "http://localhost:8000/api/v1/agent/trajectories?agent_id=echo-agent-001&limit=10"
```

**响应** (200 OK):
```json
[
  {
    "agent_id": "echo-agent-001",
    "session_id": "session-67890",
    "user_id": "user-12345",
    "trajectory": {
      "steps": []
    },
    "create_time": "2026-01-22T10:30:00Z",
    "update_time": "2026-01-22T10:30:00Z"
  }
]
```

#### 用例 3: 按 session_id 筛选

**请求**:
```bash
curl -X GET "http://localhost:8000/api/v1/agent/trajectories?session_id=session-67890"
```

---

## 6. 服务状态接口

### 6.1 获取服务状态

获取服务整体运行状态。

**接口路径**: `GET /api/v1/service/status`

#### 响应格式

| 字段 | 类型 | 描述 |
|------|------|------|
| status | string | 服务状态: running / stopped |
| agent_count | integer | 当前活跃的 Agent 数量 |
| config_count | integer | 已加载的配置数量 |
| health_reporter_running | boolean | 健康上报服务是否运行中 |
| database_connected | boolean | 数据库是否已连接 |

#### 用例

**请求**:
```bash
curl -X GET "http://localhost:8000/api/v1/service/status"
```

**响应** (200 OK):
```json
{
  "status": "running",
  "agent_count": 3,
  "config_count": 5,
  "health_reporter_running": true,
  "database_connected": true
}
```

---

### 6.2 触发健康状态上报

立即触发一次健康状态上报。

**接口路径**: `POST /api/v1/service/health-report`

#### 用例

**请求**:
```bash
curl -X POST "http://localhost:8000/api/v1/service/health-report"
```

**响应** (200 OK):
```json
{
  "success": true,
  "message": "健康状态上报已触发"
}
```

---

## 错误码说明

| HTTP 状态码 | 描述 |
|-------------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 422 | 请求数据验证失败 |
| 500 | 服务器内部错误 |

### 错误响应格式

```json
{
  "detail": "错误描述信息"
}
```

---

## 流式事件类型说明

| 事件类型 | 描述 | data 示例 |
|----------|------|-----------|
| start | 任务开始 | `{"message": "开始处理"}` |
| thinking | 思考/推理中 | `{"message": "正在分析问题..."}` |
| content | 输出内容块 | `{"text": "这是一段输出内容"}` |
| tool_call | 调用工具 | `{"tool": "search", "args": {"query": "xxx"}}` |
| tool_result | 工具返回结果 | `{"tool": "search", "result": "..."}` |
| error | 发生错误 | `{"message": "错误信息", "code": "ERROR_CODE"}` |
| done | 任务完成 | `{"message": "处理完成", "execution_time": 1.5}` |

---

## 完整测试脚本

```bash
#!/bin/bash
# Agent Engine Service API 测试脚本

BASE_URL="http://localhost:8000/api/v1"

echo "=== 1. 获取服务状态 ==="
curl -s "$BASE_URL/service/status" | jq .

echo -e "\n=== 2. 获取所有配置 ==="
curl -s "$BASE_URL/agent/configs" | jq .

echo -e "\n=== 3. 添加新配置 ==="
curl -s -X POST "$BASE_URL/agent/config" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "test-agent-001",
    "agent_type_id": "uuid-echo-xxx",
    "agent_type_name": "echo_agent"
  }' | jq .

echo -e "\n=== 4. 执行任务（同步） ==="
curl -s -X POST "$BASE_URL/agent/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "echo-agent-001",
    "user_id": "test-user",
    "input": {"message": "Hello, World!"}
  }' | jq .

echo -e "\n=== 5. 执行任务（流式） ==="
curl -X POST "$BASE_URL/agent/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "echo-agent-001",
    "user_id": "test-user",
    "input": {"message": "流式测试"},
    "stream": true
  }'

echo -e "\n\n=== 6. 获取活跃 Agent 列表 ==="
curl -s "$BASE_URL/agent/list" | jq .

echo -e "\n=== 7. 获取健康状态 ==="
curl -s "$BASE_URL/agent/health" | jq .

echo -e "\n=== 8. 获取轨迹历史 ==="
curl -s "$BASE_URL/agent/trajectories?limit=5" | jq .

echo -e "\n=== 9. 删除测试配置 ==="
curl -s -X DELETE "$BASE_URL/agent/config/test-agent-001" | jq .

echo -e "\n=== 测试完成 ==="
```

---

*文档版本: 1.0.0*
*最后更新: 2026年1月22日*
