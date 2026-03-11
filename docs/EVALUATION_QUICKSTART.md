# 智能体轨迹评估系统 - 快速开始

## 快速开始（5分钟）

### 1. 配置 LLM API

编辑 `.env` 文件，添加你的 API Key：

```bash
# 使用 DeepSeek（推荐，性价比高）
EVALUATION_LLM_API_KEY=sk-your-deepseek-api-key
```

或者编辑 `config/evaluation_config.yaml` 切换到其他模型：

```yaml
llm:
  provider: "openai"  # 或 qwen, gemini, gateway
  model_name: "gpt-4"
  api_key: "${EVALUATION_LLM_API_KEY}"
  api_base: "https://api.openai.com/v1"
```

### 2. 启动服务

```bash
python run.py
```

### 3. 调用评估接口

当智能体执行完成，轨迹写入数据库后，调用评估接口：

```bash
curl -X POST "http://localhost:8000/api/v1/evaluation/evaluate" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "your-agent-id",
    "user_id": "your-user-id",
    "session_id": "your-session-id"
  }'
```

### 4. 查看评估结果

```bash
# 按 ID 查询
curl -X GET "http://localhost:8000/api/v1/evaluation/result/1"

# 按条件查询
curl -X GET "http://localhost:8000/api/v1/evaluation/results?agent_id=your-agent-id"
```

## 核心概念

### 评估流程

```
轨迹写入数据库 → 调用评估接口 → LLM 分析 → 保存评估结果
```

### 评估维度

1. **信号捕捉敏锐度**: 是否准确识别风险信号
2. **逻辑推演**: 是否合理结合硬信息和软信息
3. **处置建议合理性**: 建议是否符合业务常识

### 评分标准

- 每个步骤: 0-10 分
- 整体评分: 0-10 分
- 附带详细评分理由

## 集成示例

### Python 代码集成

```python
from src.services.evaluation import get_trajectory_evaluator

# 在轨迹写入完成后
async def on_trajectory_saved(agent_id, user_id, session_id):
    evaluator = get_trajectory_evaluator()
    
    response = await evaluator.evaluate_trajectory(
        agent_id=agent_id,
        user_id=user_id,
        session_id=session_id
    )
    
    if response.success:
        print(f"评估完成，总分: {response.evaluation.overall.score}")
    else:
        print(f"评估失败: {response.error}")
```

### HTTP API 集成

```python
import httpx

async def trigger_evaluation(agent_id, user_id, session_id):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/v1/evaluation/evaluate",
            json={
                "agent_id": agent_id,
                "user_id": user_id,
                "session_id": session_id
            }
        )
        return response.json()
```

## 自定义评估标准

编辑 `config/evaluation_config.yaml`：

```yaml
evaluation_prompt:
  system_prompt: |
    # 你的自定义评估标准
    
    ## 评分维度 1: 准确性
    - 评估要点...
    
    ## 评分维度 2: 完整性
    - 评估要点...
```

## 支持的 LLM 模型

| 提供商 | 配置示例 | 说明 |
|--------|----------|------|
| DeepSeek | `provider: "deepseek"` | 推荐，性价比高 |
| OpenAI | `provider: "openai"` | GPT-4, GPT-3.5 |
| 通义千问 | `provider: "qwen"` | 阿里云 |
| Gemini | `provider: "gemini"` | Google |
| 模型网关 | `provider: "gateway"` | 自定义网关 |

## 常见问题

### Q: 评估失败怎么办？

A: 检查以下几点：
1. LLM API Key 是否正确
2. 数据库中是否存在对应轨迹
3. 网络是否可访问 LLM API
4. 查看日志获取详细错误

### Q: 如何避免重复评估？

A: 默认情况下，相同的 `(agent_id, user_id, session_id)` 只会评估一次。如需重新评估，设置 `force_reevaluate: true`。

### Q: 评估需要多长时间？

A: 通常 5-30 秒，取决于：
- 轨迹步骤数量
- LLM 响应速度
- 网络延迟

### Q: 如何批量评估？

A: 使用 Python 的 `asyncio.gather` 并发调用：

```python
tasks = [
    evaluator.evaluate_trajectory(agent_id, user_id, session_id)
    for agent_id, user_id, session_id in batch_data
]
results = await asyncio.gather(*tasks)
```

## 测试

运行测试脚本：

```bash
python tests/test_evaluation.py
```

## 下一步

- 阅读完整文档: [docs/EVALUATION.md](./EVALUATION.md)
- 查看 API 文档: [docs/API.md](./API.md)
- 自定义评估标准
- 集成到你的业务流程

## 技术支持

如有问题，请查看：
1. 日志文件（如果配置了 `LOG_FILE`）
2. 控制台输出
3. 完整文档 `docs/EVALUATION.md`

---

*快速开始指南 v1.0*
