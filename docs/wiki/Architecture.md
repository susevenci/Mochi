# Architecture

## 总览

```
客户端（浏览器 / Tauri WebView）
   │  WebSocket（统一信封）
   ▼
网关层 gateway/       鉴权 · 心跳 · 消息分发 · 对话 Task 隔离
   │
   ▼
编排层 orchestration/
   ├─ Decision     规则优先，< 1ms 路由（command / chat / task / emotional）
   ├─ Roleplay     纯净上下文 + 流式生成 + 双通道解析
   └─ Agent Core   工具循环（S6）
   │
   ▼
能力层
   ├─ EmotionEngine（S3，PAD 状态机，横切）
   ├─ Memory（上下文预算 / 短期窗口 / 长期记忆）
   ├─ Providers（OpenAI 兼容，多模型分工）
   └─ Performance（情绪 → 表现指令）
```

## 六条不变量

编号在代码注释与测试中直接引用（I1–I6）。违反任何一条都应返工，而不是"先这样"。

| 编号 | 不变量 | 落地方式 |
| --- | --- | --- |
| I1 | 情绪只有后端一个权威源 | 前端只消费 `performance.cue`，不做情绪计算 |
| I2 | 扮演层 prompt 中**不得出现任何工具 schema** | `ContextBuilder.build(layer="roleplay")` 单测断言无 `tools` / `工具` / `function` |
| I3 | 快照驱动表现 | 前端不自行推断状态，按后端快照渲染 |
| I4 | 契约单一真相源 | Pydantic → JSON Schema → TS 类型，生成物禁止手改 |
| I5 | Provider 抽象 | 业务层禁止直连 SDK，`ruff` 用 `banned-api` 拦截 `openai` 导入 |
| I6 | 单 worker | WS 连接集合即状态，避免多进程状态分裂 |

## 三层为什么必须分离

| 层 | 上下文 | 工具 schema | 目标 |
| --- | --- | --- | --- |
| Decision | 3 轮摘要 | 0 | < 1ms 路由 |
| Roleplay | 人格 + 情绪 + 记忆 | **0（硬约束）** | 首字 < 2.5s、人设稳定 |
| Agent Core | 任务 + 全量工具 | 全量 | 后台执行、错误回灌自愈 |

本质不是"三次 LLM 调用"，而是**三套上下文策略**——所以代码里只有一个 `ContextBuilder(layer=...)`，而不是三个 prompt 拼接函数。

### 当前实现状态

| 层 / 能力 | 状态 |
| --- | --- |
| Decision（规则引擎） | ✅ S1；LLM 兜底分类 ⏳ S6 |
| Roleplay（纯净上下文 + 流式） | ✅ S1 |
| Agent Core（工具循环） | ⏳ S6；`TASK` 路由当前按 chat 处理 |
| EmotionEngine（PAD） | ⏳ S3；当前情绪来自 LLM 建议 |
| Memory（短期窗口） | ✅ S1；长期记忆 ⏳ S6 |
| Voice（ASR / TTS / 口型） | ⏳ S4 |

这张表是阅读代码时的"防迷路"标记：看到 `S3` / `S6` 的注释，说明那块是**预留接口而非失效代码**。

## 模块边界

```
main.py        装配与 HTTP/WS 入口，不含业务规则
bootstrap.py   唯一装配点（构造器注入，无全局单例）
gateway/       线上协议与连接，不关心回复内容
orchestration/ 业务规则与 LLM 调用，不认识 WebSocket
memory/        上下文装配，不发起 IO
providers/     模型服务，不含角色/情绪知识
config/        配置解析，不依赖上层
```

依赖方向只能自上而下。`orchestration` 通过 `EventSink` Protocol 向 `gateway` 发事件，而不是反向导入——这条边界让编排层可以在无 WS 的单测里完整运行。

## 一轮对话的数据流

```
用户输入
  │
  ├─▶ Decision.classify()           路由（规则优先，未命中 → chat）
  │
  ├─▶ CommandRouter.handle()        斜杠命令：直接回复，不调 LLM
  │
  └─▶ RoleplayService.reply()
        ├─ ContextBuilder.build()   人格 + 最近 N 轮 + 输出格式
        ├─ Provider.stream()        SSE 逐段产出正文
        ├─ MoodStreamParser.feed()  双通道拆分：正文 / <<<MOOD>>> JSON
        │     ├─ 正文增量 → chat.agent_delta（前端逐字渲染）
        │     └─ JSON 尾块 → 解析 emotion / action
        ├─ PerformanceMapper        情绪标签 → motion / expression
        │     └─ performance.cue
        └─ chat.agent_final         定稿（文本 + 情绪 + 首字延迟）
```

**双通道解析**是这一层最脆弱的部分，四种真实故障都有单测覆盖：

1. 分隔符被 token 边界拆开（`<<<MO` + `OD>>>`）
2. 正文出现 `<<<` 但不是分隔符 → 必须原样回吐，不能吞字
3. JSON 被 `max_tokens` 截断 → 丢弃该块，正文优先
4. JSON 外套了 ```json 围栏

## 取消传播

生成过程中的打断不走 `task.cancel()`（会在任意 `await` 点抛出，清理逻辑被跳过），而是：

1. 前端发 `chat.interrupt`
2. `TurnRegistry` 把 `Turn.cancelled` 事件置位
3. 流式循环每轮检查 `turn.is_cancelled`，主动 break
4. 取消后不写 history，`final.error = TURN_CANCELLED`

## 配置分层

| 层级 | 位置 | 热更新 |
| --- | --- | --- |
| 环境配置 | `.env` → Pydantic `Settings` | 重启生效 |
| 用户配置 | `<data_dir>/settings.json`（窗口 / LLM） | `PATCH /api/v1/config/llm` 即时生效 |
| 前端选择 | `localStorage`（当前模型） | 即时生效 |

优先级：用户配置 > 环境配置 > 代码默认。

## 关键权衡

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| 桌面壳 | Tauri 2（Plan B: Electron） | 体积小、原生透明窗；本机用 GNU 工具链编译（见 [Getting-Started](Getting-Started.md)） |
| 状态管理 | 后端权威 + 前端只读 | 避免两端状态漂移 |
| UI 框架 | 原生 DOM + Preact（仅面板） | Live2D 层零框架依赖，避免与 canvas 争抢渲染 |
| 测试策略 | 纯函数单测 + 真实链路冒烟 | 解析器/映射逻辑适合单测；LLM 链路用脚本冒烟 |
| 传输 | 单一 WS 连接 + 统一信封 | 双向流、可打断；REST 只承担配置与静态资源 |
| 生成方式 | 对话跑独立 Task | 接收循环保持可读，才能收到 `chat.interrupt` |

## 相关页面

- [Orchestration](Orchestration.md) — 三层编排的实现细节
- [Providers](Providers.md) — LLM 接入与降级
- [Memory-and-Context](Memory-and-Context.md) — 上下文策略
- [Protocol](Protocol.md) — 线上契约
- [Code-Tour](Code-Tour.md) — 文件级地图

