# Code Tour · 代码地图

这页回答"我想改 X，该看哪个文件"。按依赖方向从外到内排列。

## 建议阅读顺序

```
main.py → bootstrap.py → context.py
      → gateway/ws.py → orchestration/orchestrator.py
      → orchestration/roleplay.py → memory/context_builder.py
      → providers/openai_compatible.py
```

先看装配（谁持有谁），再看一条消息如何穿过各层，最后看 Provider 的流式细节。这样不会一上来就陷进状态机。

## 后端 `mochi/server/app/`

### 顶层

| 文件 | 职责 | 什么时候改它 |
| --- | --- | --- |
| `main.py` | FastAPI 装配、健康检查、全部 REST、Live2D 静态挂载 | 加端点、改启动行为 |
| `bootstrap.py` | 依赖装配：配置 → 角色卡 → 记忆 → Provider → 编排 | 新增服务、调整装配顺序 |
| `context.py` | `AppContext` 数据类，持有所有单例 | 新增跨层共享的服务 |
| `__init__.py` | `__version__` | 发版 |

### `gateway/` 接入层

| 文件 | 职责 |
| --- | --- |
| `protocol.py` | **契约唯一真相源**：`MessageType`、`Envelope`、各 Payload、`build_envelope()` |
| `ws.py` | 连接集合、`WSSink`（编排事件 → 信封）、消息分发、`/ws` 路由 |
| `auth.py` | `hmac.compare_digest` 校验 token；空 token 直接放行 |
| `errors.py` | `ErrorCode` 与 `error_envelope()` |

改消息格式先改 `protocol.py`，然后跑契约生成（见 [Testing](Testing.md)）。

### `orchestration/` 编排层

| 文件 | 职责 |
| --- | --- |
| `orchestrator.py` | 唯一入口：分类 → 命令/对话；持有 `TurnRegistry` |
| `decision.py` | 规则引擎（命令/任务/情感/兜底） |
| `commands.py` | `/help` `/new` `/role` |
| `roleplay.py` | 纯净上下文 + 流式 + 解析 + 记忆写入 + cue |
| `mood_parser.py` | 四态双通道解析状态机 |
| `performance.py` | 情绪标签 → motion/priority 映射表 |
| `events.py` | `EventSink` Protocol 与 `FinalPayload` / `CuePayload` |
| `turn_registry.py` | Turn 生命周期与取消事件 |

`performance.py` 的 `EMOTION_TO_MOTION` 是**换模型时唯一要改的表**（如果新模型的动作用另一套命名）。

### `providers/` LLM 接入

| 文件 | 职责 |
| --- | --- |
| `base.py` | `LLMProvider` Protocol、`ChatMessage`、`Usage`、`ChatResult`、`LLMError` |
| `openai_compatible.py` | httpx 实现：SSE、重试、思考开关、错误映射 |
| `factory.py` | 历史遗留，已被 `LLMSettingsService` 取代（技术债） |
| `usage.py` | 按用途累加 token |

### `memory/` 记忆

| 文件 | 职责 |
| --- | --- |
| `short_term.py` | 20 轮滑动窗口 |
| `context_builder.py` | system prompt + 整轮截断 + I2 约束 |

### `config/` 配置

| 文件 | 职责 |
| --- | --- |
| `settings.py` | `.env` → `Settings`，目录创建 |
| `user_settings.py` | `settings.json` 读写、深合并、原子替换 |
| `llm_settings.py` | LLM 配置解析、热更新、`/models`、密钥掩码 |
| `character_card.py` | YAML 角色卡模型与加载器 |

### `utils/`

| 文件 | 职责 |
| --- | --- |
| `ids.py` | 26 字符 ULID（48-bit 时间 + 80-bit 随机） |

## 测试 `mochi/server/tests/`

| 文件 | 保护什么 |
| --- | --- |
| `conftest.py` | 隔离的 `Settings` 与 `TestClient` |
| `test_ws_protocol.py` | 信封与握手契约 |
| `test_auth.py` | token 边界 |
| `test_health.py` | 探活与运行信息 |
| `test_user_settings.py` | 配置文件读写与 REST |
| `unit/test_*` | 编排、解析、映射、上下文、Provider、配置 |

改动 `orchestration/` 或 `memory/` 时，对应 `unit/test_*` 是最快的回归网。

## 脚本 `mochi/scripts/`

| 文件 | 用途 |
| --- | --- |
| `doctor.py` | 环境体检，缺项给安装命令 |
| `dev.ps1` | 一键起后端 + 前端（支持 `-BackendOnly` / `-FrontendOnly`） |
| `smoke_ws.py` | WS 握手/心跳冒烟 |
| `smoke_chat.py` | 真实 LLM 对话冒烟（含场景） |
| `probe_llm.py` | 模型连通性、流式、首 token 延迟 |
| `export_schema.py` | Pydantic → JSON Schema |
| `gen-types.mjs` | JSON Schema → TS |
| `fetch_live2d.py` | 从模型合集稀疏克隆单个模型 |
| `live2d_pick.py` | 列合集、浏览目录、看模型能力、下载预览图 |
| `make_thumb.py` | 生成缩略图 |
| `make_fallback_portrait.py` | 生成兜底静态立绘 PNG（纯标准库，无 Pillow） |
| `setup_binutils.ps1` | 下载 w64devkit（含 dlltool/windres）供 Tauri 构建 |
| `tauri.ps1` | 注入 binutils 后调 `tauri dev/build` |
| `check_window.ps1` | 启动壳并枚举窗口样式/像素，做透明与置顶取证 |

## 前端 `mochi/frontend/src/`

见 [Frontend](Frontend.md) 的模块地图。入口是 `main.ts`，改动最频繁的三个文件是 `main.ts`、`SettingsPanel.tsx`、`Live2DStage.ts`。

## 桌面壳 `mochi/desktop/src-tauri/`

| 文件 | 现状 |
| --- | --- |
| `tauri.conf.json` | 420×560、无边框、透明、置顶、隐藏任务栏、CSP 白名单、`visible:false` 防白闪 |
| `src/main.rs` | 注册 10 个窗口命令 + 启动时将窗口置顶 |
| `src/window.rs` | `set_always_on_top` / `set_click_through` / `start_dragging` / `set_position` / `get_position`（含 DPI 与显示器名）/ `show` / `hide` / `minimize_to_tray` / `quit_app` / `set_autostart`（S5 前显式返回未实现） |
| `rust-toolchain.toml` | 钉死 `stable-x86_64-pc-windows-gnu`（本机无 MSVC） |
| `.cargo/config.toml` | 默认 target = windows-gnu，链接器用 `rust-lld` |
| `capabilities/default.json` | Tauri 2 权限声明（自定义命令不需要额外 permission） |
| `desktop/package.json` | `@tauri-apps/cli` + `dev`/`build` 代理到 `../frontend` |

构建入口是 `scripts/tauri.ps1`（内部给 `PATH` 补 binutils 后调 CLI）；窗口形态用 `scripts/check_window.ps1` 取证。

## 数据与契约

| 路径 | 说明 |
| --- | --- |
| `mochi/characters/*.yaml` | 角色卡，入库 |
| `mochi/shared/schema/protocol.schema.json` | 契约生成物，入库 |
| `mochi/frontend/src/types/protocol.ts` | 契约生成物，入库 |
| `mochi/data/` | 运行时数据，**不入库** |
| `mochi/frontend/public/vendor/` | Cubism Core，**不入库** |

## 常见改动的落点

| 想改 | 去哪 |
| --- | --- |
| 换角色说话风格 | `characters/*.yaml` + `ContextBuilder.system_prompt()` |
| 改情绪→动作映射 | `orchestration/performance.py` |
| 加一条斜杠命令 | `orchestration/commands.py` + `decision.py` 前缀规则 |
| 支持新的 LLM 方言 | `providers/openai_compatible.py::_body()` |
| 加 REST 端点 | `main.py` |
| 加 WS 消息 | `gateway/protocol.py` → 生成物 → `gateway/ws.py` 分发 |
| 改窗口形态 | `desktop/src-tauri/tauri.conf.json` + `src/window.rs` |
| 改气泡/面板样式 | `frontend/src/styles/global.css` |

## 相关页面

- [Architecture](Architecture.md) — 先建立分层心智模型
- [Orchestration](Orchestration.md) — 一轮对话的细节
- [Testing](Testing.md) — 改完之后怎么验收
