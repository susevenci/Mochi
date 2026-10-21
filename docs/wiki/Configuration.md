# Configuration · 配置与数据

项目的配置刻意分成三层，各管一件事：**环境**（`.env`）、**用户偏好**（`settings.json`）、**前端临时选择**（`localStorage`）。混在一起会导致"改个窗口位置要重启后端"或者"密钥被提交进仓库"。

## 三层配置

| 层级 | 位置 | 内容 | 生效方式 |
| --- | --- | --- | --- |
| 环境配置 | `mochi/.env` → Pydantic `Settings` | 端口、token、数据目录、LLM 默认值、角色默认值 | 重启生效 |
| 用户配置 | `<data_dir>/settings.json` | 窗口状态、LLM 运行时配置（含密钥） | `PATCH` 后即时生效 |
| 前端选择 | 浏览器 `localStorage` | 当前 Live2D 模型 | 即时生效 |

优先级：**用户配置 > 环境配置 > 代码默认**。

`.env` 已被 gitignore；`settings.json` 位于数据目录（默认 `%APPDATA%/Mochi`），同样不入库。

## 环境配置（`config/settings.py`）

`Settings` 使用 `pydantic-settings`，读取当前工作目录下的 `.env`，大小写不敏感，未知键忽略。

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `SERVER_HOST` | `127.0.0.1` | 只监听本机 |
| `SERVER_PORT` | `8765` | HTTP / WS 同端口 |
| `SERVER_TOKEN` | 空 | 为空不校验；发布版由桌面壳随机生成 |
| `DATA_DIR` | `%APPDATA%/Mochi` | 非 Windows 回落到 `~/.config/Mochi` |
| `LOG_LEVEL` | `INFO` | |
| `LLM_API_KEY` | 空 | |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | 必须 OpenAI 兼容 |
| `LLM_MODEL_CHAT` | `deepseek-chat` | 扮演 |
| `LLM_MODEL_DECISION` | `deepseek-chat` | 预留（S6 LLM 兜底分类） |
| `LLM_MODEL_SUMMARY` | `deepseek-chat` | 预留（S6 摘要） |
| `LLM_TEMPERATURE_ROLEPLAY` | `0.85` | |
| `LLM_TEMPERATURE_DECISION` | `0.0` | 预留 |
| `LLM_TIMEOUT_SECONDS` | `20` | httpx 超时 |
| `CHARACTER` | `tsundere` | 启动角色卡 id |

`ensure_dirs()` 在 bootstrap 时创建 `live2d/`、`voices/`、`skills/`、`characters/`、`logs/`。运行时数据与代码分离，卸掉仓库不会丢用户数据。

> `.env` 是按**当前工作目录**解析的。启动前先 `cd mochi`，或在启动命令里显式设置环境变量。

## 用户配置（`config/user_settings.py`）

`UserSettings` 管理数据目录下的 `settings.json`，两个 section：

```json
{
  "window": {
    "position": null,
    "always_on_top": true,
    "click_through": false,
    "autostart": false
  },
  "llm": {
    "base_url": "",
    "api_key": "",
    "model": "",
    "disable_thinking": true
  }
}
```

行为约定：

| 场景 | 行为 |
| --- | --- |
| 文件不存在 | 使用默认值，不报错 |
| JSON 损坏 | 回落默认值，不阻塞启动 |
| 读 | `get_all()` 返回深拷贝，调用方改不到内部状态 |
| 写 | `patch()` 浅合并；`window` / `llm` 段深一层合并 |
| 落盘 | 先写 `.tmp` 再 `replace()` 原子替换，进程被杀不会留半个文件 |

`llm` 段的空值表示"回落到 `.env`"，不是"清空配置"。

### 配置相关端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / PATCH | `/api/v1/config/user` | 仅允许 `window` 键，其他键返回 400 |
| GET / PATCH | `/api/v1/config/llm` | 视图只回 `api_key_hint`；PATCH 校验 `base_url` 为 http(s) |
| GET | `/api/v1/llm/models` | 代理上游 `/models` |

`base_url` 会被 `rstrip("/")`；空 `api_key` 会被拒绝；`model` 空值视为不修改。这些校验在 `main.py` 的 PATCH 处理器里，而不是在 `LLMSettingsService` 里——服务层保持可编程，HTTP 层负责用户输入。

## 数据目录

```
<data_dir>/                     # 默认 %APPDATA%/Mochi
├─ settings.json               # 用户配置（含 LLM 密钥，勿外传）
├─ mochi.db                    # 长期记忆（S6）
├─ live2d/<模型名>/             # Live2D 模型，不入库
├─ voices/                     # TTS 缓存（S4）
├─ skills/                     # Skills（S6）
├─ characters/                 # 预留目录，当前角色卡仍从仓库读取
└─ logs/
```

开发期把 `DATA_DIR` 指到 `mochi/data`（仓库里的 `mochi/data/` 已被 gitignore），可以直接看到 `live2d/`、`settings.json` 与 `probe.json`。

## 角色卡

角色卡放在**仓库**的 `mochi/characters/*.yaml`（不是数据目录），随代码一起版本化。

```yaml
id: tsundere
name: 星璃
identity:
  full_name: 星璃（Hoshiri）
  role: 住在用户桌面里的猫耳少女
  personality: |
    表面傲娇、爱抬杠…
  tone: 轻快、带刺、句尾常上扬
  sentence_length: 偏短，10~35 字
  catchphrases: [哼！, 才、才不是为了你…]
  forbidden: [作为AI, 作为一个语言模型, 我无法, 亲, 您]
greeting: 哼，你终于来了。
fallback: 唔…我这边好像有点状况，等我一下。
```

| 字段 | 约束 | 用途 |
| --- | --- | --- |
| `id` / `name` | 必填 | 文件名应与 `id` 一致 |
| `identity.full_name` / `role` / `personality` | 必填 | 人格内核 |
| `identity.tone` / `sentence_length` | 可选 | 说话风格 |
| `identity.catchphrases` / `forbidden` | 可选 | 口癖与禁词 |
| `greeting` | 可选 | 切换角色时的开场白 |
| `fallback` | 可选 | LLM 故障时的人设化降级文案 |

内置两张卡：`tsundere`（星璃）与 `genki`（小满）。`forbidden` 里的"作为AI / 作为一个语言模型"是防破壁的硬约束，改卡时不要删。

`CardLoader` 启动时加载 `CHARACTER` 指定的卡，`/role set <id>` 热切换并清空上下文。

## 安全约定

| 项 | 约定 |
| --- | --- |
| `SERVER_TOKEN` | 为空=开发模式；非空时 REST 需 `X-Mochi-Token` 或 `?token=`，WS 未授权直接 4401 |
| `api_key` | 只写 `settings.json`；日志与 API 视图都不出现明文 |
| 绑定地址 | 默认 `127.0.0.1`，不要改成 `0.0.0.0` |
| 代理 | Provider 与 `/models` 请求都 `trust_env=False`，避免系统代理改写本地请求 |
| 仓库卫生 | `.env`、`data/`、模型、Cubism Core 全部 gitignore |

## 相关页面

- [Getting-Started](Getting-Started.md) — 首次配置步骤
- [Providers](Providers.md) — LLM 配置如何生效
- [Frontend](Frontend.md) — 前端如何拿到端口与 token
