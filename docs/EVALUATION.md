# 智能体轨迹评估系统使用文档

## 概述

智能体轨迹评估系统用于对风控智能体的执行轨迹进行自动化评估和打分。系统通过大语言模型（LLM）对智能体的每个执行步骤进行分析，给出评分和评价理由。

## 系统架构

```
其他组件 → 通知评估器 → 查询数据库 → 调用 LLM → 保存评估结果
```

## 核心功能

1. **轨迹查询**: 从数据库查询智能体的完整执行轨迹
2. **LLM 评估**: 使用大模型对轨迹进行评估和打分
3. **结果存储**: 将评估结果保存到数据库
4. **结果查询**: 提供 API 查询评估结果

## 数据库表设计

### 表名: `T_AGENT_TRAJECTORY_EVALUATION`

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | integer | 是 | 评估记录 ID（自增主键） |
| agent_id | string | 是 | Agent 的唯一标识符 |
| user_id | string | 是 | 用户 ID |
| session_id | string | 是 | 会话 ID |
| trajectory | object | 是 | 智能体运行轨迹（汇总后的 steps） |
| evaluation | object | 是 | 评估结果（包含 overall 和 steps） |
| evaluated_at | datetime | 是 | 评估时间 |
| evaluator_model | string | 是 | 使用的评估模型名称 |
| evaluation_prompt_version | string | 是 | 评估 Prompt 版本 |

### evaluation 字段结构

```json
{
  "overall": {
    "score": 7,
    "reason": "整体逻辑合理，风险识别准确"
  },
  "steps": [
    {
      "step": 0,
      "score": 7,
      "reason": "信号捕捉准确，处理逻辑合理"
    },
    {
      "step": 1,
      "score": 8,
      "reason": "风险评估全面，建议具体可行"
    }
  ]
}
```

## 配置说明

### 1. LLM 配置

编辑 `config/evaluation_config.yaml` 文件：

```yaml
llm:
  # 模型提供商: gateway/openai/deepseek/qwen/gemini
  provider: "deepseek"
  
  # 模型名称
  model_name: "deepseek-chat"
  
  # API 配置
  api_key: "${EVALUATION_LLM_API_KEY}"  # 从环境变量读取
  api_base: "https://api.deepseek.com/v1"
  
  # 模型参数
  temperature: 0.7
  max_tokens: 2000
  timeout: 60
```

### 2. 支持的 LLM 提供商

#### (1) 模型网关

```yaml
llm:
  provider: "gateway"
  model_name: "your-model-name"
  api_key: "your-gateway-api-key"
  api_base: "https://your-gateway-url.com"
```

#### (2) DeepSeek

```yaml
llm:
  provider: "deepseek"
  model_name: "deepseek-chat"
  api_key: "sk-xxx"
  api_base: "https://api.deepseek.com/v1"
```

#### (3) OpenAI

```yaml
llm:
  provider: "openai"
  model_name: "gpt-4"
  api_key: "sk-xxx"
  api_base: "https://api.openai.com/v1"
```

#### (4) 阿里云通义千问

```yaml
llm:
  provider: "qwen"
  model_name: "qwen-turbo"
  api_key: "sk-xxx"
  api_base: "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

#### (5) Google Gemini

```yaml
llm:
  provider: "gemini"
  model_name: "gemini-pro"
  api_key: "your-gemini-api-key"
  api_base: "https://generativelanguage.googleapis.com/v1beta"
```

### 3. 评估 Prompt 配置

在 `config/evaluation_config.yaml` 中自定义评估标准：

```yaml
evaluation_prompt:
  version: "v1.0"
  
  # 系统 Prompt（定义评估标准）
  system_prompt: |
    # Role
    你是一位【银行贷后资产保全专家】。你的任务是审核AI生成的贷后风险预警报告。
    
    # Audit Criteria (评分标准)
    ## Dimension 1: 信号捕捉敏锐度
    - AI 是否准确捕捉到了关键风险信号？
    ...
  
  # 用户 Prompt 模板
  user_prompt_template: |
    请对以下智能体的执行轨迹进行评估和打分。
    ...
```

### 4. 环境变量配置

在 `.env` 文件中设置：

```bash
# 评估 LLM API Key
EVALUATION_LLM_API_KEY=sk-your-api-key-here
```

## API 使用指南

### 1. 触发评估

**接口**: `POST /api/v1/evaluation/evaluate`

**请求示例**:

```bash
curl -X POST "http://localhost:8000/api/v1/evaluation/evaluate" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent-550e8400-e29b-41d4-a716-446655440000",
    "user_id": "user-12345",
    "session_id": "agent-session-550e8400",
    "force_reevaluate": false
  }'
```

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| agent_id | string | 是 | Agent 的唯一标识符 |
| user_id | string | 是 | 用户 ID |
| session_id | string | 是 | 会话 ID |
| force_reevaluate | boolean | 否 | 是否强制重新评估（默认 false） |

**响应示例**:

```json
{
  "success": true,
  "message": "评估完成",
  "evaluation_id": 1,
  "evaluation": {
    "overall": {
      "score": 7,
      "reason": "整体逻辑合理，风险识别准确"
    },
    "steps": [
      {
        "step": 0,
        "score": 7,
        "reason": "信号捕捉准确，处理逻辑合理"
      }
    ]
  },
  "error": null
}
```

### 2. 查询评估结果（按 ID）

**接口**: `GET /api/v1/evaluation/result/{evaluation_id}`

**请求示例**:

```bash
curl -X GET "http://localhost:8000/api/v1/evaluation/result/1"
```

**响应示例**:

```json
{
  "id": 1,
  "agent_id": "agent-550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user-12345",
  "session_id": "agent-session-550e8400",
  "trajectory": {
    "steps": [...]
  },
  "evaluation": {
    "overall": {...},
    "steps": [...]
  },
  "evaluated_at": "2026-01-23T10:00:00",
  "evaluator_model": "deepseek-chat",
  "evaluation_prompt_version": "v1.0"
}
```

### 3. 查询评估结果列表

**接口**: `GET /api/v1/evaluation/results`

**请求示例**:

```bash
# 查询所有评估结果
curl -X GET "http://localhost:8000/api/v1/evaluation/results?limit=10"

# 按 agent_id 筛选
curl -X GET "http://localhost:8000/api/v1/evaluation/results?agent_id=agent-550e8400&limit=10"

# 按 session_id 筛选
curl -X GET "http://localhost:8000/api/v1/evaluation/results?session_id=agent-session-550e8400"
```

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| agent_id | string | 否 | 按 Agent ID 筛选 |
| user_id | string | 否 | 按用户 ID 筛选 |
| session_id | string | 否 | 按会话 ID 筛选 |
| limit | integer | 否 | 返回记录数限制（默认 100） |

## 使用流程

### 完整流程示例

```python
# 1. 其他组件：智能体执行完成，轨迹已写入数据库
# （这部分由现有系统自动完成）

# 2. 其他组件：通知评估器进行评估
import httpx

async def notify_evaluation(agent_id: str, user_id: str, session_id: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/v1/evaluation/evaluate",
            json={
                "agent_id": agent_id,
                "user_id": user_id,
                "session_id": session_id,
                "force_reevaluate": False
            }
        )
        result = response.json()
        print(f"评估完成: {result}")
        return result

# 3. 查询评估结果
async def get_evaluation(evaluation_id: int):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"http://localhost:8000/api/v1/evaluation/result/{evaluation_id}"
        )
        result = response.json()
        print(f"评估结果: {result}")
        return result
```

### Python SDK 示例

```python
from src.services.evaluation import get_trajectory_evaluator

# 获取评估器实例
evaluator = get_trajectory_evaluator()

# 执行评估
response = await evaluator.evaluate_trajectory(
    agent_id="agent-550e8400-e29b-41d4-a716-446655440000",
    user_id="user-12345",
    session_id="agent-session-550e8400",
    force_reevaluate=False
)

if response.success:
    print(f"评估成功，ID: {response.evaluation_id}")
    print(f"总分: {response.evaluation.overall.score}")
    print(f"评价: {response.evaluation.overall.reason}")
else:
    print(f"评估失败: {response.error}")
```

## 评估标准说明

系统默认使用银行贷后资产保全的评估标准，包括三个维度：

### Dimension 1: 信号捕捉敏锐度
- 评估 AI 是否准确捕捉到关键风险信号
- 例如：账户冻结、停业、诉讼等负面信号

### Dimension 2: 逻辑推演
- 评估 AI 是否结合了硬信息和软信息
- 例如：老客户 + 欠息 → 应建议密切关注

### Dimension 3: 处置建议合理性
- 评估 AI 给出的建议是否符合贷后管理常识
- 高风险 → 启动催收、查封资产
- 中风险 → 增加回访频次
- 低风险 → 常规监测

## 自定义评估标准

如需自定义评估标准，修改 `config/evaluation_config.yaml` 中的 `system_prompt` 部分：

```yaml
evaluation_prompt:
  system_prompt: |
    # 你的自定义评估标准
    
    ## 评分维度 1: ...
    - 评估要点 1
    - 评估要点 2
    
    ## 评分维度 2: ...
    - 评估要点 1
    - 评估要点 2
```

## 故障排查

### 1. 评估失败

**问题**: 评估接口返回 `success: false`

**排查步骤**:
1. 检查数据库中是否存在对应的轨迹记录
2. 检查 LLM API Key 是否正确配置
3. 检查 LLM API 是否可访问
4. 查看日志文件获取详细错误信息

### 2. LLM 响应解析失败

**问题**: 日志显示 "解析 LLM 响应 JSON 失败"

**原因**: LLM 返回的格式不符合预期

**解决方案**:
1. 调整 `user_prompt_template`，强调输出格式要求
2. 降低 `temperature` 参数，提高输出稳定性
3. 检查 LLM 返回的原始内容（在日志中）

### 3. 评估超时

**问题**: 评估请求超时

**解决方案**:
1. 增加 `timeout` 配置（默认 60 秒）
2. 减少 `max_tokens` 参数
3. 检查网络连接

## 性能优化

### 1. 启用评估缓存

在 `config/evaluation_config.yaml` 中：

```yaml
settings:
  enable_cache: true
```

启用后，相同的 `(agent_id, user_id, session_id)` 不会重复评估。

### 2. 批量评估

如需批量评估多个轨迹，可以并发调用评估接口：

```python
import asyncio

async def batch_evaluate(requests):
    tasks = [
        evaluator.evaluate_trajectory(**req)
        for req in requests
    ]
    results = await asyncio.gather(*tasks)
    return results
```

## 最佳实践

1. **及时评估**: 在轨迹写入数据库后立即触发评估
2. **错误处理**: 评估失败不应影响主业务流程
3. **日志记录**: 记录评估请求和结果，便于审计
4. **定期审查**: 定期审查评估结果，优化评估标准
5. **版本管理**: 使用 `evaluation_prompt_version` 跟踪 Prompt 版本

## 扩展开发

### 添加新的 LLM 提供商

1. 在 `src/services/evaluation/llm_client.py` 中创建新的客户端类：

```python
class NewProviderClient(BaseLLMClient):
    async def chat_completion(self, messages, **kwargs) -> str:
        # 实现调用逻辑
        pass
```

2. 在 `LLMClientFactory` 中注册：

```python
@staticmethod
def create_client(config: LLMConfig) -> BaseLLMClient:
    if provider == "new-provider":
        return NewProviderClient(config)
    ...
```

### 自定义评估逻辑

继承 `TrajectoryEvaluator` 类并重写 `_evaluate_with_llm` 方法：

```python
class CustomEvaluator(TrajectoryEvaluator):
    async def _evaluate_with_llm(self, ...):
        # 自定义评估逻辑
        pass
```

---

*文档版本: 1.0.0*  
*最后更新: 2026年1月23日*
