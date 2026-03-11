# OpenClaw main/sessions/sessions.json 详细分析

本文对 `~/.openclaw/agents/main/sessions/sessions.json` 做逐字段解析，便于理解 OpenClaw 的会话索引结构与运行时状态。

---

## 一、文件角色与整体结构

### 1.1 文件角色

- **不是**：对话内容存储（对话在 `<sessionId>.jsonl` 里）。
- **是**：**会话注册表 / 索引**：记录「当前有哪些逻辑会话」「每个会话对应哪个 transcript 文件」「该会话的元数据与运行时状态」。
- **读写时机**：创建/恢复/更新/删除会话时由 OpenClaw 进程读写；多会话时同一文件可能被并发更新（通常带锁或原子写）。

### 1.2 根结构

```json
{
  "<sessionKey>": { <SessionEntry> },
  ...
}
```

- **根键**：`sessionKey`，唯一标识一个「逻辑会话」。
- **根值**：一个 `SessionEntry` 对象，描述该会话的元数据、技能快照、系统提示报告、模型与 token 状态等。

### 1.3 Session Key 的语义

当前 main 的示例里只有一个键：

| Session Key       | 含义 |
|-------------------|------|
| `agent:main:main` | 主 Agent（main）的**主会话**：默认对话线程，无子会话标识。 |

更一般地，Session Key 的格式可以理解为：

- `agent:<agentId>:main` — 该 Agent 的主会话（用户直接对话）。
- `agent:<agentId>:subagent:<subagentInstanceId>` — 该 Agent 派生的子会话（例如 analyst-agent 被 main 派发时，在 analyst 的 sessions 里会有 `agent:analyst-agent:subagent:<uuid>`）。

因此：**一个 sessions.json 里可以有多个 sessionKey**（多会话/多线程），每个 key 对应一个 SessionEntry 和磁盘上的一个 `sessionId.jsonl`。

---

## 二、SessionEntry 顶层字段总览

下面按「会话标识 → 技能快照 → 通道与来源 → 文件与模型 → 系统提示报告 → 压缩与 token → 降级与杂项」顺序说明。你的文件里出现的字段都会覆盖到。

| 字段 | 类型 | 含义 |
|------|------|------|
| `sessionId` | string | 会话的 UUID，对应磁盘上的 `sessions/<sessionId>.jsonl`。 |
| `updatedAt` | number | 最后更新时间（Unix 毫秒时间戳）。 |
| `systemSent` | boolean | 是否已向模型发送过系统提示（bootstrap + 工作区文件 + 技能等）。 |
| `skillsSnapshot` | object | 会话创建时的技能列表与注入 prompt 的快照（见第三节）。 |
| `deliveryContext` | object | 当前投递上下文（如 channel）。 |
| `lastChannel` | string | 最后使用的通道（如 webchat）。 |
| `sessionFile` | string | 该会话 transcript 的绝对路径（与 sessionId 对应）。 |
| `modelProvider` / `model` | string | 当前使用的模型提供商与模型 ID。 |
| `abortedLastRun` | boolean | 上一轮是否被用户中止。 |
| `totalTokensFresh` | boolean | 下方 token 统计是否为最新。 |
| `cacheRead` / `cacheWrite` | number | 缓存读/写 token 数（若支持）。 |
| `chatType` | string | 对话类型，如 `direct`。 |
| `origin` | object | 会话来源（provider、surface、chatType）。 |
| `systemPromptReport` | object | 系统提示生成报告（见第五节）。 |
| `compactionCount` | number | 该会话经历过的压缩次数（如记忆压缩）。 |
| `contextTokens` | number | 模型上下文窗口大小。 |
| `inputTokens` / `outputTokens` / `totalTokens` | number | 当前会话的输入/输出/总 token 统计。 |
| `fallbackNotice*` | string | 若发生降级，记录选中的模型、当前模型及原因。 |

---

## 三、skillsSnapshot 详解

作用：**冻结会话创建时的技能环境**，便于恢复会话时知道「当时有哪些技能、描述和路径」，避免后续技能增删影响已有会话的语义。

### 3.1 结构概览

```json
"skillsSnapshot": {
  "prompt": "<整段注入到系统提示里的技能说明文本>",
  "skills": [ { "name", "requiredEnv"?, "primaryEnv"? }, ... ],
  "resolvedSkills": [ { "name", "description", "filePath", "baseDir", "source", "disableModelInvocation" }, ... ],
  "version": 0
}
```

- **prompt**：字符串，即发给模型的 `<available_skills>...</available_skills>` 整段，包含每个 skill 的 name、description、location。会话恢复时可按此还原「当时模型看到的技能列表」。
- **skills**：简表，仅 name 与 env 要求，用于快速判断需要哪些环境变量。
- **resolvedSkills**：解析后的完整列表，包含：
  - `filePath`：SKILL.md 的绝对路径。
  - `baseDir`：该 skill 的根目录（相对路径解析基准）。
  - `source`：`openclaw-bundled`（内置）或 `openclaw-workspace`（工作区技能，如 project-manager）。
- **version**：快照格式版本，当前为 0。

### 3.2 和你当前配置的对应关系

当前 main 的 skillsSnapshot 里包含 9 个技能：clawhub、coding-agent、gh-issues、github、healthcheck、skill-creator、tmux、weather、**project-manager**。其中 project-manager 的 `source` 为 `openclaw-workspace`，路径在 `~/.openclaw/workspace-main/skills/project-manager/`；其余为 `openclaw-bundled`，路径在 Node 的 openclaw 安装目录下。  
这表示：**该会话是在「main + 这 9 个技能」的环境下创建的**，后续若在 openclaw.json 或工作区里增删技能，不会改写这条已存在的快照。

---

## 四、deliveryContext、lastChannel、origin、chatType

- **deliveryContext**：当前投递上下文，例如 `{ "channel": "webchat" }`，表示消息来自 Web 聊天界面。
- **lastChannel**：最后一次活动的通道，与 deliveryContext.channel 通常一致。
- **origin**：会话的创建来源，例如：
  - `provider`: `"webchat"`
  - `surface`: `"webchat"`
  - `chatType`: `"direct"`
  表示这是一次从 Web 聊天发起的直接对话。
- **chatType**：与 origin.chatType 一致，如 `"direct"`（直接对话），以区分例如「线程内回复」等其它类型。

这些字段主要用于路由、审计和 UI 展示（例如在 Control UI 里按 channel 过滤会话）。

---

## 五、sessionFile、model、abortedLastRun、cache、token 与 fallback

- **sessionFile**：该会话 transcript 的绝对路径，例如：
  `/home/ubuntu/.openclaw/agents/main/sessions/cf0f6d43-5af4-4756-9b7c-7cb0d2fe3baf.jsonl`  
  与 `sessionId` 一一对应，打开该 jsonl 即可看到完整对话事件流。

- **modelProvider / model**：当前使用的模型，如 `zhipu` + `glm-4.5`（或文件中实际值）。若发生过降级，可能与 `systemPromptReport` 或 `fallbackNoticeActiveModel` 不一致。

- **abortedLastRun**：上一轮模型推理是否被用户点击「停止」等中止。用于 UI 或重试逻辑。

- **totalTokensFresh**：为 true 表示下面的 input/output/cache/total 是最近一次统计结果；为 false 时可能尚未刷新。

- **cacheRead / cacheWrite**：若网关或模型支持 prompt cache，这里记录本次会话的缓存读/写 token 数（如 6186 / 0）。

- **contextTokens**：模型上下文长度上限（如 128000）。

- **inputTokens / outputTokens / totalTokens**：当前会话累计输入/输出/总 token，用于用量统计与限制。

- **fallbackNoticeSelectedModel / fallbackNoticeActiveModel / fallbackNoticeReason**：若因限流等原因发生模型降级，这里会记录「实际选用的模型」「当前活动模型」和「原因」（如 `rate limit`）。你当前文件里示例为：选中 `zhipu/glm-4.7`，活动模型 `zhipu/glm-5`，原因为 `rate limit`，说明曾因限流从 glm-5 降到 glm-4.7。

---

## 六、systemPromptReport 详解（系统提示生成报告）

这是**诊断与学习**价值最大的一块：记录「本次会话在发送第一条用户消息前，系统提示是如何组装的」。

### 6.1 顶层字段

| 字段 | 含义 |
|------|------|
| `source` | 报告来源，如 `"run"` 表示来自运行时生成。 |
| `generatedAt` | 报告生成时间（毫秒时间戳）。 |
| `sessionId` / `sessionKey` | 对应会话。 |
| `provider` / `model` | 生成系统提示时使用的模型（可能与当前 model 不同，若发生过降级）。 |
| `workspaceDir` | 该 Agent 的工作区根目录。 |
| `bootstrapMaxChars` / `bootstrapTotalMaxChars` | Bootstrap 单文件/总字符限制（用于截断）。 |
| `sandbox` | 沙箱模式与是否启用。 |
| `systemPrompt` | 系统提示体积统计。 |
| `injectedWorkspaceFiles` | 从工作区注入的文档列表。 |
| `skills` | 技能块统计。 |
| `tools` | 工具列表与 schema 体积。 |

### 6.2 systemPrompt 体积

```json
"systemPrompt": {
  "chars": 33471,
  "projectContextChars": 19675,
  "nonProjectContextChars": 13796
}
```

- **chars**：系统提示总字符数。
- **projectContextChars**：来自项目/工作区的部分（如 AGENTS.md、MEMORY.md 等）。
- **nonProjectContextChars**：非项目部分（模型指令、技能 prompt、工具 schema 等）。

便于分析「上下文是否过大、主要来自工作区还是全局配置」。

### 6.3 injectedWorkspaceFiles（工作区注入文件）

列表中的每一项对应一个被注入系统提示的工作区文件：

| 字段 | 含义 |
|------|------|
| `name` | 文件名（如 AGENTS.md）。 |
| `path` | 绝对路径。 |
| `missing` | 是否缺失（若为 true 则可能占位或跳过）。 |
| `rawChars` | 文件原始字符数。 |
| `injectedChars` | 实际注入的字符数（可能被截断）。 |
| `truncated` | 是否被截断。 |

你当前会话里包含：AGENTS.md、SOUL.md、TOOLS.md、IDENTITY.md、USER.md、HEARTBEAT.md、BOOTSTRAP.md、MEMORY.md 等，均未截断。  
这说明：**main 的默认行为是把工作区根目录下这些「人格/工具/记忆」文档整份注入系统提示**，会话恢复时也会按同一逻辑使用这些文件。

### 6.4 skills 块统计

```json
"skills": {
  "promptChars": 4593,
  "entries": [ { "name": "clawhub", "blockChars": 448 }, ... ]
}
```

- **promptChars**：技能整体在系统提示里占的字符数。
- **entries**：每个技能的 name 与 blockChars（该技能在 prompt 中的字符数）。  
用于评估「哪个技能占用最多上下文」。

### 6.5 tools 列表

```json
"tools": {
  "listChars": 1419,
  "schemaChars": 16117,
  "entries": [ { "name", "summaryChars", "schemaChars", "propertiesCount" }, ... ]
}
```

- **listChars**：工具列表描述总长。
- **schemaChars**：所有工具 schema 总长。
- **entries**：每个工具的名称、摘要长度、schema 长度、参数个数。  

你当前会话中有 read、edit、write、exec、process、browser、canvas、nodes、message、tts、agents_list、sessions_*、subagents、session_status、web_search、web_fetch 等。  
这对理解「系统提示里工具占多少 token」以及「为何要压缩或裁剪工具」很有用。

---

## 七、compactionCount、contextTokens、totalTokens

- **compactionCount**：该会话发生过的压缩次数（如记忆/历史压缩）。当前示例为 0，表示尚未压缩。
- **contextTokens**：模型上下文长度（如 128000）。
- **inputTokens / outputTokens / totalTokens**：当前会话的累计用量；与 `totalTokensFresh` 配合使用。

---

## 八、与 transcript（.jsonl）的对应关系

- **sessions.json**：用 `sessionKey` → `sessionId`（以及 `sessionFile`）建立「逻辑会话 → 磁盘文件」的映射；并保存该会话的**元数据与运行时状态**（技能快照、系统提示报告、模型、token、fallback 等）。
- **`<sessionId>.jsonl`**：该会话的**事件流**，每行一条 JSON，类型包括：
  - `session`：会话开始（id、version、timestamp、cwd）。
  - `model_change`：切换模型。
  - `thinking_level_change`：思考级别。
  - `message`：user/assistant/toolResult 等消息；assistant 消息里可含 thinking、text、toolCall。
  - 其他 custom 事件等。

因此：**要完整理解一次会话**，需要同时看 sessions.json 里的该 sessionKey 条目（了解环境与状态）和对应 sessionId 的 .jsonl（了解对话与事件序列）。

---

## 九、小结：学习时可关注的要点

1. **Session Key 的语义**：`agent:<agentId>:main` vs `agent:<agentId>:subagent:<id>`，理解「主会话」与「子会话」在索引中的区分。
2. **skillsSnapshot**：会话创建时技能环境的冻结表示；`resolvedSkills` 中的 `source`（bundled vs workspace）和路径对调试技能加载很重要。
3. **systemPromptReport**：系统提示是如何组装的（工作区文件、技能、工具各占多少）、是否有截断、沙箱与 bootstrap 限制，是优化上下文和排查「模型看不到某文件」的关键。
4. **sessionFile 与 sessionId**：始终一一对应，sessions.json 负责「指向」正确的 transcript 文件。
5. **model / fallback / token**：当前模型、是否发生过降级、token 与缓存用量，便于做成本与稳定性分析。

把上述几点和实际文件里的值对照一遍，就能对 main 下 session 的索引与运行时状态有比较深刻的理解。若你后续想看 analyst-agent 或子会话的 sessions.json，结构相同，只是 sessionKey 会出现 `subagent` 形式以及可能的 `spawnedBy` 等字段。
