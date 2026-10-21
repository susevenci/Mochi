# Mochi · 情感桌宠

> 常驻桌面、拥有**持续情绪状态**、能文字/语音对话的 Live2D AI 桌宠。
> 架构思想参考 [KdaiP/EchoBot](https://github.com/KdaiP/EchoBot)，代码独立实现。

Mochi 不是"套了动漫皮的聊天客户端"，而是三个身份的叠加：

| 身份 | 说明 | 关键能力 |
| --- | --- | --- |
| 陪伴者 | 有性格、有情绪、有记忆的桌面伙伴 | 情感引擎、人格一致性、长期记忆 |
| 表演者 | 用 Live2D 把内在状态"演"出来 | 表情 / 动作 / 口型 / TTS 韵律联动 |
| 执行者 | 能调用工具完成轻量任务 | 工具循环、Skills 懒加载 |

## 当前进度

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| S0 | 环境骨架：后端 / 契约链路 / 前端 / 桌面壳配置 | ✅ 12 项中 7 项通过（壳待 MSVC） |
| S1 | 对话闭环：Provider、角色卡、纯净上下文、流式双通道解析、WS、前端 UI | ✅ 13/13 |
| S2 | Live2D 呈现：模型加载、待机、表情/动作、口型 | 🚧 进行中 |
| S3 | 情感引擎：PAD 状态机、衰减、人格调制、调试面板 | ⏳ |
| S4 | 语音链路：ASR / TTS / 半双工 / 打断 | ⏳ |
| S5 | 桌面壳：边车托管、托盘、穿透、开机自启 | ⏳ |
| S6 | 记忆 / Skills / 工具 | ⏳ |
| S7 | 打磨与打包 | ⏳ |

已实测指标（本地 LM Studio，`qwen3.5-4b`，关闭思考模式）：

- 流式**首 token 0.10s**（探针）/ 185–966ms（含上下文的真实对话）
- 多轮短期记忆、角色卡热切换、`happy` 情绪标签随回复产出
- `ruff` 0 问题 / `mypy` 0 issue / `pytest` 38 passed

## 架构

```
┌──────────────────────────────────────────────┐
│ 桌面壳 Tauri（窗口/托盘/边车）                 │
├──────────────────────────────────────────────┤
│ 前端 WebView：Live2D 渲染 · 口型 · 气泡 UI     │
├──────────────────────────────────────────────┤
│ 后端 Python：                                 │
│   Decision ──▶ Roleplay（纯净上下文）          │
│      └──────▶ Agent Core（工具循环）           │
│   EmotionEngine（PAD 状态机，横切）            │
│   Memory / Tools / Skills / Voice / Provider  │
├──────────────────────────────────────────────┤
│ LLM（OpenAI 兼容）· TTS · ASR · 搜索           │
└──────────────────────────────────────────────┘
```

三条不变量（违反即返工）：

1. **情绪只有后端一个权威源**，前端只负责表现。
2. **扮演层 prompt 中不得出现任何工具 schema**（防人设稀释）。
3. **前后端契约单一真相源**：后端 Pydantic → JSON Schema → 前端 TS 类型，生成物禁止手改。

### 三层编排为什么必须分离

| 层 | 上下文 | 工具 schema | 目标 |
| --- | --- | --- | --- |
| Decision | 3 轮摘要 | 0 | < 1ms 路由 |
| Roleplay | 人格 + 情绪 + 记忆 | **0（硬约束）** | 首字 < 2.5s、人设稳定 |
| Agent Core | 任务 + 全量工具 | 全量 | 后台执行、错误回灌自愈 |

本质不是"三次 LLM 调用"，而是**三套上下文策略**——所以代码里只有一个 `ContextBuilder(layer=...)`，而不是三个 prompt 拼接函数。

## 目录结构

```
mochi/
├─ server/app/            # FastAPI 后端
│  ├─ gateway/            # WS 信封、鉴权、心跳、对话分发
│  ├─ orchestration/      # Decision / Roleplay / Turn 注册表 / 双通道解析
│  ├─ providers/          # OpenAI 兼容 Provider（多模型分工、重试、用量）
│  ├─ memory/             # 上下文预算、短期窗口
│  ├─ config/             # Settings、角色卡、settings.json
│  └─ utils/              # ULID、数学原语
├─ server/tests/          # 38 项测试（协议 / 解析器 / 编排 / 角色扮演）
├─ frontend/src/          # Vite + TS + pixi（Live2D 层零框架依赖）
├─ desktop/src-tauri/     # 透明置顶窗配置（待 Rust 工具链）
├─ characters/            # 角色卡 YAML（人格、口癖、禁忌）
├─ shared/schema/         # 契约 JSON Schema（由后端导出）
└─ scripts/               # 体检 / 契约生成 / 冒烟 / 模型选型
```

## 快速开始

前置：Python ≥ 3.11、Node ≥ 20、一个 OpenAI 兼容的 LLM（本地 [LM Studio](https://lmstudio.ai/) 或云端 DeepSeek / OpenAI）。

```powershell
# 1. 后端
cd mochi
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env          # 填 LLM_BASE_URL / LLM_MODEL_CHAT / LLM_API_KEY
.venv\Scripts\python.exe -m uvicorn --app-dir server app.main:create_app --factory --port 8765
```

```powershell
# 2. 前端
cd mochi/frontend
npm install
npm run dev                     # http://127.0.0.1:5173
```

```powershell
# 3. 冒烟（可选）
.venv\Scripts\python.exe mochi\scripts\doctor.py            # 环境体检
.venv\Scripts\python.exe mochi\scripts\smoke_ws.py          # WS 握手
.venv\Scripts\python.exe mochi\scripts\smoke_chat.py --scenario memory   # 真实对话
```

在输入框输入 `你好呀` 即可对话；`/help` 查看命令，`/role set genki` 切换角色。

### 质量门禁

```powershell
.venv\Scripts\python.exe -m pytest mochi
.venv\Scripts\python.exe -m ruff check mochi\server mochi\scripts --config mochi\pyproject.toml
.venv\Scripts\python.exe -m mypy mochi\server\app mochi\scripts --config-file mochi\pyproject.toml
.venv\Scripts\python.exe mochi\scripts\export_schema.py     # 改契约后重新导出
node mochi\scripts\gen-types.mjs                            # 再生成前端类型
```

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | Python 3.11+ · FastAPI · uvicorn（单 worker）· Pydantic v2 · aiosqlite |
| LLM | OpenAI 兼容协议（DeepSeek / OpenAI / Ollama / LM Studio 只改 base_url） |
| 前端 | Vite 5 · TypeScript 5.4 · pixi.js 7.4 · pixi-live2d-display（Cubism 2/4） |
| 桌面壳 | Tauri 2（透明/置顶/无边框/托盘/边车），Electron 为 Plan B |
| 质量 | ruff · mypy · pytest |

## 版权与使用声明

- 本项目代码仅用于个人学习与本地使用。
- **Live2D 模型不入库**：模型体积大且版权归属原公司（如游戏厂商），仅存放在本地 `mochi/data/live2d/`，仓库中只保留 `characters/*.yaml` 里的模型名引用。
- 同理，不随仓库分发任何提取自商业游戏的素材。
