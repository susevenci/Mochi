# Getting Started

## 前置条件

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Python | ≥ 3.11 | 需要 `StrEnum`、`tomllib` |
| Node.js | ≥ 20 | 前端构建 |
| LLM | OpenAI 兼容 | 本地 LM Studio / Ollama，或云端 DeepSeek / OpenAI |
| Live2D 模型 | Cubism 2/3/4 | 自行准备，不入库（见 [Live2D-Pipeline](Live2D-Pipeline.md)） |

> 桌面壳（Tauri 2）的构建需要 Rust；**本机没有 MSVC 也能编**：仓库固定用 GNU 工具链（`desktop/src-tauri/rust-toolchain.toml`），详见下方“6. 桌面壳”。

## 0. 一键启动（可选）

```powershell
powershell -ExecutionPolicy Bypass -File mochi\scripts\dev.ps1
# 只起后端：-BackendOnly
# 只起前端：-FrontendOnly
```

脚本会各开一个终端运行 uvicorn（`--reload`）与 Vite；关闭对应窗口即停止。

## 1. 后端

```powershell
cd mochi
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

编辑 `.env`（本文件已被 gitignore）：

```ini
LLM_API_KEY=local
LLM_BASE_URL=http://127.0.0.1:8080/v1
LLM_MODEL_CHAT=<你的模型名>
LLM_MODEL_DECISION=<同上>
LLM_MODEL_SUMMARY=<同上>
LLM_TEMPERATURE_ROLEPLAY=0.85
LLM_TEMPERATURE_DECISION=0.0
LLM_TIMEOUT_SECONDS=60
SERVER_PORT=8765
```

```powershell
.venv\Scripts\python.exe -m uvicorn --app-dir server app.main:create_app --factory --host 127.0.0.1 --port 8765
```

启动日志应包含：

```
bootstrap data_dir=... character=tsundere model=<模型名> token=disabled
live2d static mounted: ...\data\live2d
```

## 2. 前端

```powershell
cd mochi/frontend
npm install

# Live2D Cubism Core（官方 SDK，不随仓库分发）
mkdir public\vendor
curl.exe -L -o public\vendor\live2dcubismcore.min.js https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js

npm run dev
```

打开 `http://127.0.0.1:5173`。左下角显示 `ready v<server_version>`（当前后端 `__version__` 为 `0.3.0`）表示 WS 握手成功。

> 前端已配置 `/api` 与 `/live2d` 代理到 `127.0.0.1:8765`，无需处理 CORS。

## 3. 冒烟验证

```powershell
# 环境体检（Python / Node / pnpm / cargo / WebView2）
.venv\Scripts\python.exe mochi\scripts\doctor.py

# WS 握手 + 心跳
.venv\Scripts\python.exe mochi\scripts\smoke_ws.py

# 真实对话（多轮记忆）
.venv\Scripts\python.exe mochi\scripts\smoke_chat.py --scenario memory

# 模型连通性与首 token 延迟
.venv\Scripts\python.exe mochi\scripts\probe_llm.py --base-url http://127.0.0.1:8080/v1 --model <模型名> --api-key local
```

## 4. 界面操作

| 操作 | 效果 |
| --- | --- |
| 输入框回车 | 发送消息（流式逐字显示） |
| `Esc` | 打断当前生成 |
| 点击角色上半身 | 播放摸头动作 |
| 点击角色下半身 | 播放戳身体动作 |
| 右上角齿轮 | 打开设置：LLM 配置 / 衣柜 / 动作试玩 |
| 右上角锤子 | 打开 S2 调试面板：口型电平表 / 动作试玩 / 表情叠加 / 一键自检 |
| `/help` | 查看斜杠命令 |
| `/role set genki` | 热切换角色卡（清空上下文） |

## 5. 质量门禁

```powershell
.venv\Scripts\python.exe -m pytest mochi
.venv\Scripts\python.exe -m ruff check mochi\server mochi\scripts --config mochi\pyproject.toml
.venv\Scripts\python.exe -m mypy mochi\server\app mochi\scripts --config-file mochi\pyproject.toml
```

改了协议（Pydantic）后必须重新生成契约：

```powershell
.venv\Scripts\python.exe mochi\scripts\export_schema.py   # 生成 JSON Schema
node mochi\scripts\gen-types.mjs                          # 生成前端 TS 类型
```

两份生成物都要提交；手改生成物会被视为破坏"契约单一真相源"。

## 6. 桌面壳（可选，Windows）

前置（一次性）：

```powershell
# 1) GNU host 工具链（本机无 MSVC，用不到 link.exe）
rustup toolchain install stable-x86_64-pc-windows-gnu --profile minimal

# 2) binutils（rustc 生成 raw-dylib 导入库需要 dlltool，tauri-build 打资源需要 windres）
powershell -ExecutionPolicy Bypass -File scripts/setup_binutils.ps1

# 3) Tauri CLI（装在 desktop 下，约 30MB）
npm.cmd --prefix desktop install

# 4) 体检：应看到 Rust GNU 工具链 / Tauri CLI / WebView2 全为 PASS
.venv\Scripts\python.exe scripts\doctor.py
```

日常：

```powershell
# 同时拉起 Vite（beforeDevCommand）+ 编译壳 + 开窗口
powershell -ExecutionPolicy Bypass -File scripts/tauri.ps1 dev

# 打包
powershell -ExecutionPolicy Bypass -File scripts/tauri.ps1 build

# 只验证 Rust 侧能编（不跑 GUI）
cd desktop\src-tauri; cargo check
```

要点：

- 窗口是**透明 + 无边框 + 置顶 + 不占任务栏**，启动时 `visible=false`，前端模型就绪后才 `show_window`，避免白闪。
- 拖拽角色超过 6px → 调 `start_dragging()` 拖窗口；松手把位置写入 `data/settings.json` 的 `window.position`，下次启动恢复。
- 窗口形态可用 `scripts/check_window.ps1` 取证（枚举窗口 + 像素比对）。
- 若将来装了 VS Build Tools，删掉 `rust-toolchain.toml` 与 `.cargo/config.toml` 的 `[build]` 段即可回到 msvc。

## 7. 验收清单

启动完成后，按顺序确认：

| # | 检查 | 期望 |
| --- | --- | --- |
| 1 | `http://127.0.0.1:8765/health` | `{"status":"ok", ...}` |
| 2 | 前端左下角状态 | `ready v0.3.0` |
| 3 | 输入 `你好呀` | 气泡逐字增长，定稿后显示情绪标签 |
| 4 | 输入 `我叫阿哲`，再问 `我叫什么名字` | 能回答出名字（短期记忆生效） |
| 5 | `Esc` | 停止生成，不报错 |
| 6 | 点击角色上半身 / 下半身 | 摸头 / 戳身体动作（或表情降级） |
| 7 | 右上角齿轮 → 保存 LLM | 状态行提示"已保存并生效" |
| 8 | 右上角锤子 → 运行 S2 自检 | `自检通过（6 项）` |
| 9 | `smoke_ws.py` | `smoke ok` |

任何一项不符合，先看 [Troubleshooting](Troubleshooting.md)，再用 `scripts/doctor.py` 排除环境问题。

## 相关页面

- [Configuration](Configuration.md) — 三层配置与数据目录
- [Testing](Testing.md) — 测试与门禁细节
- [Live2D-Pipeline](Live2D-Pipeline.md) — 模型从哪来

