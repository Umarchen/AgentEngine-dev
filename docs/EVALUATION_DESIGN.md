# 智能体轨迹评估系统 - 设计方案

## 1. 需求分析

### 1.1 核心需求

1. **接口通知**: 提供函数接口，其他组件通过 `agent_id`, `user_id`, `session_id` 通知轨迹写入完成
2. **轨迹查询**: 从数据库查询智能体的完整运行轨迹（所有 steps）
3. **LLM 评估**: 使用大模型对轨迹进行评估和打分
4. **结果存储**: 将评估结果保存到新的数据库表
5. **配置灵活**: 支持多种 LLM 提供商和自定义评估标准

### 1.2 技术要求

- 不改动现有代码
- 支持模型网关和第三方模型（DeepSeek, Qwen, Gemini, OpenAI）
- 评估 Prompt 可配置
- 对每个 step 进行评估并汇总

## 2. 系统设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      其他组件                                │
│              (轨迹写入完成后通知评估器)                        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   评估器 API 层                              │
│  POST /api/v1/evaluation/evaluate                           │
│  GET  /api/v1/evaluation/result/{id}                        │
│  GET  /api/v1/evaluation/results                            │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              TrajectoryEvaluator (核心评估器)                │
│  - evaluate_trajectory()      # 主入口                       │
│  - _fetch_trajectories()      # 查询轨迹                     │
│  - _aggregate_trajectories()  # 汇总步骤                     │
│  - _evaluate_with_llm()       # LLM 评估                     │
│  - _parse_llm_response()      # 解析结果                     │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│PromptManager │    │  LLMClient   │    │DatabaseManager│
│  (Prompt管理) │    │  (LLM调用)   │    │  (数据库操作) │
└──────────────┘    └──────────────┘    └──────────────┘
```

### 2.2 目录结构

```
src/
├── services/
│   └── evaluation/              # 新增：评估服务
│       ├── __init__.py
│       ├── evaluator.py         # 核心评估器
│       ├── llm_client.py        # LLM 客户端封装
│       └── prompt_manager.py    # Prompt 管理器
├── models/
│   └── evaluation_schemas.py    # 新增：评估数据模型
├── database/
│   └── database.py              # 扩展：添加评估相关操作
├── api/
│   └── router.py                # 扩展：添加评估 API
└── config/
    └── evaluation_config.yaml   # 新增：评估配置文件
```

### 2.3 数据库设计

#### 新表: T_AGENT_TRAJECTORY_EVALUATION

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键，自增 |
| agent_id | VARCHAR | Agent ID |
| user_id | VARCHAR | 用户 ID |
| session_id | VARCHAR | 会话 ID |
| trajectory | JSON | 汇总后的轨迹（包含所有 steps） |
| evaluation | JSON | 评估结果（overall + steps） |
| evaluated_at | DATETIME | 评估时间 |
| evaluator_model | VARCHAR | 评估模型名称 |
| evaluation_prompt_version | VARCHAR | Prompt 版本 |

#### evaluation 字段结构

```json
{
  "overall": {
    "score": 7,
    "reason": "整体逻辑合理"
  },
  "steps": [
    {
      "step": 0,
      "score": 7,
      "reason": "信号捕捉准确"
    },
    {
      "step": 1,
      "score": 8,
      "reason": "处理逻辑合理"
    }
  ]
}
```

## 3. 核心组件设计

### 3.1 TrajectoryEvaluator（评估器）

**职责**:
- 接收评估请求
- 查询和汇总轨迹
- 调用 LLM 评估
- 保存评估结果

**关键方法**:

```python
class TrajectoryEvaluator:
    async def evaluate_trajectory(
        self,
        agent_id: str,
        user_id: str,
        session_id: str,
        force_reevaluate: bool = False
    ) -> EvaluationResponse:
        """主入口：评估轨迹"""
        
    async def _fetch_trajectories(...) -> List[Dict]:
        """从数据库查询轨迹"""
        
    def _aggregate_trajectories(...) -> Dict:
        """汇总轨迹步骤"""
        
    async def _evaluate_with_llm(...) -> Evaluation:
        """使用 LLM 评估"""
        
    def _parse_llm_response(...) -> Evaluation:
        """解析 LLM 响应"""
```

### 3.2 LLMClient（LLM 客户端）

**设计模式**: 工厂模式 + 策略模式

**支持的提供商**:
- `OpenAICompatibleClient`: OpenAI, DeepSeek, Qwen
- `GatewayClient`: 自定义模型网关
- `GeminiClient`: Google Gemini

**接口**:

```python
class BaseLLMClient(ABC):
    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> str:
        """调用 LLM 进行对话补全"""
        pass

class LLMClientFactory:
    @staticmethod
    def create_client(config: LLMConfig) -> BaseLLMClient:
        """根据配置创建对应的客户端"""
        pass
```

### 3.3 PromptManager（Prompt 管理器）

**职责**:
- 从配置文件加载 Prompt
- 构建评估 Prompt
- 支持 Prompt 版本管理

**关键方法**:

```python
class PromptManager:
    def get_system_prompt(self) -> str:
        """获取系统 Prompt（评估标准）"""
        
    def get_user_prompt_template(self) -> str:
        """获取用户 Prompt 模板"""
        
    def build_user_prompt(
        self,
        agent_id: str,
        user_id: str,
        session_id: str,
        trajectory: Dict
    ) -> str:
        """构建完整的用户 Prompt"""
```

### 3.4 DatabaseManager 扩展

**新增方法**:

```python
# 保存评估结果
async def save_trajectory_evaluation(
    self,
    evaluation_record: TrajectoryEvaluationRecord
) -> int:
    """保存评估结果，返回记录 ID"""

# 查询评估结果
async def get_trajectory_evaluation(
    self,
    agent_id: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    evaluation_id: Optional[int] = None
) -> Optional[TrajectoryEvaluationRecord]:
    """查询单条评估结果"""

async def get_trajectory_evaluations(
    self,
    agent_id: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 100
) -> List[TrajectoryEvaluationRecord]:
    """查询多条评估结果"""
```

## 4. 数据流设计

### 4.1 评估流程

```
1. 其他组件调用评估接口
   POST /api/v1/evaluation/evaluate
   {
     "agent_id": "xxx",
     "user_id": "xxx",
     "session_id": "xxx"
   }
   
2. 评估器检查缓存
   - 如果已存在评估结果，直接返回
   - 否则继续评估流程
   
3. 查询数据库获取轨迹
   SELECT * FROM T_AGENT_TRAJECTORY
   WHERE agent_id = ? AND user_id = ? AND session_id = ?
   
4. 汇总轨迹步骤
   - 合并所有 trajectory.steps
   - 按 step 编号排序
   - 重新编号确保连续
   
5. 构建评估 Prompt
   - 加载系统 Prompt（评估标准）
   - 构建用户 Prompt（包含轨迹数据）
   
6. 调用 LLM 评估
   - 发送请求到 LLM API
   - 等待响应
   
7. 解析 LLM 响应
   - 提取 JSON 格式的评估结果
   - 验证和补全缺失的步骤评估
   
8. 保存评估结果
   INSERT INTO T_AGENT_TRAJECTORY_EVALUATION
   (agent_id, user_id, session_id, trajectory, evaluation, ...)
   VALUES (?, ?, ?, ?, ?, ...)
   
9. 返回评估结果
   {
     "success": true,
     "evaluation_id": 1,
     "evaluation": {...}
   }
```

### 4.2 数据模型

```python
# 评估请求
EvaluationRequest:
  - agent_id: str
  - user_id: str
  - session_id: str
  - force_reevaluate: bool

# 评估响应
EvaluationResponse:
  - success: bool
  - message: str
  - evaluation_id: Optional[int]
  - evaluation: Optional[Evaluation]
  - error: Optional[str]

# 评估结果
Evaluation:
  - overall: OverallEvaluation
    - score: int (0-10)
    - reason: str
  - steps: List[StepEvaluation]
    - step: int
    - score: int (0-10)
    - reason: str

# 评估记录（数据库）
TrajectoryEvaluationRecord:
  - id: Optional[int]
  - agent_id: str
  - user_id: str
  - session_id: str
  - trajectory: Dict
  - evaluation: Evaluation
  - evaluated_at: datetime
  - evaluator_model: str
  - evaluation_prompt_version: str
```

## 5. 配置设计

### 5.1 配置文件结构

```yaml
# config/evaluation_config.yaml

# LLM 配置
llm:
  provider: "deepseek"           # 提供商
  model_name: "deepseek-chat"    # 模型名称
  api_key: "${ENV_VAR}"          # API Key（支持环境变量）
  api_base: "https://..."        # API 基础 URL
  temperature: 0.7               # 温度参数
  max_tokens: 2000               # 最大 token 数
  timeout: 60                    # 超时时间

# 评估 Prompt 配置
evaluation_prompt:
  version: "v1.0"                # Prompt 版本
  system_prompt: |               # 系统 Prompt（评估标准）
    # Role
    你是一位银行贷后资产保全专家...
    
    # Audit Criteria
    ## Dimension 1: 信号捕捉敏锐度
    ...
  
  user_prompt_template: |        # 用户 Prompt 模板
    请对以下智能体的执行轨迹进行评估...
    
    ## 智能体信息
    - Agent ID: {agent_id}
    ...

# 其他配置
settings:
  enable_cache: true             # 启用评估缓存
  max_retries: 3                 # 失败重试次数
  evaluation_timeout: 120        # 评估超时时间
```

### 5.2 环境变量

```bash
# .env
EVALUATION_LLM_API_KEY=sk-your-api-key-here
```

## 6. API 设计

### 6.1 评估接口

```
POST /api/v1/evaluation/evaluate

Request:
{
  "agent_id": "string",
  "user_id": "string",
  "session_id": "string",
  "force_reevaluate": false
}

Response:
{
  "success": true,
  "message": "评估完成",
  "evaluation_id": 1,
  "evaluation": {
    "overall": {
      "score": 7,
      "reason": "..."
    },
    "steps": [...]
  },
  "error": null
}
```

### 6.2 查询接口

```
GET /api/v1/evaluation/result/{evaluation_id}

Response:
{
  "id": 1,
  "agent_id": "...",
  "evaluation": {...},
  "evaluated_at": "2026-01-23T10:00:00",
  ...
}
```

```
GET /api/v1/evaluation/results?agent_id=xxx&limit=10

Response:
[
  {
    "id": 1,
    "agent_id": "...",
    ...
  },
  ...
]
```

## 7. 扩展性设计

### 7.1 添加新的 LLM 提供商

1. 创建新的客户端类继承 `BaseLLMClient`
2. 实现 `chat_completion` 方法
3. 在 `LLMClientFactory` 中注册

### 7.2 自定义评估标准

修改 `config/evaluation_config.yaml` 中的 `system_prompt`

### 7.3 自定义评估逻辑

继承 `TrajectoryEvaluator` 并重写相关方法

## 8. 性能优化

### 8.1 评估缓存

- 相同的 `(agent_id, user_id, session_id)` 不重复评估
- 通过 `force_reevaluate` 参数强制重新评估

### 8.2 异步处理

- 所有 I/O 操作使用 `async/await`
- 支持并发评估多个轨迹

### 8.3 超时控制

- LLM 调用超时（默认 60 秒）
- 整体评估超时（默认 120 秒）

## 9. 错误处理

### 9.1 错误类型

1. **轨迹不存在**: 返回错误信息
2. **LLM 调用失败**: 重试机制 + 默认评分
3. **响应解析失败**: 使用默认评分
4. **数据库错误**: 记录日志并返回错误

### 9.2 降级策略

当 LLM 评估失败时，返回默认评估：
- 所有步骤评分 5 分
- 理由: "评估失败，使用默认分数"

## 10. 测试策略

### 10.1 单元测试

- LLM 客户端测试（Mock API）
- Prompt 构建测试
- 响应解析测试

### 10.2 集成测试

- 完整评估流程测试
- 数据库操作测试
- API 接口测试

### 10.3 测试脚本

`tests/test_evaluation.py` 提供完整的测试流程

## 11. 部署建议

### 11.1 配置检查

1. 确保 LLM API Key 正确配置
2. 检查网络连接（能否访问 LLM API）
3. 验证数据库连接

### 11.2 监控指标

- 评估成功率
- 评估耗时
- LLM API 调用失败率
- 数据库查询性能

### 11.3 日志记录

- 评估请求日志
- LLM 调用日志
- 错误日志
- 性能日志

## 12. 安全考虑

### 12.1 API Key 安全

- 使用环境变量存储
- 不在日志中输出
- 定期轮换

### 12.2 输入验证

- 验证 agent_id, user_id, session_id 格式
- 限制查询结果数量
- 防止 SQL 注入

### 12.3 访问控制

- API 鉴权（如需要）
- 限流保护
- 防止滥用

## 13. 总结

### 13.1 设计亮点

1. **模块化设计**: 评估逻辑独立，不影响现有代码
2. **灵活配置**: 支持多种 LLM 和自定义评估标准
3. **可扩展性**: 易于添加新的 LLM 提供商
4. **容错性**: 完善的错误处理和降级策略
5. **性能优化**: 异步处理 + 评估缓存

### 13.2 技术栈

- **Web 框架**: FastAPI
- **异步**: asyncio
- **HTTP 客户端**: httpx
- **配置管理**: YAML + Pydantic
- **日志**: Loguru

### 13.3 文件清单

**新增文件**:
- `src/services/evaluation/evaluator.py`
- `src/services/evaluation/llm_client.py`
- `src/services/evaluation/prompt_manager.py`
- `src/services/evaluation/__init__.py`
- `src/models/evaluation_schemas.py`
- `config/evaluation_config.yaml`
- `docs/EVALUATION.md`
- `docs/EVALUATION_QUICKSTART.md`
- `docs/EVALUATION_DESIGN.md`
- `tests/test_evaluation.py`

**修改文件**:
- `src/database/database.py` (扩展评估相关方法)
- `src/api/router.py` (添加评估 API)
- `.env.example` (添加 LLM API Key 配置)

---

*设计文档 v1.0*  
*最后更新: 2026年1月23日*
