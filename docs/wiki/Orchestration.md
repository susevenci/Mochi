# Orchestration · 编排层

编排层是"一条用户输入如何变成一条回复"的全部逻辑所在。对外只有一个入口：

```python
Orchestrator.handle_chat(turn_id: str, user_text: str, sink: EventSink) -> None
```

它不依赖 WebSocket —— `sink` 是 `EventSink` Protocol，生产环境注入 `WSSink`，单测注入记录型假实现。

## 入口与路由

```
handle_chat
  ├─ DecisionService.classify()      规则优先，< 1ms
  ├─ Route.COMMAND ──▶ CommandRouter.handle()  直接回复，不调 LLM
  ├─ Route.TASK    ──▶ 当前仅记日志，按 chat 处理（S6 改为 ack + 后台执行）
  └─ 其余          ──▶ RoleplayService.reply()
```

### 规则表（`orchestration/decision.py`）

| 优先级 | 规则 | 命中条件 | 结果 |
| --- | --- | --- | --- |
| 1 | `empty_input` | 空串/纯空白 | `CHAT` |
| 2 | `command_prefix` | 以 `/` 开头 | `COMMAND` |
| 3 | `task_pattern` | `^(帮我\|请\|给我).*(写\|生成\|搜索\|查\|计算\|记录\|提醒)` | `TASK` |
| 4 | `emotion_lexicon` | 命中 7 个情感词之一 | `EMOTIONAL` |
| 5 | 兜底 | 以上都不命中 | `CHAT`，`confidence=0.5` |

`DecisionService` 还有一道阈值：`confidence < 0.6` 时强制降级为 `CHAT`（`matched_rule="low_confidence"`）。LLM 兜底分类计划在 S6 接入，三段式结构不变。

情感词表是刻意做小的：`我好难过` / `我生气了` / `谢谢你` / `你最棒了` / `抱抱` / `晚安` / `滚`。它的用途不是"识别所有情绪"，而是给 S3 情感引擎提供高频刺激样本。

### 斜杠命令（`orchestration/commands.py`）

| 命令 | 行为 |
| --- | --- |
| `/help` | 列出可用命令 |
| `/new` | 清空短期记忆 |
| `/role list` | 列出角色卡，标注当前 |
| `/role set <id>` | 热切换角色卡，并清空上下文 |
| 其他 | 提示"不认识的命令" |

命令不走 LLM、不产生情绪刺激，这是 C 类行为的约定。

## 扮演层的一次完整回合

`RoleplayService.reply()` 的时序：

```
1. 取配置快照          provider / model / disable_thinking（每轮一次，热更新下轮生效）
2. ContextBuilder.build(history.recent(), user_text)
3. provider.stream(...)  ──▶ SSE 增量
4. MoodStreamParser.feed(chunk) ──▶ 正文增量 ──▶ sink.delta()
5. parser.finish()     ──▶ MoodResult(text, emotion, action, parsed)
6. 写短期记忆（仅未取消且正文非空）
7. map_emotion()       ──▶ sink.cue(performance.cue)
8. sink.final(chat.agent_final)
```

关键参数：`temperature=0.85`（来自 `LLM_TEMPERATURE_ROLEPLAY`）、`max_tokens=400`。首 token 延迟从**第一段正文**开始计，不是从请求发出计。

### 故障降级

`LLMError` 不向上抛：用角色卡的 `fallback` 文案兜底，`final.error` 带错误码。这样"模型挂了"表现为角色说一句人设化的台词，而不是窗口报错。

## 双通道解析

LLM 被要求先输出正文，再输出 `<<<MOOD>>>`，最后跟一个 JSON 块。解析器必须在**流式**条件下把两条通道分开，因此实现为四态状态机：

```
TEXT ──发现 <<<──▶ PENDING ──完整分隔符──▶ JSON ──解析成功──▶ DONE
  ▲                   │
  └──── 前缀失配 ──────┘   （整段回吐为正文）
```

四种真实故障，全部有单测覆盖：

| # | 故障 | 处理 |
| --- | --- | --- |
| 1 | 分隔符被 token 边界拆开（`<<<MO` + `OD>>>`） | PENDING 态攒前缀，凑齐再切换 |
| 2 | 正文出现 `<<<` 但不是分隔符 | 失配后整段回吐，绝不吞字 |
| 3 | JSON 被 `max_tokens` 截断 | `finish()` 丢弃该块，正文优先，`note="mood_json_unparsed"` |
| 4 | JSON 外套 ```json 围栏 | 解析前剥离围栏 |

`finish()` 的原则是**正文优先**：任何情况下都不能因为情绪 JSON 不完整而丢掉用户已经看到的文字。

## 取消传播

打断不走 `task.cancel()` —— 那会在任意 `await` 点抛异常，清理逻辑被跳过。实际链路：

```
前端 Esc ──▶ chat.interrupt(turn_id)
         ──▶ TurnRegistry.cancel(turn_id) 置位 asyncio.Event
         ──▶ 流式循环每轮检查 turn.is_cancelled，主动 break
         ──▶ final.error = "TURN_CANCELLED"，不写 history
```

对话生成跑在独立 `asyncio.Task` 里，WS 接收循环保持可用，否则生成期间收不到打断消息。

## 与 GateWay 的边界

| 关注点 | 归属 |
| --- | --- |
| 信封编解码、鉴权、心跳 | `gateway/` |
| 路由、上下文、生成、解析 | `orchestration/` |
| 情绪 → 表现映射 | `orchestration/performance.py` |
| 事件出口 | `EventSink` Protocol（由 gateway 实现） |

这条边界让 `tests/unit/test_roleplay.py` 可以在没有任何 WS 的情况下测完整回合。

## 相关页面

- [Architecture](Architecture.md) — 分层与不变量
- [Memory-and-Context](Memory-and-Context.md) — 上下文如何装配
- [Providers](Providers.md) — 流式从哪来
- [Protocol](Protocol.md) — 事件如何上线
