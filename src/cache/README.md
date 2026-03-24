# Redis 缓存模块

基于 Redis 的分布式缓存模块，为 AgentEngine 提供高性能缓存支持。

## 📋 功能特性

- ✅ **Redis 客户端集成**：支持单机模式和哨兵模式
- ✅ **连接池管理**：自动管理连接池，优化性能
- ✅ **重试机制**：使用 tenacity 实现自动重试
- ✅ **序列化支持**：默认 JSON 序列化，可选 Pickle
- ✅ **缓存键安全**：URL 编码 + 长度限制
- ✅ **TTL 随机化**：防止缓存雪崩
- ✅ **降级策略**：Redis 故障时自动降级
- ✅ **监控指标**：Prometheus 指标采集
- ✅ **Pydantic 支持**：自动序列化/反序列化 Pydantic 模型

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 基础使用

```python
from src.cache import RedisClient, RedisConfig, CacheManager, CacheKeyBuilder, CacheTTL

# 1. 创建 Redis 客户端
config = RedisConfig(host="127.0.0.1", port=6379)
redis_client = RedisClient(config)
await redis_client.connect()

# 2. 创建缓存管理器
cache_manager = CacheManager(redis_client)

# 3. 设置缓存
await cache_manager.set(
    key=CacheKeyBuilder.agent_config("agent_001"),
    value={"name": "Test Agent"},
    ttl=CacheTTL.AGENT_CONFIG
)

# 4. 获取缓存
data = await cache_manager.get(CacheKeyBuilder.agent_config("agent_001"))

# 5. 断开连接
await redis_client.disconnect()
```

## 📁 模块结构

```
src/cache/
├── __init__.py           # 模块入口
├── constants.py          # 缓存键、TTL 常量
├── redis_client.py       # Redis 客户端
├── cache_manager.py      # 缓存管理器
├── serializer.py         # 序列化器
├── metrics.py            # 监控指标
└── key_builder.py        # 缓存键构建器
```

## 🔧 核心组件

### 1. RedisClient

Redis 客户端，支持单机和哨兵模式。

```python
from src.cache import RedisClient, RedisConfig

# 单机模式
config = RedisConfig(host="127.0.0.1", port=6379)
client = RedisClient(config)

# 哨兵模式
config = RedisConfig(
    sentinel_enabled=True,
    sentinel_master_name="mymaster",
    sentinel_hosts=["redis-sentinel-1:26379", "redis-sentinel-2:26379"]
)
client = RedisClient(config)

# 连接
await client.connect()

# 基础操作
value = await client.get("key")
await client.set("key", "value", ex=3600)
await client.delete("key")

# 断开连接
await client.disconnect()
```

### 2. CacheManager

缓存管理器，提供统一的缓存操作接口。

```python
from src.cache import CacheManager

cache_manager = CacheManager(redis_client)

# 基础操作
data = await cache_manager.get("key")
await cache_manager.set("key", data, ttl=3600)
await cache_manager.delete("key")

# Read-Through 模式
data = await cache_manager.get_with_fallback(
    key="agent:config:001",
    loader=lambda: db.get_config("001"),
    ttl=3600
)

# 批量删除
count = await cache_manager.delete_pattern("agent:config:*")

# 健康检查
health = await cache_manager.health_check()
stats = await cache_manager.get_stats()
```

### 3. CacheKeyBuilder

缓存键构建器，提供统一的键命名规范。

```python
from src.cache import CacheKeyBuilder

# Agent 配置
key = CacheKeyBuilder.agent_config("agent_001")
# -> "agent_engine:agent:config:agent_001"

# Agent 模板
key = CacheKeyBuilder.agent_template("tpl_echo")
# -> "agent_engine:template:config:tpl_echo"

# 会话历史
key = CacheKeyBuilder.session_history("session_123")
# -> "agent_engine:session:history:session_123"

# 自定义键
builder = CacheKeyBuilder()
safe_key = builder.build("custom:key:with spaces")
```

### 4. CacheSerializer

序列化器，支持 JSON 和 Pickle。

```python
from src.cache import CacheSerializer
from pydantic import BaseModel

class MyModel(BaseModel):
    id: str
    name: str

serializer = CacheSerializer()

# 序列化
json_str = serializer.serialize({"id": "001", "name": "Test"})

# 反序列化
data = serializer.deserialize(json_str)

# Pydantic 模型支持
model = MyModel(id="001", name="Test")
json_str = serializer.serialize(model)
model = serializer.deserialize(json_str, model_class=MyModel)
```

### 5. CacheMetrics

监控指标采集器，集成 Prometheus。

```python
from src.cache import CacheMetrics

# 记录指标
CacheMetrics.record_hit("agent_config")
CacheMetrics.record_miss("agent_config")
CacheMetrics.record_latency("get", "agent_config", 0.005)

# 指标会自动暴露到 /metrics 端点
```

## 📊 监控指标

缓存模块自动采集以下 Prometheus 指标：

| 指标 | 类型 | 说明 |
|------|------|------|
| `cache_hits_total` | Counter | 缓存命中次数 |
| `cache_misses_total` | Counter | 缓存未命中次数 |
| `cache_latency_seconds` | Histogram | 操作延迟分布 |
| `cache_degradation_total` | Counter | 降级事件次数 |
| `cache_fallback_total` | Counter | 数据库回源次数 |
| `redis_connections_active` | Gauge | 活跃连接数 |
| `redis_errors_total` | Counter | Redis 错误次数 |

## ⚙️ 配置

### Redis 配置

```yaml
redis:
  host: "127.0.0.1"
  port: 6379
  db: 0
  password: ""
  max_connections: 50
  socket_timeout: 5
  socket_connect_timeout: 3
  retry_on_timeout: true
```

### TTL 配置

```python
from src.cache import CacheTTL

# 使用预定义的 TTL
ttl = CacheTTL.AGENT_CONFIG  # 1 小时
ttl = CacheTTL.AGENT_TEMPLATE  # 24 小时
ttl = CacheTTL.SESSION_HISTORY  # 30 分钟
```

## 🧪 测试

运行单元测试：

```bash
pytest tests/test_cache/ -v
```

## 📖 更多示例

详细示例请参考：
- [缓存集成指南](.staging/docs/cache_integration_guide.md)
- [示例代码](examples/cache_example.py)

## 🛠️ 故障排查

### 缓存命中率低

```bash
# 检查缓存键数量
redis-cli DBSIZE

# 检查 TTL 配置
cat config/cache_config.yaml | grep ttl
```

### Redis 连接问题

```bash
# 检查 Redis 状态
redis-cli PING

# 检查连接数
redis-cli INFO clients

# 检查内存使用
redis-cli INFO memory
```

## 📝 版本历史

- **v1.0.0** (2026-03-12)
  - ✅ 实现 Redis 客户端
  - ✅ 实现缓存管理器
  - ✅ 实现序列化器
  - ✅ 实现缓存键构建器
  - ✅ 实现监控指标
  - ✅ 集成到 ConfigManager
  - ✅ 单元测试覆盖 >80%

## 📄 许可证

内部项目，仅供 AgentEngine 使用。
