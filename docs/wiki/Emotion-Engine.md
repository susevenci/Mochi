# Emotion Engine

> **状态：设计蓝图，尚未实现（S3）**。本页记录设计，供实现时对照；当前的情绪标签来自 LLM 建议。

## 当前替代方案（S1/S2）

在引擎缺位期间，链路是：

```
LLM 输出的 <<<MOOD>>> JSON
  └─ emotion.label
       └─ orchestration/performance.map_emotion()
            └─ performance.cue(motion, priority)
```

这套方案能跑通表现层，但有本页开头列出的三个问题。S3 的接入方式是**替换输入源而不改下游**：

| 环节 | 现在 | S3 之后 |
| --- | --- | --- |
| 情绪来源 | LLM 自报 `emotion.label` | `EmotionEngine.snapshot()` 裁决 |
| 映射 | `map_emotion()` | 同一个 `map_emotion()`，输入换成快照 |
| 协议 | `performance.cue` | 不变 |
| 握手 | `sys.hello_ack.emotion = null` | 下发当前快照 |

`SysHelloAckPayload.emotion` 已预留；`FinalPayload.emotion` 当前承载 LLM 建议，S3 后换成引擎快照，字段不变。


## 为什么需要独立引擎

只靠 LLM 输出的情绪标签，会有三个致命问题：

1. **无记忆**：每轮重新判定，"上一句被夸"不会影响"这一句的心情"
2. **不一致**：同一句话可能给出不同标签
3. **不可解释**：无法回答"她为什么现在不开心"

所以情绪必须是**后端持续演进的状态**，LLM 只是刺激源之一。

## PAD 三维模型

| 维度 | 范围 | 含义 |
| --- | --- | --- |
| Valence（效价） | −1 … +1 | 愉悦 ↔ 不悦 |
| Arousal（唤醒） | 0 … 1 | 平静 ↔ 激动 |
| Dominance（支配） | 0 … 1 | 顺从 ↔ 掌控 |

在 PAD 之上再映射出 **16 个离散标签**（用于表现层与日志）：

`neutral` `happy` `excited` `amused` `affectionate` `shy` `proud` `curious`
`sleepy` `bored` `lonely` `sad` `worried` `angry` `hurt` `surprised`

## 双时间尺度

| 变量 | 语义 | 衰减 | 用途 |
| --- | --- | --- | --- |
| `emotion`（快） | 当前这一轮的情绪 | 秒级，回归基线 | 表情/动作、回复语气 |
| `mood`（慢） | 长期心境 | 分钟～小时级 | 长期人设偏移、亲密度 |

快变量制造"反应"，慢变量制造"性格"。

## 七个计算原语

实现时**只允许**这七种运算，便于单测与调参：

| 原语 | 作用 |
| --- | --- |
| `soft_step(x, low, high)` | 平滑阈值（代替硬 if），避免标签跳变 |
| `decay_toward(value, baseline, tau, dt)` | 指数回归基线 |
| `update_mood(mood, emotion, alpha)` | 快变量向慢变量渗透 |
| `compute_intensity(stimulus, sensitivity)` | 刺激强度 → PAD 增量 |
| `apply_habituation(stimulus, history)` | 重复刺激衰减（1 : 0.7 : 0.49 …） |
| `infer_label(pad)` | PAD → 16 标签（带滞回） |
| `modulate(base, mood)` | 人格对表达的调制（傲娇会把 +V 表现为更小的正向偏移） |

## 与编排层的五个耦合点

情绪引擎不侵入编排逻辑，只在五个明确位置交互：

| # | 位置 | 方向 | 内容 |
| --- | --- | --- | --- |
| 1 | 用户输入入口 | 刺激 → 引擎 | `StimulusSource`: `user_praise` / `user_insult` / `user_touch` / `task_success` … |
| 2 | 交互事件（点击/拖拽） | 刺激 → 引擎 | 由 `interaction.event` 上报 |
| 3 | `ContextBuilder` | 引擎 → prompt | 注入"当前心情"文本块（不是数值） |
| 4 | LLM 情绪建议裁决 | 引擎裁决 | LLM 说"开心"，引擎可下调（人格/心境不允许剧烈跳变） |
| 5 | 任务结果 | 刺激 → 引擎 | 工具成功/失败 |

裁决规则：LLM 的建议作为**一次性刺激**进入引擎，最终状态由引擎决定 → 保证 I1（情绪单一权威源）。

## 时间旅行

必须支持：

```python
engine.advance(seconds=8 * 3600)   # 模拟"离线 8 小时后重逢"
```

否则无法验证"衰减是否正确"，也做不了"久别重逢"这种关键体验。所有衰减必须写成 `f(dt)` 而不是每帧固定值。

## 可量化验收

| 指标 | 目标 |
| --- | --- |
| 标签切换率 | 4–12 次/小时（太低像面瘫，太高像抽搐） |
| 平均停留时长 | ≈ 1.2 × τ |
| 一阶差分（变化速率） | < 0.3 / s |
| 重复刺激衰减比 | 1 : 0.7 : 0.49 |
| 静默期活跃度 | > 0.01（不能彻底死寂） |

## 调试面板（S3 第 1 天交付）

先做 Curve 面板再接引擎——没有可视化就没法调参：

- 三条曲线（V/A/D）实时滚动
- 刺激注入按钮（点一下就发一个 `user_praise`）
- 当前标签与置信度
- `advance(seconds)` 快进控件

## 对表现层的影响（结合 S2 结论）

S2 的事实是：**本批模型没有可用的 `.exp3` 情绪表情**。因此 S3 的输出映射应改为：

```
EmotionState → action_map（动作组）优先 → 参数兜底（ParamEyeLOpen / ParamMouthForm / ParamAngleZ）
```

而不是原计划书 5.2.9 的 `expression_map`。

## 实现提示

| 事项 | 建议 |
| --- | --- |
| 模块位置 | 新增 `server/app/emotion/`，与 `memory/` 平级；不要把状态塞进 `Orchestrator` |
| 状态持久化 | 先内存 + 定期快照到 `settings.json` 同级文件；S6 再进 SQLite |
| 与 LLM 建议的关系 | LLM 的 `emotion.label` 作为 `Stimulus`，不是最终状态（保证 I1） |
| 测试 | 七个原语都是纯函数，优先单测；`advance(seconds)` 必须可重复 |
| 观测 | 每次标签切换记录 `from → to`、`V/A/D`、触发刺激，否则无法调参 |

## 相关页面

- [Orchestration](Orchestration.md) — 引擎的五个耦合点
- [Live2D-Pipeline](Live2D-Pipeline.md) — 表现层能力限制
- [Roadmap](Roadmap.md) — S3 任务顺序

