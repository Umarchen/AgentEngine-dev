# OpenClaw 目录与调试指南

## 一、两套目录：运行态 vs 源代码

| 概念 | 路径 | 作用 |
|------|------|------|
| **运行态目录（状态/数据目录）** | `~/.openclaw`（默认） | 配置、会话、插件、工作区等**运行时数据**。调试运行中的 OpenClaw 主要看这里。 |
| **源代码目录** | 例如 `/home/ubuntu/openclaw` | 项目源码（TypeScript/JS）。**仅在你改代码、构建、跑测试时用**，对已安装的 `openclaw` 运行态无影响。 |

- 运行态目录可通过环境变量 **`OPENCLAW_STATE_DIR`**（或旧版 `CLAWDBOT_STATE_DIR`）覆盖，默认是 **`$HOME/.openclaw`**。
- 你当前机器上运行态目录为：**`/home/ubuntu/.openclaw`**。

---

## 二、运行态目录结构（~/.openclaw）

```
~/.openclaw/
├── openclaw.json              # 主配置文件（模型、网关、agents、插件等）
├── openclaw.json.backup-*     # 配置自动备份（按时间）
├── openclaw.json.bak*        # 其他备份
├── exec-approvals.json       # 执行审批状态
├── update-check.json         # 更新检查状态
│
├── agents/                    # 各 Agent 的“安装”目录（二进制/脚本等）
│   ├── main/
│   ├── analyst-agent/
│   ├── architect-agent/
│   └── devops-agent/
│
├── extensions/                # 用户安装的插件（如 openclaw-agent-dashboard）
│   └── openclaw-agent-dashboard/
│
├── identity/                  # 设备/身份
│   ├── device.json
│   └── device-auth.json
│
├── devices/                   # 配对设备
│   ├── paired.json
│   └── pending.json
│
├── logs/                      # 日志
│   ├── commands.log
│   └── config-audit.jsonl
│
├── memory/                    # 全局记忆（如 Qdrant 等持久化）
│   └── main.sqlite
│
├── cron/                      # 定时任务
│   └── jobs.json
│
├── subagents/                 # 子 Agent 相关运行时
│
├── canvas/                    # Canvas 相关
├── completions/               # 补全相关
├── docs/                      # 文档/生成物
├── dashboard/                 # Dashboard 相关
│
├── workspace-main/            # 默认/主 Agent 的工作目录（见下节）
├── workspace-analyst/        # analyst-agent 的工作目录
├── workspace-architect/       # architect-agent 的工作目录
├── workspace-devops/          # devops-agent 的工作目录
├── workspace-backup/
└── workspace-*                # 其他 Agent 的 workspace-<agentId>
```

---

## 三、工作目录（Agent Workspace）是什么

- **工作目录** = 某个 Agent 的“工作区根目录”。Agent 读写的项目文件、AGENTS.md、SOUL.md、MEMORY.md、skills 等都在对应的工作目录下。
- 由配置里的 **`agents.defaults.workspace`** 或 **`agents.list[].workspace`** 决定；未配置时默认规则：
  - 默认 Agent：`~/.openclaw/workspace` 或（若设了 `OPENCLAW_PROFILE`）`~/.openclaw/workspace-<profile>`。
  - 其他 Agent：`~/.openclaw/workspace-<agentId>`（例如 `workspace-analyst`）。
- 你当前配置里默认工作目录是：**`~/.openclaw/workspace-main`**，即 **`/home/ubuntu/.openclaw/workspace-main`**。

### workspace-main 典型结构

```
~/.openclaw/workspace-main/
├── .openclaw/
│   └── workspace-state.json   # 工作区状态（如 bootstrap 时间等）
├── .git/
├── AGENTS.md                  # Agent 说明（给模型读）
├── BOOTSTRAP.md
├── HEARTBEAT.md
├── IDENTITY.md
├── MEMORY.md
├── SOUL.md
├── TOOLS.md
├── USER.md
├── avatars/
├── docs/
├── memory/
├── skills/
└── (你的项目文件)
```

调试时：
- 看“当前在干什么” → 看 **运行态目录** `~/.openclaw`（尤其是 `openclaw.json`、`logs/`、`agents/`）。
- 看“Agent 在哪个目录干活、读了哪些文件” → 看 **工作目录**（如 `~/.openclaw/workspace-main`）。

---

## 四、各文件/目录作用速查（运行态 ~/.openclaw）

| 路径 | 作用 |
|------|------|
| **openclaw.json** | 主配置：模型、网关端口、auth、agents 列表、defaults.workspace、插件、cron、会话等。改配置或排查配置问题先看这里。 |
| **exec-approvals.json** | 执行类操作的审批状态。 |
| **agents/** | 各 Agent 的运行文件（由 openclaw 安装/更新时写入）。一般不改，除非排查 agent 加载问题。 |
| **extensions/** | 用户安装的插件。调试插件时看对应插件子目录。 |
| **identity/** | 设备标识与认证。 |
| **devices/** | 已配对/待配对设备。 |
| **logs/** | 命令日志、配置审计日志等。排查运行错误可看这里。 |
| **memory/** | 全局记忆存储（如 SQLite）。 |
| **cron/** | 定时任务定义。 |
| **subagents/** | 子 Agent 运行时数据。 |
| **workspace-*** | 各 Agent 的工作目录；主 Agent 的即你配置的 `agents.defaults.workspace`（当前为 workspace-main）。 |

---

## 五、调试时常用环境变量（运行态）

- **OPENCLAW_STATE_DIR**：覆盖状态目录，默认 `~/.openclaw`。例如：`export OPENCLAW_STATE_DIR=/tmp/oc-debug` 可单独起一套数据做调试。
- **OPENCLAW_CONFIG_PATH**：覆盖配置文件路径，默认 `$OPENCLAW_STATE_DIR/openclaw.json`。
- **OPENCLAW_HOME**：覆盖“主目录”用于 ~ 展开；显示路径时会用 `$OPENCLAW_HOME` 代替实际路径。
- **OPENCLAW_GATEWAY_PORT**：网关端口（与 config 中 gateway.port 一致即可）。
- **OPENCLAW_GATEWAY_TOKEN** / **OPENCLAW_GATEWAY_PASSWORD**：网关认证（优先于配置文件，便于安全调试）。

这些只影响**运行态**从哪里读配置和数据，与源代码目录无关。

---

## 六、源代码目录（仅改代码用）

- 典型路径：**`/home/ubuntu/openclaw`**（你本机 clone 下来的仓库）。
- 结构要点：
  - **src/**：TypeScript 源码（网关、agent、插件、配置解析等）。
  - **src/config/paths.ts**：解析 `OPENCLAW_STATE_DIR`、状态目录、配置路径（`resolveStateDir`、`resolveConfigPath` 等）。
  - **src/utils.ts**：`resolveConfigDir()`，与 paths 一起决定“配置根目录”。
  - **src/agents/agent-scope.ts**：`resolveAgentWorkspaceDir()`，决定每个 Agent 的工作目录。
  - **src/agents/workspace.ts**：工作区模板、默认工作区路径、BOOTSTRAP 等。
  - **extensions/**：官方/内置插件源码。
  - **scripts/**：系统服务、Podman 等脚本。
- 修改这里只影响**从源码构建并运行**的 openclaw（例如 `pnpm build` 后 `pnpm openclaw` 或 `node dist/...`）；**不影响**已通过 `npm install -g openclaw` 安装的运行时，除非你重新安装或链接到该源码构建结果。

---

## 七、OpenClaw 3.8 更新说明与目录是否有变更

### 当前目录是否有变更：**无**

从 2026.3.1 到 2026.3.8，**运行态目录结构没有变化**：

- 状态目录仍是 **`~/.openclaw`**（或 `OPENCLAW_STATE_DIR`）。
- 顶层项不变：`openclaw.json`、`agents/`、`extensions/`、`identity/`、`devices/`、`logs/`、`memory/`、`cron/`、`subagents/`、`workspace-*` 等。
- 工作目录解析规则未改：仍由 `agents.defaults.workspace` / `agents.list[].workspace` 决定，默认仍为 `~/.openclaw/workspace-<id>`。

升级到 3.8 后无需迁移或重命名任何目录；现有 `~/.openclaw` 可直接继续用。

### 3.8 相对 3.1 的主要区别（与调试/目录相关）

以下多为行为与配置上的增强，不改变目录布局：

| 类别 | 说明 |
|------|------|
| **Doctor 状态目录检查** | macOS：若状态目录在 iCloud（`~/Library/Mobile Documents/...` 或 `~/Library/CloudStorage/...`）会警告，提示可能 I/O 变慢或锁/同步问题。Linux：若状态目录在 SD/eMMC（`mmcblk*`）上会警告，提示随机 I/O 与磨损。 |
| **文件工具与工作区** | 未设置时默认遵守文档：`tools.fs.workspaceOnly=false`，主机上的 `write`/`edit` 可访问工作区外路径（沙箱关闭时）。路径中的 `~/...` 会先按用户主目录展开，再做工作区根检查。 |
| **插件加载顺序** | 内置插件先于全局 `~/.openclaw/extensions` 加载；同 ID 时内置优先（`plugins.load.paths` 仍最高优先级）。 |
| **会话/诊断配置** | 新增可选配置：`diagnostics.stuckSessionWarnMs`（默认 120000）、`agents.defaults.compaction.memoryFlush.forceFlushTranscriptBytes`（默认 2MB）等，用于长会话与压缩行为。 |
| **安全与审计** | 工作区安全写入、沙箱媒体读取、子 Agent 沙箱继承等加固；`gateway.controlUi.allowedOrigins=["*"]` 会被安全审计标为高风险。 |
| **Cron / Gateway / CLI** | Cron 定时器热循环防护、失败告警、Control UI API 路由修正；CLI 启动与 `--version`/`--help` 快速路径等。 |

你当前 `openclaw.json` 里的 `meta.lastTouchedVersion` 若原是 `2026.3.2`，在 3.8 下再次写入配置后可能会变为 `2026.3.8`，仅表示“最后由该版本写入”，**不表示目录或必填字段有破坏性变更**。

---

## 八、小结

| 问题 | 答案 |
|------|------|
| OpenClaw 的目录是哪个？ | 运行态：**`~/.openclaw`**（可被 `OPENCLAW_STATE_DIR` 覆盖）。 |
| 目录结构？ | 见第二节树状图；配置在 `openclaw.json`，各 Agent 工作区在 `workspace-<id>/`。 |
| 工作目录是什么？ | 每个 Agent 的工作区根目录；主 Agent 当前为 **`~/.openclaw/workspace-main`**。 |
| 各文件作用？ | 见第四节表格。 |
| 基于它调试运行态？ | 看 `~/.openclaw/openclaw.json`、`logs/`、对应 `workspace-*/`；必要时用 `OPENCLAW_STATE_DIR` 做隔离调试。 |
| 源代码目录？ | 例如 **`/home/ubuntu/openclaw`**；只影响你改代码、构建和本地跑测试，对已安装的 openclaw 运行态无影响。 |
