# Mochi 架构说明

## 1. 三条主线

```
Tauri 壳 ── 透明置顶窗 / 托盘 / 全局快捷键 / 边车托管
前端 WebView ── Live2D、字幕、语音、调试面板（只表现）
Python 后端 ── Decision / Roleplay / Agent Core / Emotion / Memory / Voice
```

- **单一入口**：所有输入都经过 `Orchestrator.handle_chat()`。
- **单一情绪权威**：`EmotionEngine` 是唯一状态源，前端只消费快照与 cue。
- **单一契约源**：Pydantic → JSON Schema → TS 类型（`scripts/export_schema.py` / `scripts/gen-types.mjs`）。

## 2. 三层上下文策略

| 层 | 上下文 | 工具 schema | 目标 |
| --- | --- | --- | --- |
| Decision | 最近 3 轮摘要 | 0 | 规则 <1ms，LLM 兜底 <800ms |
| Roleplay | 人格 + 情绪 + 记忆 + 摘要 + 最近轮次 | **0（硬约束）** | 首字 <2.5s、人设稳定 |
| Agent Core | 任务指令 + 工具 schema + 任务消息 | 全量 | 工具循环、错误回灌 |

## 3. 一次对话的数据流

```
WS chat.user_input
  → Decision（command / chat / emotional / task）
  → EmotionEngine.apply_text（PAD 刺激）
  → Roleplay：
       ContextBuilder(roleplay)
       ├─ 人格内核
       ├─ 【内心状态】+ 表达约束（冻结快照）
       ├─ 【长期记忆】画像 / 摘要 / 召回
       └─ 最近 20 轮
       → LLM 流式正文
       → 句子切分 → edge-tts 流式合成（下一句预取）
       → performance.cue + audio.out_* + chat.agent_final
  → 写回 messages / 抽取长期记忆 / 滚动摘要
```

Task 路由：`ack` 立即返回 → 后台 Agent Core 工具循环 → `proactive.speak` 汇报。

## 4. 进程与端口

- 后端只绑 `127.0.0.1`；Tauri 启动时选空闲端口 + 随机 token。
- 边车以 `mochi-server.exe`（PyInstaller resource）运行；崩溃 5s 内重启，退出先 `POST /shutdown`。
- 前端所有 REST 走 `config.apiBase`，WS 走 `ws://127.0.0.1:<port>/ws?token=...`。

## 5. 目录

```
mochi/
  server/app/
    gateway/         WS 信封、鉴权、心跳、音频/确认消息
    orchestration/   Decision / Roleplay / Agent / Turn / Naturalness
    emotion/         PAD、标签、状态机、人格、主动性、调试 REPL
    memory/          会话、摘要、抽取、tiktoken、ContextBuilder
    tools/           注册表、12+ 内置工具、Agent Core
    skills/          SKILL.md 注册表与三工具
    store/           SQLite schema / 单写者队列 / 情绪 JSON Repo
    voice/           ASR / VAD / edge-tts / 句子管线
    scheduler/       提醒调度
  frontend/src/      Live2D、音频、ShellAdapter、Preact UI
  desktop/src-tauri/ Rust 壳、边车、托盘、快捷键、热区
  skills/            三个技能包
```

## 6. 质量门禁

`scripts/gate.ps1`：ruff + mypy + pytest/coverage + schema/gen-types 漂移 + 前端 build/test。
CI 在每次 push 运行同一套检查（`.github/workflows/quality.yml`）。
