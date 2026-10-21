# Providers · LLM 接入层

Provider 层是业务与模型服务之间唯一允许的通道（不变量 I5）。业务代码只认 `LLMProvider` Protocol，不认任何 SDK。

## 抽象（`providers/base.py`）

```
LLMProvider (Protocol)
  ├─ async chat(...)   -> ChatResult        非流式
  ├─ stream(...)       -> AsyncIterator[str] 只产出正文增量
  └─ async aclose()
```

配套数据类型：

| 类型 | 作用 |
| --- | --- |
| `ChatMessage(role, content, tool_call_id)` | 线上消息，`to_wire()` 转 OpenAI 格式 |
| `Usage(prompt_tokens, completion_tokens, total_tokens)` | 用量，`from_wire()` 解析 |
| `ChatResult(content, model, finish_reason, usage, reasoning)` | 非流式结果 |
| `LLMError(code, detail)` | 统一异常，`code` 直接进前端错误码 |

I5 不是口头约定：`pyproject.toml` 里用 ruff `banned-api` 禁止业务代码 `import openai`，唯一例外是 `app/providers/*`。

## OpenAI 兼容实现

`providers/openai_compatible.py` 用 `httpx.AsyncClient` 直接实现，不依赖官方 SDK。只要服务端兼容 `/chat/completions`，改 `base_url + model` 即可切换：DeepSeek / OpenAI / Ollama / LM Studio / vLLM / llama.cpp 都是同一条路径。

### 请求体

```json
{
  "model": "<model>",
  "messages": [{"role": "system|user|assistant", "content": "..."}],
  "temperature": 0.85,
  "max_tokens": 400,
  "stream": true,
  "chat_template_kwargs": {"enable_thinking": false}
}
```

`trust_env=False` 是有意为之：本地模型和云端点都不走系统代理，避免代理干扰 POST。

### 关闭思考

桌宠不依赖推理过程，思考只会让首字多等数秒并吃掉 token。不同模型家族的控制方言不同，因此按**模型名**适配，而不是按供应商分支：

| 模型家族 | 控制字段 |
| --- | --- |
| Qwen / llama.cpp / vLLM / LM Studio | `chat_template_kwargs.enable_thinking=false` |
| gpt-oss / o1 / o3 / o4 前缀 | 上述字段 + `reasoning_effort=low` |

`reasoning_content` 在流式解析中一律丢弃，只 yield `delta.content`。

### 重试与错误映射

非流式调用有有限重试：最多 2 次，退避 0.5s → 1s。

| 上游状态 | 处理 |
| --- | --- |
| `401` / `403` | 立即失败，`LLM_AUTH_FAILED`（不重试） |
| `408` `429` `500` `502` `503` `504` | 重试，最终 `LLM_UPSTREAM` |
| 其他 `4xx` | 立即失败，`LLM_BAD_REQUEST` |
| 超时 | 重试，最终 `LLM_TIMEOUT` |
| 网络异常 | 重试，最终 `LLM_NETWORK` |
| `choices` 为空 | `LLM_EMPTY_RESPONSE` |

流式请求不重试：一旦开始产出，重试会导致前端收到重复文本。错误在建立连接阶段就映射为 `LLM_AUTH_FAILED` / `LLM_BAD_REQUEST`。

SSE 解析只处理 `data:` 行，遇到 `[DONE]` 停止，坏行跳过并 debug 记录——单行脏数据不应该毁掉整轮回复。

## 运行时配置与热更新

`config/llm_settings.py` 的 `LLMSettingsService` 持有"当前配置 + Provider 实例"：

```
优先级： `<data_dir>/settings.json` 的 llm 段  >  `.env`（Settings）  >  代码默认
```

| 行为 | 说明 |
| --- | --- |
| `config` | 冻结的 `LLMConfig(base_url, api_key, model, disable_thinking, source)` |
| `provider` | 懒加载；首次访问时按当前配置构建 |
| `update(...)` | 写 `settings.json` → 重新解析 → `aclose()` 旧 Provider → 下一轮使用新实例 |
| `list_models()` | 请求 `{base_url}/models`，返回排序去重后的 ID 列表 |

`source` 字段告诉界面当前配置来自用户还是环境变量（`user` / `env`）。

`api_key` 的安全约定：

- 绝不写日志、绝不回传明文
- 对外视图只给 `api_key_set: bool` 与 `api_key_hint`（`mask_key()`：≤8 位显示 `••••`，否则 `前2••••后4`）
- PATCH 时传空字符串会被拒绝（400），"留空"在界面上表示"不修改"

## 用量统计

`providers/usage.py` 的 `UsageTracker` 按用途（`roleplay` / `decision` / `summary` …）累加调用数与 token，单进程单例（I6）。它已装配进 `AppContext`，但当前**尚未接入调用点**——S1 的流式路径不解析 `usage`，S6 做成本面板时再接。`snapshot()` 可直接复用。

## 接入新供应商的检查清单

1. 确认服务端实现 `/chat/completions` 与 SSE 格式（`data: {...}` + `[DONE]`）。
2. 填 `base_url`（必须以 `/v1` 之类结尾，代码只做 `rstrip("/")`）。
3. 填 `model`，必要时在设置面板里"保存并获取模型"验证连通性。
4. 用 `scripts/probe_llm.py` 验证非流式、流式与首 token 延迟。
5. 若模型默认思考且不支持 `enable_thinking`，观察 `finish_reason` 与正文是否为空，见 [Troubleshooting](Troubleshooting.md)。

## 测试覆盖

`tests/unit/test_provider.py` 验证请求体构造（含两种思考开关方言）、`tests/unit/test_llm_settings.py` 验证配置优先级、掩码、热更新与 `/models` 解析。

## 相关页面

- [Configuration](Configuration.md) — 三层配置与数据目录
- [Orchestration](Orchestration.md) — 谁在调用 stream
- [Troubleshooting](Troubleshooting.md) — 空回复、首字慢、代理问题
