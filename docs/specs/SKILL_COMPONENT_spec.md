# 技能组件（技能发现和管理）需求规格说明书

> **项目名称**: AgentEngine-dev  
> **特性标识**: SKILL_COMPONENT  
> **版本**: v1.0  
> **编写日期**: 2026-04-07  
> **编写人员**: 业务分析师 (BA)  
> **项目模式**: 增量模式

---

## 1. 需求背景与目标

### 1.1 背景

当前系统已有 `SkillMgr`（`src/skills/skillmgr.py`），具备技能扫描、注册、执行的基础能力，并配合 `SkillRefreshTimer` 实现定时增量刷新。但现有能力存在以下缺口：

1. **无 REST API 暴露**：技能的注册、卸载、查询、热重载均无 HTTP 接口，运维与外部系统集成只能依赖定时刷新或直接操作 `registry.json` 文件。
2. **注册方式单一**：仅支持启动时扫描 `skills_root` 目录 + `registry.json` 持久化回放，不支持运行时通过 API 动态注册新技能。
3. **无细粒度热重载**：缺乏对单个技能的热重载能力，仅能通过全量刷新（`refresh_skills_incremental`）间接实现。

### 1.2 目标

在现有 `SkillMgr` 基础上增强补齐（**不做大重构**），实现以下目标：

1. 暴露 6 个 REST API 端点，覆盖技能的 CRUD 和运行时控制
2. 支持运行时通过本地路径动态注册技能
3. 支持单个技能热重载和全量扫描刷新
4. 确保不破坏现有 `SkillMgr` 的已有功能（扫描、执行、定时刷新）

---

## 2. 功能需求列表

### 2.1 核心功能需求

#### [REQ_SKILL_COMPONENT_001] 技能列表查询

**需求描述**: 提供 `GET /api/v1/skills` 端点，返回当前已注册的所有技能列表，包含技能元数据（名称、描述、是否可执行、注册来源、注册时间）。

**详细规格**:

- **路径**: `GET /api/v1/skills`
- **响应结构**:
  ```json
  {
    "success": true,
    "data": [
      {
        "name": "web_calc_skill",
        "description": "对 numbers 做汇总统计",
        "executable": true,
        "source": "builtin",
        "registered_at": "2026-04-07T12:00:00+00:00",
        "entry_module": "run.py",
        "entry_function": "run"
      }
    ],
    "total": 1
  }
  ```
- 数据来源：`SkillMgr._skill_records` 内存索引
- `executable` 字段由 `record.handler is not None` 判定
- 无需查询参数，返回全部技能；如需筛选由调用方自行过滤

**验收条件**:

| 编号 | 条件 | 优先级 |
|-----|------|--------|
| AC-001-1 | 端点返回 200，结构符合上述 schema | P0 |
| AC-001-2 | 已注册技能全部出现在列表中 | P0 |
| AC-001-3 | `executable` 字段准确反映 handler 绑定状态 | P0 |

---

#### [REQ_SKILL_COMPONENT_002] 技能详情查询

**需求描述**: 提供 `GET /api/v1/skills/{name}` 端点，返回指定技能的完整元数据。

**详细规格**:

- **路径**: `GET /api/v1/skills/{name}`
- **路径参数**: `name` — 技能名称（对应 `SkillRecord.name`）
- **响应结构**:
  ```json
  {
    "success": true,
    "data": {
      "name": "web_calc_skill",
      "description": "对 numbers 做汇总统计",
      "executable": true,
      "source": "builtin",
      "registered_at": "2026-04-07T12:00:00+00:00",
      "path": "src/skills/web_calc_skill",
      "entry_module": "run.py",
      "entry_function": "run",
      "input_schema": { "type": "object", "properties": { ... } }
    }
  }
  ```
- 技能不存在时返回 `404`：`{"success": false, "detail": "技能不存在: {name}"}`

**验收条件**:

| 编号 | 条件 | 优先级 |
|-----|------|--------|
| AC-002-1 | 已注册技能返回 200 及完整元数据 | P0 |
| AC-002-2 | 不存在的技能名返回 404 | P0 |
| AC-002-3 | `input_schema` 字段为完整 JSON Schema 对象 | P1 |

---

#### [REQ_SKILL_COMPONENT_003] 技能注册

**需求描述**: 提供 `POST /api/v1/skills` 端点，通过传入技能目录的本地路径，系统扫描该目录并注册技能。

**详细规格**:

- **路径**: `POST /api/v1/skills`
- **请求体**:
  ```json
  {
    "skill_path": "/absolute/or/relative/path/to/skill_dir",
    "skill_name": "optional_custom_name"
  }
  ```
  - `skill_path`（必填）：本地目录路径，系统将验证该路径存在且为目录
  - `skill_name`（可选）：自定义技能名，不传则取目录名作为技能名
- **处理流程**:
  1. 校验 `skill_path` 存在且为目录，不存在返回 `400`
  2. 解析技能名：优先使用 `skill_name`，否则取 `skill_path` 的最后一级目录名
  3. 检测同名技能是否已存在；如存在返回 `409 Conflict`
  4. 调用 `SkillMgr` 注册：创建 `SkillRecord`，写入 `_skill_records`
  5. 尝试自动绑定 handler（解析 `SKILL.md` front-matter + 动态加载 `entry_module`）
  6. 持久化到 `registry.json`（调用现有 `_flush_registry_file()`）
  7. 同步 `t_skill_exe_info` 表
- **响应结构**:
  ```json
  {
    "success": true,
    "message": "技能已注册: my_skill",
    "data": {
      "name": "my_skill",
      "executable": true,
      "source": "api-register"
    }
  }
  ```
- **错误响应**:
  - `400`：路径不存在或非目录
  - `409`：同名技能已注册

**验收条件**:

| 编号 | 条件 | 优先级 |
|-----|------|--------|
| AC-003-1 | 传入合法路径，技能注册成功，返回 200 | P0 |
| AC-003-2 | 注册后通过 `GET /skills` 可查到该技能 | P0 |
| AC-003-3 | 注册后 `registry.json` 中包含该技能记录 | P0 |
| AC-003-4 | 无效路径返回 400 | P0 |
| AC-003-5 | 重复注册同名技能返回 409 | P1 |
| AC-003-6 | 若技能目录包含有效的 `SKILL.md` + `entry_module`，handler 自动绑定 | P1 |

---

#### [REQ_SKILL_COMPONENT_004] 技能卸载

**需求描述**: 提供 `DELETE /api/v1/skills/{name}` 端点，卸载指定技能，同步清除内存索引和 `registry.json` 持久化。

**详细规格**:

- **路径**: `DELETE /api/v1/skills/{name}`
- **路径参数**: `name` — 技能名称
- **处理流程**:
  1. 检查技能是否存在，不存在返回 `404`
  2. 从 `_skill_records` 中移除该 `SkillRecord`
  3. 从 `_skill_meta_cache` 中移除缓存
  4. 调用 `_flush_registry_file()` 重写 `registry.json`
  5. 同步更新 `t_skill_exe_info` 表（将该技能标记为不可执行或删除记录）
- **响应结构**:
  ```json
  {
    "success": true,
    "message": "技能已卸载: my_skill"
  }
  ```
- **注意事项**:
  - 卸载仅清除注册信息，**不删除磁盘上的技能目录文件**
  - 卸载后若该技能正被某 Agent 的 `tool_calls` 引用，后续调用将返回"skill 未实现或不可执行"——这是预期行为
  - builtin 类型技能（如 `web_calc_skill`）允许卸载，下次全量刷新或重启不会自动恢复

**验收条件**:

| 编号 | 条件 | 优先级 |
|-----|------|--------|
| AC-004-1 | 卸载后 `GET /skills` 列表中不再包含该技能 | P0 |
| AC-004-2 | 卸载后 `registry.json` 中不再包含该技能记录 | P0 |
| AC-004-3 | 不存在的技能名返回 404 | P0 |
| AC-004-4 | 卸载后再次调用 `execute_skill` 返回"未实现或不可执行" | P1 |

---

#### [REQ_SKILL_COMPONENT_005] 单个技能热重载

**需求描述**: 提供 `POST /api/v1/skills/{name}/reload` 端点，对指定技能执行全量重载：从磁盘重新扫描该技能目录，替换内存中的 handler 和元数据。

**详细规格**:

- **路径**: `POST /api/v1/skills/{name}/reload`
- **路径参数**: `name` — 技能名称
- **处理流程**:
  1. 检查技能是否存在，不存在返回 `404`
  2. 清除该技能的 `_skill_meta_cache` 缓存
  3. 重新从磁盘解析 `SKILL.md` front-matter，更新 `description` 和 `input_schema`
  4. 重新动态加载 `entry_module` → `entry_function`，替换 `handler`
  5. 更新 `_skill_records` 中对应记录的 `registered_at` 为当前时间
  6. 调用 `_flush_registry_file()` 持久化
  7. 同步 `t_skill_exe_info` 表
- **响应结构**:
  ```json
  {
    "success": true,
    "message": "技能已重载: my_skill",
    "data": {
      "name": "my_skill",
      "executable": true,
      "previous_executable": true
    }
  }
  ```
- **边界情况**:
  - 若重载后 `SKILL.md` 或 `entry_module` 缺失/损坏，handler 将变为 `None`，`executable` 变为 `false`——这是合法结果，接口仍返回 `200`
  - 重载期间通过 `asyncio.Lock` 保证与注册/卸载/刷新操作互斥

**验收条件**:

| 编号 | 条件 | 优先级 |
|-----|------|--------|
| AC-005-1 | 修改技能目录中的 `SKILL.md` 后调用 reload，`description` 更新 | P0 |
| AC-005-2 | 修改 `entry_module` 代码后调用 reload，新 handler 生效 | P0 |
| AC-005-3 | 不存在的技能名返回 404 | P0 |
| AC-005-4 | 重载后 `registry.json` 中 `registered_at` 更新 | P1 |
| AC-005-5 | 入口文件损坏时重载不抛异常，`executable` 变为 false | P1 |

---

#### [REQ_SKILL_COMPONENT_006] 全量扫描刷新

**需求描述**: 提供 `POST /api/v1/skills/refresh` 端点，触发全量扫描 `skills_root` 目录，发现新技能并注册。

**详细规格**:

- **路径**: `POST /api/v1/skills/refresh`
- **处理逻辑**: 复用现有 `SkillMgr.refresh_skills_incremental()` 方法，与 `SkillRefreshTimer` 定时触发的逻辑一致
- **响应结构**:
  ```json
  {
    "success": true,
    "message": "技能全量刷新完成",
    "stats": {
      "added_from_registry": 0,
      "added_from_local_scan": 2,
      "total_records": 5,
      "total_executable": 3
    }
  }
  ```
- **与现有端点的关系**: 现有 `POST /api/v1/service/skills-refresh` 功能相同，本需求新增 `/api/v1/skills/refresh` 作为技能资源组的规范路径。两个端点共存不冲突，后续可考虑废弃旧路径。

**验收条件**:

| 编号 | 条件 | 优先级 |
|-----|------|--------|
| AC-006-1 | 调用后新放入 `skills_root` 的技能目录被发现并注册 | P0 |
| AC-006-2 | 返回 `stats` 包含准确的增量计数 | P0 |
| AC-006-3 | 已有技能不受影响（不重复注册、不覆盖 handler） | P0 |
| AC-006-4 | 不破坏 `SkillRefreshTimer` 的定时刷新逻辑 | P0 |

---

### 2.2 配置需求

#### [REQ_SKILL_COMPONENT_007] API 路由挂载

**需求描述**: 新增技能管理 API 路由模块，在 `app.py` 中挂载到主应用。

**新增配置项**:

| 配置项 | 环境变量 | 类型 | 默认值 | 说明 |
|-------|---------|------|--------|------|
| 技能 API 前缀 | — | str | `/api/v1` | 与现有 API 路由保持一致 |

**验收条件**:

| 编号 | 条件 | 优先级 |
|-----|------|--------|
| AC-007-1 | 新路由模块独立文件，不侵入现有 `router.py` | P0 |
| AC-007-2 | 在 `app.py` 的 lifespan 中完成路由挂载 | P0 |
| AC-007-3 | 所有 6 个端点可通过 HTTP 访问 | P0 |

---

## 3. 非功能需求

### 3.1 性能指标

| 指标 | 目标值 | 测量方法 |
|-----|--------|---------|
| 技能列表查询响应时间 | ≤ 50ms (P95) | 100 次请求取 P95 |
| 单个技能热重载时间 | ≤ 500ms (P95) | 含磁盘 I/O + 模块加载 |
| 全量刷新时间 | ≤ 2s (P95) | 假设 ≤50 个技能 |
| 并发注册/卸载互斥等待 | 无死锁 | 并发压力测试验证 |

### 3.2 可靠性指标

| 指标 | 目标值 | 说明 |
|-----|--------|------|
| 注册/卸载后 registry.json 一致性 | 100% | 内存与文件必须同步 |
| 热重载原子性 | handler 旧→新无中间态 | Lock 保护下完成替换 |
| API 错误响应格式统一 | 100% | 遵循现有 `{"success": false, "detail": "..."}` 风格 |

### 3.3 安全性需求

| 需求 | 说明 |
|-----|------|
| 路径校验 | `skill_path` 必须为合法目录路径，拒绝文件路径和不存在的路径 |
| 无认证 | 与现有 API 保持一致，当前系统无认证机制（存量债务 M6），本次不做额外增加 |

---

## 4. 影响范围分析

### 4.1 新增模块

| 模块路径 | 职责 | 说明 |
|---------|------|------|
| `src/api/skill_router.py` | 技能管理 API 路由 | 6 个端点定义，调用 SkillMgr |
| `src/models/skill_schemas.py` | 技能相关 Pydantic 模型 | 请求/响应数据模型 |

### 4.2 修改模块

| 模块路径 | 修改内容 | 影响程度 |
|---------|---------|---------|
| `src/skills/skillmgr.py` | 新增 `unregister_skill()`、`reload_skill()` 方法 | 中 |
| `src/app.py` | `include_router(skill_router)` 挂载新路由 | 低 |

### 4.3 API 变更

| 变更类型 | API | 说明 |
|---------|-----|------|
| 新增 | `GET /api/v1/skills` | 技能列表 |
| 新增 | `GET /api/v1/skills/{name}` | 技能详情 |
| 新增 | `POST /api/v1/skills` | 技能注册 |
| 新增 | `DELETE /api/v1/skills/{name}` | 技能卸载 |
| 新增 | `POST /api/v1/skills/{name}/reload` | 单个技能热重载 |
| 新增 | `POST /api/v1/skills/refresh` | 全量扫描刷新 |
| 保留 | `POST /api/v1/service/skills-refresh` | 现有端点不改动，功能与新 `/skills/refresh` 重复 |

### 4.4 数据库变更

无新增表。`t_skill_exe_info` 表为现有表，注册/卸载/重载操作通过现有 `upsert_skill_exe_info()` 函数同步。

---

## 5. 兼容性分析

### 5.1 向后兼容

- 现有 `SkillMgr` 的所有公开方法（`initialize`、`refresh_skills_incremental`、`register_builtin_skill`、`register_skill`、`list_available_skills`、`execute_skill`）签名和行为不变
- 现有 `SkillRefreshTimer` 的定时刷新逻辑不受影响
- 现有 `POST /api/v1/service/skills-refresh` 端点保留不动
- `SkillDemoAgent` 通过 `register_builtin_skill` 注册的 `web_calc_skill` 行为不变
- `registry.json` 格式不变，新增字段向后兼容

### 5.2 版本依赖

- 依赖现有 `SkillMgr` 单例机制（`get_skill_manager()`）
- 依赖现有 `asyncio.Lock` 互斥机制
- 依赖现有 `upsert_skill_exe_info()` 数据库函数
- 无新增第三方依赖

### 5.3 升级路径

- 部署后即可使用，无需数据迁移
- 旧端点 `/service/skills-refresh` 可继续使用，待后续版本统一废弃

---

## 6. 验收标准

### 6.1 功能验收

| 编号 | 验收项 | 验收方法 | 责任方 |
|-----|--------|---------|--------|
| FAT-01 | 6 个 API 端点全部返回正确状态码 | 单元测试 + 手动 curl 验证 | 开发 |
| FAT-02 | 注册后列表和详情 API 可查到 | 注册 → 列表查询 → 详情查询 | 开发 |
| FAT-03 | 卸载后内存和 registry.json 同步清除 | 卸载 → 查询 404 → 检查 registry.json | 开发 |
| FAT-04 | 热重载后 handler 和元数据更新 | 修改文件 → reload → 验证新行为 | 开发 |
| FAT-05 | 全量刷新发现新技能 | 新建目录 → refresh → 列表包含 | 开发 |
| FAT-06 | 现有功能不受影响 | 运行现有 `test_skillmgr.py` 全通过 | 开发 |
| FAT-07 | SkillRefreshTimer 定时刷新正常 | 启动后等待定时触发，验证无异常 | 开发 |

### 6.2 性能验收

| 编号 | 验收项 | 目标 | 验收方法 |
|-----|--------|-----|---------|
| PAT-01 | 列表查询 P95 延迟 | ≤ 50ms | 压测脚本 100 次 |
| PAT-02 | 热重载 P95 延迟 | ≤ 500ms | 压测脚本 50 次 |

### 6.3 兼容性验收

| 编号 | 验收项 | 验收方法 |
|-----|--------|---------|
| CAT-01 | 现有 `SkillDemoAgent` 的 `llm_select_and_call_skill` 正常执行 | 运行现有集成测试 |
| CAT-02 | `POST /service/skills-refresh` 仍可用 | curl 验证 |
| CAT-03 | `SkillRefreshTimer` 定时循环正常运行 | 日志验证 |

---

## 7. 依赖关系

### 7.1 需求依赖图

```
[REQ_007] 路由挂载
    ├── [REQ_001] 列表查询
    ├── [REQ_002] 详情查询
    ├── [REQ_003] 技能注册
    ├── [REQ_004] 技能卸载
    ├── [REQ_005] 热重载
    └── [REQ_006] 全量刷新
```

[REQ_007] 是所有端点的前置条件——路由必须先挂载，端点才可达。[REQ_003/004/005] 依赖 `SkillMgr` 新增方法。[REQ_006] 复用现有方法，无额外依赖。

### 7.2 实施优先级

1. **Phase 1**：[REQ_007] 路由挂载 + [REQ_001/002] 只读端点 → 快速验证框架
2. **Phase 2**：[REQ_003] 注册 + [REQ_004] 卸载 → CRUD 闭环
3. **Phase 3**：[REQ_005] 热重载 + [REQ_006] 全量刷新 → 运维能力补齐

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| `registry.json` 并发写入冲突 | 数据丢失或格式损坏 | 所有写操作通过 `asyncio.Lock` 串行化，已有机制 |
| 动态加载恶意 `entry_module` | 安全风险 | 当前系统无认证（存量债务 M6），本次沿袭现状；后续版本应增加路径白名单 |
| 热重载期间旧 handler 正在执行 | 请求结果不确定 | 现有 `execute_skill` 为同步调用 handler，重载在 Lock 保护下完成；若 handler 为长时间运行任务，存在替换窗口。建议在 reload 响应中标注"正在执行的调用使用旧 handler" |
| `skill_path` 传入系统敏感路径 | 信息泄露/越权 | 校验路径必须在 `skills_root` 范围内或明确白名单目录内（**[TO_CLARIFY]** 是否限制路径范围？当前设计未限制） |

---

## 9. 附录

### 9.1 技术选型说明

- **路由框架**：复用 FastAPI + `APIRouter`，与现有 `router.py` 风格一致
- **数据模型**：Pydantic v2，与现有 `schemas.py` 风格一致
- **SkillMgr 扩展方式**：在现有类上新增方法，不改变类结构

### 9.2 相关文件路径

| 文件 | 路径 |
|-----|------|
| SkillMgr 实现 | `src/skills/skillmgr.py` |
| 定时刷新器 | `src/services/skill_refresh_timer.py` |
| 现有 API 路由 | `src/api/router.py` |
| 应用工厂 | `src/app.py` |
| 示例 Agent | `src/agents/skill_demo_agent/skill_demo_agent.py` |
| 存量摸排报告 | `.staging/legacy_code_anatomy.md` |
| 注册表文件 | `src/skills/registry.json` |
| 示例技能 | `src/skills/web_calc_skill/` |

### 9.3 参考文档

- 现有 API 风格参考：`src/api/router.py` 中所有端点的装饰器、响应结构、错误处理模式
- 现有 SkillMgr 方法参考：`register_skill()`、`refresh_skills_incremental()`、`_auto_bind_executable_skills()`

---

**文档版本**: v1.0  
**最后更新**: 2026-04-07  
**审核状态**: 待评审
