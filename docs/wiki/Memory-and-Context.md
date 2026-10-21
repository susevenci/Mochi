# Memory & Context · 记忆与上下文

这一层回答两个问题：**记得多少**（短期窗口）与**怎么喂给模型**（上下文装配）。

## 记忆分层

| 层 | 实现 | 范围 | 状态 |
| --- | --- | --- | --- |
| L1 短期窗口 | `memory/short_term.py` | 最近 20 轮对话，进程内存 | ✅ S1 |
| L1+ 摘要压缩 | 同上接口扩展 | 超窗后摘要 | ⏳ S6 |
| L2 长期记忆 | SQLite（`data/mochi.db`） | 跨会话事实 | ⏳ S6 |

`ShortTermMemory` 只有四个操作：`append(user, assistant)`、`recent()`、`clear()`、`__len__`。超过 `max_turns` 时从头部丢弃——**按整轮丢弃**，不会留下孤立的半轮消息。

切换角色卡与 `/new` 都会 `clear()`，这是有意的：人设变了还带着旧上下文，会让模型精神分裂。

## 上下文装配

`ContextBuilder.build(recent, user_input, layer="roleplay")` 输出 `list[ChatMessage]`：

```
[system]  人格内核 + 表达约束 + （可选情绪块） + 输出格式
[user]    ← 最近第 N 轮
[assistant]
…
[user]    本轮输入
```

### 预算

S1 用字符数近似 token，S6 换 `tiktoken` 精确计数：

| 预算 | 常量 | 值 |
| --- | --- | --- |
| system prompt | `PERSONA_CHARS + OUTPUT_FORMAT_CHARS` | 900 + 400 |
| 对话历史 | `DIALOG_CHARS` | 2400 |

历史按"从最近往前"装入，**整轮判断**：若某轮会超预算且已有选中轮次，直接停止；单人长消息不会把历史切成半问半答。

### system prompt 结构

```
【人格内核】
你是<full_name>，<role>。
性格：<personality>
说话风格：<tone>；句子长度：<sentence_length>
常用口头禅：<catchphrases>
绝不出现的词句：<forbidden>

【表达约束】
- 永远以角色身份说话，不自称 AI 或语言模型
- 回复控制在 60 字以内，不要长篇说教
- 不用 emoji，可用少量颜文字

<可选：当前情绪块>

【输出格式】
先输出回复正文，然后换行输出 <<<MOOD>>> 再输出一个 JSON：
{"emotion":{...},"action":{...}}
label 只能从这个列表选：neutral,happy,…,surprised
```

情绪块由参数 `emotion_block` 预留，当前 `RoleplayService` 尚未传入。S3 计划注入**自然语言描述**（"你现在有点不安"），而不是 PAD 数值——数值对模型的语气没有帮助。

## I2：扮演层零工具

`build(layer="roleplay")` 是唯一实现的层，且**硬性不含任何工具 schema**。这不是靠自觉，而是两条约束：

1. `layer != "roleplay"` 直接 `NotImplementedError`，防止有人偷偷加参数。
2. `tests/unit/test_context_builder.py::test_roleplay_has_zero_tool_schema` 把整段 prompt 转小写后断言不含 `tools` / `工具` / `function`。

Agent Core 的上下文（S6）会走不同的 `layer` 与预算，但共享同一个 builder——这就是"三套上下文策略，一个装配器"的含义。

## 上下文里不放什么

| 不放 | 原因 |
| --- | --- |
| 工具 schema | 人设稀释（I2） |
| PAD 原始数值 | 模型无法稳定利用，反而泄漏实现细节 |
| 系统时间/环境变量 | 桌宠不需要扮演运维 |
| 完整历史 | 首字延迟与成本随长度线性上升 |

## 观测

`RoleplayService` 每轮记录：

```
roleplay start turn=… messages=… prompt_chars=… model=… thinking=…
roleplay done  turn=… first_token_ms=… latency_ms=… chars=… parsed=…
```

`prompt_chars` 是最实用的调参信号：它突然变大，通常意味着历史截断逻辑或角色卡被改坏了。

## 后续演进

- S3：`emotion_block` 接引擎快照；system prompt 增加"当前心情"段。
- S6：`ShortTermMemory` 换成 SQLite + 摘要压缩，接口保持不变；`ContextBuilder` 增加 `layer="agent"`。
- 长期记忆检索结果以"相关回忆"块注入 roleplay 上下文，仍不含工具 schema。

## 相关页面

- [Orchestration](Orchestration.md) — 谁在调用 build
- [Configuration](Configuration.md) — 数据目录与角色卡
- [Emotion-Engine](Emotion-Engine.md) — 情绪块的内容来源
