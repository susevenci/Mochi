# Protocol · 协议

前后端只有两种通道：**WS 传业务**、**REST 传配置与静态资源**。所有 WS 消息共用一个信封，所有契约由 Pydantic 生成。

## 连接

```
ws://127.0.0.1:8765/ws?token=<optional>
```

- 鉴权：query `?token=` 或请求头 `X-Mochi-Token`；服务端 `SERVER_TOKEN` 为空时不校验
- 未授权：握手阶段直接 `close(code=4401)`，不进入消息循环
- 心跳：客户端每 20s 发 `sys.ping`，服务端回 `sys.pong`
- 连接集合由 `ConnectionManager` 持有，支持 `broadcast()`（S3 主动推送情绪/搭话时复用）
- 对话生成跑在独立 Task，接收循环在生成期间仍可读——这是 `chat.interrupt` 能生效的前提

## 统一信封

所有消息（双向）都是同一个信封：

```json
{
  "v": 1,
  "type": "chat.user_input",
  "id": "01J8ZK3M4Q7X9Y2B5C6D7E8F9G",
  "ts": 1761000000.123,
  "turn_id": "01J8ZK3M4Q7X9Y2B5C6D7E8F9H",
  "payload": {}
}
```

| 字段 | 说明 |
| --- | --- |
| `v` | 协议版本，不匹配返回 `sys.error` + `PROTOCOL_MISMATCH` |
| `type` | `域.动作` 命名 |
| `id` | ULID（26 字符，单调递增，便于排查时序） |
| `ts` | Unix 时间戳（秒，浮点） |
| `turn_id` | 一轮对话的关联 ID；请求缺省时服务端生成 |
| `payload` | 类型相关的业务体 |

> 信封的 `v/id/ts` 用 `build_envelope()` 自动填充；这三个字段**不能**设默认值，否则 JSON Schema 会把它们标成可选，导致前端类型失真。`Envelope` 还设置了 `extra="forbid"`，多余字段会被拒。

## 消息类型

### 系统类

| type | 方向 | payload |
| --- | --- | --- |
| `sys.hello` | C→S | `{}` |
| `sys.hello_ack` | S→C | `{server_version, protocol, server_time, emotion?}` |
| `sys.ping` | C→S | `{ts}` |
| `sys.pong` | S→C | `{echo_ts, server_time}` |
| `sys.error` | S→C | `{code, detail, retryable}` |
| `sys.status` | S→C | 预留（S3 主动推送状态快照） |

`sys.hello_ack.emotion` 已预留，S3 起在握手时下发当前情绪快照。

### 对话类

| type | 方向 | payload |
| --- | --- | --- |
| `chat.user_input` | C→S | `{text, modality?, session_id?}`，`text` 长度 1–2000 |
| `chat.agent_delta` | S→C | `{delta, index, done}` — 逐字增量 |
| `chat.agent_final` | S→C | `{text, route, emotion?, action?, error?, first_token_ms?, latency_ms?}` |
| `chat.interrupt` | C→S | `{reason}` — 必须携带 `turn_id` |

`modality` 默认 `"text"`（S4 会用到 `"voice"`），`session_id` 默认 `"sess_default"`。

### 表现类

| type | 方向 | payload |
| --- | --- | --- |
| `performance.cue` | S→C | `{emotion_label, motion, expression?, priority}` |

`priority` 为 `normal` / `high`；`expression` 当前恒为 `null`——本批模型没有可用的 `.exp3` 情绪表情，表现全部由 motion 承担（见 [Live2D-Pipeline](Live2D-Pipeline.md)）。

## 一轮对话的消息序列

```
C→S  chat.user_input            turn_id=T
S→C  chat.agent_delta × N       （逐字）
S→C  performance.cue            （情绪 → 表现，先于定稿）
S→C  chat.agent_final           （text 定稿 + first_token_ms）
```

设计上没有单独的 `chat.agent_start`：第一个 `agent_delta` 就是开始信号。前端在发送时先放一个"…"占位气泡，避免"没反应"的错觉。

打断时：

```
C→S  chat.interrupt             turn_id=T
S→C  chat.agent_final           error="TURN_CANCELLED"
```

打断后不再推送任何 delta，也不写短期记忆。

## 错误处理

### `sys.error` 的错误码

| code | 含义 | 可重试 |
| --- | --- | --- |
| `BAD_JSON` | 不是合法 JSON | 否 |
| `BAD_ENVELOPE` | 信封字段缺失/类型错/payload 校验失败 | 否 |
| `PROTOCOL_MISMATCH` | `v` 不匹配 | 否 |
| `UNKNOWN_TYPE` | 未支持的消息类型 | 否 |
| `AUTH_FAILED` | 鉴权失败（REST 401 的 detail） | 否 |
| `INTERNAL` | 服务端内部错误 | 视情况 |

### `chat.agent_final.error` 的 LLM 错误码

这些错误**不中断连接**，而是走角色卡的 fallback 文案：

| code | 含义 |
| --- | --- |
| `TURN_CANCELLED` | 用户打断 |
| `LLM_TIMEOUT` | 上游超时 |
| `LLM_NETWORK` | 网络/连接失败 |
| `LLM_UPSTREAM` | 上游 5xx / 429 重试后仍失败 |
| `LLM_BAD_REQUEST` | 上游 4xx（非鉴权） |
| `LLM_AUTH_FAILED` | 上游 401/403 |
| `LLM_EMPTY_RESPONSE` | `choices` 为空 |
| `LLM_UNKNOWN` | 未归类的失败 |

REST 侧的上游错误以 `502 {code}: {detail}` 返回（`/api/v1/llm/models`）。

## REST 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | `{status, version, protocol, uptime_s, connections}`，**不需要 token** |
| GET | `/api/v1/sys/info` | 版本、协议、角色、数据目录、是否配置 LLM/token |
| GET | `/api/v1/config/user` | 窗口配置全量 |
| PATCH | `/api/v1/config/user` | 仅接受 `window` 键，其他键 400 |
| GET | `/api/v1/config/llm` | LLM 配置**视图**（`api_key_hint` 只回掩码） |
| PATCH | `/api/v1/config/llm` | 热更新 `base_url` / `api_key` / `model` / `disable_thinking` |
| GET | `/api/v1/llm/models` | 代理请求上游 `/models`，返回模型 ID 列表 |
| GET | `/api/v1/live2d/models` | 本地模型清单（含动作/表情数量） |
| GET | `/live2d/<dir>/<file>` | 模型静态资源（目录存在时挂载） |

所有 `/api/v1/*` 受 token 保护（`SERVER_TOKEN` 为空时放行）。`/health` 刻意不鉴权：Tauri 边车探活需要在拿到 token 之前就能用。

## 契约生成

```
server/app/gateway/protocol.py   ← 唯一真相源（Pydantic）
        │  scripts/export_schema.py
        ▼
shared/schema/protocol.schema.json
        │  scripts/gen-types.mjs
        ▼
frontend/src/types/protocol.ts   ← 生成物，禁止手改
```

改协议后两步都要跑，并把两份生成物一起提交。`Envelope`、`SysHelloAckPayload`、`SysPongPayload`、`SysErrorPayload`、`ChatUserInputPayload`、`ChatAgentDeltaPayload`、`ChatAgentFinalPayload`、`ChatInterruptPayload`、`PerformanceCuePayload` 与 `MessageType` 都会进入 schema。

## 兼容性约定

| 变更 | 做法 |
| --- | --- |
| 加可选字段 | 直接加，前端按需读取 |
| 加必填字段 | 提升 `PROTOCOL_VERSION`，并在前端处理 `PROTOCOL_MISMATCH` |
| 改字段语义 | 视为破坏性变更，提升版本号 |
| 加消息类型 | 后端 `MessageType` + `_dispatch` 分支 + 前端订阅 |

服务端与前端同仓库发布，实际只需要保证 `v` 一致；版本号更多是为将来第三方客户端留的余地。

## 相关页面

- [Architecture](Architecture.md) — 协议在整体中的位置
- [Orchestration](Orchestration.md) — 事件如何产生
- [Frontend](Frontend.md) — 前端如何消费
- [Testing](Testing.md) — 协议契约测试
