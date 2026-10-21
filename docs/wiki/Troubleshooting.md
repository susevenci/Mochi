# Troubleshooting

## 症状速查

| 症状 | 先看 |
| --- | --- |
| 页面打不开 / 5173 被占 | 启动与端口 |
| 左下角一直 reconnecting、控制台 4401 | 启动与端口 → WS 鉴权 |
| 回复为空、只有一个标点 | 模型与对话 → 思考模式 |
| 首字 10s+ | 模型与对话 → 首字延迟 |
| 设置面板报 404 / `Unexpected token '<'` | 模型与对话 → Vite proxy |
| 角色不显示、控制台刷 `isInteractive` | Live2D |
| 角色会动但完全不眨眼 / 口型永远为 0 | Live2D → 帧钩子与音频接线 |
| `pytest` / `ruff` 路径或模块错误 | 测试 |

## 启动与端口

**端口被占用**

```powershell
netstat -ano | findstr :8765
Stop-Process -Id <PID> -Force
```

**`npm` 在 PowerShell 被拦（执行策略）**

```
npm : 无法加载文件 ...\npm.ps1，因为在此系统上禁止运行脚本
```

用 `npm.cmd` 代替 `npm`。

**Tauri 编译报 `linker link.exe not found`**

仓库已改为 GNU 工具链（不需要 MSVC）：

```powershell
rustup toolchain install stable-x86_64-pc-windows-gnu --profile minimal
powershell -ExecutionPolicy Bypass -File scripts/setup_binutils.ps1
npm.cmd --prefix desktop install
```

常见后续报错：

| 报错 | 原因 | 修法 |
| --- | --- | --- |
| `missing manifest in toolchain 'stable-x86_64-pc-windows-gnu'` | 工具链下载被中断 | 重新执行 `rustup toolchain install ... --force` |
| `error calling dlltool 'dlltool.exe': program not found` | 缺 binutils（rustc 生成 raw-dylib 用） | 跑 `scripts/setup_binutils.ps1`，并用 `scripts/tauri.ps1` 启动构建 |
| `icons/icon.ico not found` | tauri-build 的硬需求 | `npm.cmd --prefix desktop exec tauri icon ..\frontend\public\fallback\portrait.png` |
| GitHub 下载只有几十 KB/s | release CDN 被限速 | `setup_binutils.ps1` 已内置 8 路并行分块下载 |
| `winget` 报 `0x8a15005e 服务器证书与任何预期值都不匹配` | 本机 winget 下载通道不可用 | 不要靠 winget；按上面手动路径装 |

如果将来装上了 VS Build Tools：删掉 `desktop/src-tauri/rust-toolchain.toml`，并移除 `.cargo/config.toml` 里的 `[build]` 段，即可回到 msvc。

**WS 连接被拒（关闭码 4401）**

后端设置了 `SERVER_TOKEN`，但前端没带 token：

- 浏览器开发：设置 `VITE_SERVER_TOKEN`，或用 `?token=` 打开
- 桌面壳：确认 Rust 侧注入 `window.__MOCHI__.token`
- 只想本地快速验证：把 `.env` 的 `SERVER_TOKEN` 清空并重启（仅限本机）

**5173 端口被占用**

`vite.config.ts` 设了 `strictPort: true`，端口冲突会直接失败而不是自动换端口：

```powershell
netstat -ano | findstr :5173
Stop-Process -Id <PID> -Force
```

## 模型与对话

**回复为空 / 只有一个标点**

本地推理模型默认开"思考"，`max_tokens` 被 `reasoning_content` 吃光，`content` 为空。

- 本项目的做法：请求体带 `chat_template_kwargs.enable_thinking=false`（Qwen 系），`reasoning_effort=low`（gpt-oss / o-series）
- 排查：看 `response.choices[0].message.message_keys` 是否只有 `reasoning_content`
- LM Studio 侧也可以直接关掉思考

**首字延迟很高（10s+）**

先区分是"思考"还是"端点"：

| 现象 | 判断 |
| --- | --- |
| 回复很短但首字仍 10s+，多次几乎相同 | 端点网络/排队延迟（如 NVIDIA 集成端点实测恒为 14.1s） |
| 回复很长且首字高 | 思考未关闭 |

解决：换本地模型（4B 实测 185–966ms）或换更近的云端端点。

**设置面板保存后对话报 `LLM_AUTH_FAILED` / HTTP 502**

| 现象 | 原因 |
| --- | --- |
| 401 / 403 | `api_key` 错误，或 `base_url` 指向了没有该密钥的服务 |
| 404 on `/chat/completions` | `base_url` 少了 `/v1` 之类的版本段 |
| 502 `LLM_UPSTREAM` | 上游 5xx/429，重试后仍失败，稍后再试 |
| 明明改了 `.env` 却不生效 | `<data_dir>/settings.json` 的 `llm` 段优先级更高，去设置面板清掉或改那里 |

`/api/v1/llm/models` 能返回列表，说明 base_url 与 key 至少是通的；此时若对话仍失败，问题通常在模型名。

**设置面板"保存失败：HTTP 404"/"读取失败：Unexpected token '<'"**

Vite dev server 没代理 `/api`，请求被 SPA fallback 返回了 `index.html`。检查 `vite.config.ts`：

```ts
proxy: {
  '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true },
  '/live2d': { target: 'http://127.0.0.1:8765', changeOrigin: true },
}
```

改完必须**重启** dev server。

**改了 `tsconfig` 里的 `jsx` 后 `.tsx` 报 "无法使用 JSX"**

esbuild 只在启动时读 tsconfig，重启 vite 即可。

**控制台无法粘贴代码**

Chrome 防粘贴保护。在 Console 输入 `allow pasting` 回车。

## Live2D

**模型加载了但看不到**

看控制台这行：

```
[live2d] bounds=9600x5400 scale=0.1618 pos=(826,538)
```

- `scale` 是否合理（模型宽度 × scale ≈ 窗口宽度）
- `pos` 是否在窗口内
- 如果没有这行，说明 `load()` 失败，看 `[live2d] 模型加载失败` 的报错

**大量 `currentTarget.isInteractive is not a function`**

`pixi-live2d-display@0.4` 与 pixi 7 的兼容问题，已在 `Live2DStage` 里用 `patchPixi6Interaction()` 修掉。若再出现，确认模型与 `app.stage` 都被 patch。

**完全不眨眼 / 呼吸和微摆也没效果**

参数写了但被 Cubism 自己的参数演算盖掉。帧钩子必须挂在 `Ticker.shared` 且优先级 **低于** 模型自身的 `NORMAL(0)`——
当前用 `UPDATE_PRIORITY.UTILITY(-50)`。若换回正的优先级，表现就是“参数写进去了但画面不动”。

**口型永远是 0（调试面板电平条不动）**

三步排查：

1. 控制台看 `window.mochi.live2d.caps.mouthParamIds` 是否非空（模型没声明 `Groups.LipSync` 且没有 `ParamMouthOpenY*` 时会为空）
2. 看 `window.mochi.lipSync.params` 是否与上一步一致
3. `AudioContext` 是懒创建的：必须由 `AudioPlayer.prepare()` 提前建图，且 `LipSync` 使用解析器（每帧重取 `audio.analyser`）。若只接线一次，拿到的是 `null`，电平永远 0。

**表情叠加后参数直接打满（如 `Param37` 从 0 跳到 1）**

`Add` 类参数若每帧用 `getParameter()` 当基底再叠加，两帧就饱和。正确做法是“底值快照 + 每帧只写一次终值”，
释放时写回底值；当前实现见 `ExpressionController.baseline / restoreBaseline()`。

**像素采样恒为 1 或全 0**

`preserveDrawingBuffer: false` + `alpha: false` 时 `readPixels` 拿不到有效帧，不能用它判断是否渲染。改用控制台日志或 `renderer.extract`。

**中文 zip 解压乱码 / 报 `UnicodeDecodeError`**

Windows 中文 zip 文件名是 GBK：

```python
zipfile.ZipFile(path, metadata_encoding="gbk").extractall(dst)
```

## 编码与终端

**PowerShell 5.1 不支持 `&&`、`&` 被拒**

用 `;` 分隔，或分多条命令执行。

**中文输出在控制台显示为乱码**

控制台是 GBK，UTF-8 内容会花屏但不影响数据。核对时输出到文件再用 UTF-8 读取，或在 Python 里：

```python
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```

**打印掩码 `••••` 抛 `UnicodeEncodeError`**

同上，GBK 控制台无法编码该字符。

## 测试

**`pytest` 找不到 `app` 模块**

`pyproject.toml` 已配置 `pythonpath = ["server"]` 与 `testpaths`；从 `mochi/` 目录运行，或传 `--config-file`。

**`mypy` 报 `Library stubs not installed for "yaml"`**

```powershell
.venv\Scripts\python.exe -m pip install types-PyYAML
```

**生成物与源码不一致**

改完协议后忘跑生成：

```powershell
.venv\Scripts\python.exe mochi\scripts\export_schema.py
node mochi\scripts\gen-types.mjs
```

**`ruff` 报找不到 `pyproject.toml` / 检查了错误目录**

ruff 的配置在 `mochi/pyproject.toml`，不在仓库根：

```powershell
cd mochi
.venv\Scripts\python.exe -m ruff check server scripts --config pyproject.toml
```

pytest 同理，`testpaths` 与 `pythonpath` 都相对 `mochi/` 解析。

## 相关页面

- [Getting-Started](Getting-Started.md) — 正确的启动顺序
- [Providers](Providers.md) — 上游错误码含义
- [Live2D-Pipeline](Live2D-Pipeline.md) — 模型目录与规范化
- [Testing](Testing.md) — 门禁命令

