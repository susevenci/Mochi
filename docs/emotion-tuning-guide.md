# 情感调参指南

## 1. 文件分工

| 文件 | 负责 |
| --- | --- |
| `server/app/emotion/data/labels.yaml` | 16 标签的 PAD 中心、半径、τ、TTS、风格 |
| `server/app/emotion/data/stimuli.yaml` | 刺激 tag 的 dval/darousal/ddominance、类别、habituation |
| `server/app/emotion/data/transitions.yaml` | 禁止直跳、条件转移、守卫 |
| `characters/*.yaml` 的 `persona` | 反应增益、心境基线、标签偏置、刺激重解释 |

## 2. 七个原语（先测再调）

`soft_step` / `decay_toward` / `update_mood` / `compute_intensity` /
`apply_habituation` / `infer_label` / `modulate`。

它们全在 `emotion/` 内以纯函数实现；单测覆盖 `tests/unit/emotion/`。

## 3. 调参闭环

```powershell
# 1) 轨迹模拟（五项指标）
& scripts\py.ps1 scripts\analyze_trajectory.py --simulate 200 --seed 42

# 2) 单测 + 覆盖率
& scripts\py.ps1 -m pytest server\tests --cov=app.emotion --cov-fail-under=80

# 3) 面板实测
# 锤子按钮 → 情感/PAD：注入刺激、看曲线、滑杆即时生效、导出轨迹
```

健康区间：

| 指标 | 健康 |
| --- | --- |
| 标签切换率 | 4–12 次/小时（仅互动时段） |
| 一阶差分极值 | <0.3 /s |
| 重复刺激增幅比 | ≈1 : 0.7 : 0.49 |
| 静默 10 分钟活动 | >0.01 |
| 平均停留 | ≈1.2 × τ |

## 4. 常见症状

| 症状 | 可能原因 | 调整 |
| --- | --- | --- |
| 永远 neutral | 阈值 0.35 太高 / 标签半径太小 | 降 `infer.threshold` 或增 radius |
| 情绪癫痫 | reactivity 过高 / 不应期太短 | 降 reactivity，升 refractory |
| 生气后回不来 | 状态机缺少自然平复守卫 | 检查 `angry→neutral` 的 valence 守卫 |
| 连夸不递减 | 刺激未标 `habituate` | 在 stimuli.yaml 打开 |
| 冷落不 lonely | idle 偏好/转移守卫 | 检查 `_idle_preferred_label` 与 transitions |

## 5. 纪律

一次只改一类参数；每次把改前/改后指标写进 `docs/evidence/`。不要同时改标签中心和反应增益，否则无法归因。
