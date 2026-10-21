# Testing · 测试与质量门禁

测试策略是"**纯函数单测 + 真实链路冒烟**"：能在无 IO 条件下验证的逻辑全部单测；依赖真实 LLM 的链路用脚本冒烟，而不是 mock 到底。

## 工具链

```powershell
cd mochi
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check server scripts --config pyproject.toml
.venv\Scripts\python.exe -m mypy server\app scripts --config-file pyproject.toml
```

| 工具 | 配置 | 作用 |
| --- | --- | --- |
| pytest | `testpaths=["server/tests"]`、`pythonpath=["server"]` | 单测 |
| ruff | `line-length=100`、`E,F,I,UP,B,SIM,TID` | 风格 + 不变量 I5（banned-api `openai`） |
| mypy | `disallow_untyped_defs`、`warn_unused_ignores` | 类型 |

门禁标准是三条全绿。`mypy` 覆盖 `server/app` 与 `scripts`（43 个文件）。

## 64 项测试分布

| 文件 | 数量 | 覆盖内容 |
| --- | --- | --- |
| `test_ws_protocol.py` | 9 | 握手、心跳回显、未知类型、坏 JSON、版本不匹配、缺 `type`/`id`、`interaction.event` 接收与坏 payload |
| `test_auth.py` | 3 | WS 拒绝/接受 token、REST 401 与 `X-Mochi-Token` |
| `test_health.py` | 2 | `/health` 字段、`/api/v1/sys/info` |
| `test_user_settings.py` | 5 | 默认值、深合并、原子写、损坏回退、REST 路由 |
| `unit/test_llm_settings.py` | 11 | 优先级、掩码、热更新、`/models`、PATCH 校验 |
| `unit/test_mood_parser.py` | 7 | 四类流式故障 + 单块 + 围栏 + 尾部 `<` |
| `unit/test_decision.py` | 5 | 命令/任务/情感/普通/兜底与延迟 |
| `unit/test_performance.py` | 4 | 标签映射、high 优先级、未知标签、None |
| `unit/test_live2d_binding.py` | 6 | 衣柜扫描能力清单、绑定 ok、声明缺失回退、缺动作组、未知表情、未声明回退首个 |
| `unit/test_context_builder.py` | 3 | I2 零工具、prompt 结构、整轮截断 |
| `unit/test_orchestrator.py` | 3 | 命令不触达 roleplay、chat 委派、未知 turn 打断 |
| `unit/test_roleplay.py` | 3 | 流式 + 情绪 + cue、取消不写记忆、LLM 错误降级 |
| `unit/test_provider.py` | 3 | 两种思考开关方言、关闭时不注入 |

### 最值得保留的三类测试

1. **不变量测试**：`test_roleplay_has_zero_tool_schema`（I2）、`test_missing_id_is_bad_envelope`（契约必填）。它们保护的是设计，不是实现细节。
2. **状态机测试**：`test_mood_parser.py` 的每个用例都对应一个线上真实故障，回归价值最高。
3. **取消语义测试**：`test_cancelled_turn_does_not_write_history` —— 取消后污染记忆是很难在界面上发现的事故。

## fixture

`server/tests/conftest.py` 提供两个 fixture：

| fixture | 作用 |
| --- | --- |
| `settings(tmp_path)` | 临时 `data_dir`、关闭 token、空 LLM key —— 不污染 `%APPDATA%` |
| `client(settings)` | `TestClient(create_app(settings))`，带 `with` 触发 startup/shutdown |

需要鉴权的用例自己在文件内建 `secured_client`（`server_token="s3cret"`），不改变全局 fixture。

## S2 运行时自检（可复跑验收）

单测盖不到渲染层，所以 S2 的验收口径做成前端“一键自检”：调试面板（右上角锤子）→“运行 S2 自检”，约 12s。

| 检查项 | 判定 |
| --- | --- |
| 模型已加载 | `live2d.caps` 非空，打印模型名与参数数 |
| 动作能力 | `motionGroups.length > 0` |
| 待机（呼吸/微摆） | 1.5s 内 `ParamBreath` 或 `ParamBodyAngleX` 变化 > 0.01 |
| 眨眼 | 6s 内 `ParamEyeLOpen` 最小值 < 0.5 |
| 口型振幅法 | 播放合成测试音后 `level max > 0.15` 且 `max-min > 0.1` |
| 动作冷却去重 | 清冷却后连发两次 `request()`：`first=true`、`second=false` |

某次实测（qiye_10）：`Δbreath=0.724 Δbody=1.119`、`minEyeOpen=0.00`、`level max=0.79`、`first=true second=false`。

## 桌面壳窗口取证

`scripts/check_window.ps1` 启动壳后枚举该进程的顶层窗口（`class=Tauri Window`，420×560，`topmost=True`），
并用屏幕像素比对确认透明——窗口左上角内侧与桌面背景同色（`diff=0`）。
这类“窗口样式”只能靠系统 API 取证，单测与浏览器都替代不了。

## 写新测试的约定

- **只测行为，不测实现**：Provider 请求体这类白盒测试有明确目的时，加 `# noqa: SLF001` 并在 docstring 说明。
- **异步用例用 `asyncio.run()`**：项目未引入 `pytest-asyncio`，保持依赖最小。
- **假实现放在用例文件里**：`FakeProvider` / `RecordingSink` 各自定义，避免共享 mock 状态。
- **新增不变量时必须配测试**：I2 已有先例；S3 的"情绪单一权威源"也应有一条端到端断言。
- **禁止在单测里打真实网络**：需要真实 LLM 的场景走冒烟脚本。

## 冒烟脚本矩阵

| 脚本 | 依赖 | 验证 |
| --- | --- | --- |
| `doctor.py` | 无 | Python / Node / pnpm / npm / cargo / Rust GNU 工具链 / Tauri CLI / WebView2 |
| `smoke_ws.py` | 后端 | hello/ack、ping/pong 回显 |
| `smoke_chat.py` | 后端 + LLM | 真实对话、流式拼接、`first_token_ms`、多轮记忆 |
| `probe_llm.py` | LLM | 非流式、流式、首 token 延迟、reasoning 块数量 |

`smoke_chat.py` 内置场景：

| 场景 | 输入 |
| --- | --- |
| `hello` | `你好呀` |
| `memory` | `我叫阿哲` → `我叫什么名字` |
| `role` | `/role set genki` → `你好呀` |
| `help` | `/help` |

它按 `turn_id` 过滤消息，因此可以在同一连接上连续跑多轮。

## 契约同步

改了 `gateway/protocol.py` 之后：

```powershell
.venv\Scripts\python.exe scripts\export_schema.py   # Pydantic → JSON Schema
node scripts\gen-types.mjs                          # JSON Schema → TS
```

两份生成物都要提交。检查是否忘记生成：

```powershell
git diff --exit-code shared/schema/protocol.schema.json frontend/src/types/protocol.ts
```

这条命令适合将来放进 CI；当前仓库没有 CI（见 [Roadmap](Roadmap.md) 技术债）。

## 当前结果

| 项 | 结果 |
| --- | --- |
| `pytest` | 64 passed |
| `ruff` | All checks passed |
| `mypy` | Success: no issues found in 43 source files |
| `tsc --noEmit` | 通过 |
| `vite build` | 通过（仅 chunk > 500KB 提醒） |
| S2 自检 | 6/6 通过 |

## 相关页面

- [Getting-Started](Getting-Started.md) — 首次跑通
- [Protocol](Protocol.md) — 契约生成链路
- [Roadmap](Roadmap.md) — 未完成项与技术债
