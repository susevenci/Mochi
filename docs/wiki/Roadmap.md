# Roadmap

## 阶段总览

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| S0 | 环境骨架：后端 / 契约链路 / 前端 / 桌面壳配置 | ✅ 11/12（T0-10 穿透/麦克风待 S5/S4） |
| S1 | 对话闭环 | ✅ 13/13 |
| S2 | Live2D 呈现 | ✅ 14/14（含口型与窗口拖拽，2026-10-22 收尾） |
| S3 | 情感引擎 | ⏳ 下一步 |
| S4 | 语音（ASR / TTS / 半双工 / 音频口型） | ⏳ |
| S5 | 桌面壳（边车托管 / 托盘 / 穿透 / 位置记忆） | ⏳ |
| S6 | 记忆 / Skills / 工具 | ⏳ |
| S7 | 打磨与打包 | ⏳ |

**MVP 边界**：S0 + S1 + S2 + S3 +（S5 的窗口最小集）。

## S1 已完成（v0.1.0）

- Provider 抽象（OpenAI 兼容，DeepSeek / OpenAI / Ollama / LM Studio 只改 `base_url`）
- 角色卡 + 热切换、纯净上下文（I2 单测）
- 流式双通道解析（分隔符拆包 / 失配回吐 / 残缺 JSON / 代码围栏）
- WS 协议 `sys.*` + `chat.*`，中断、指数退避重连
- 前端流式气泡、情绪标签、`/help` `/role` `/new`

## S2 已完成（v0.2.0）

- Live2DStage：加载、包围盒缩放、居中、待机
- 情绪 cue 全链路（后端映射 → WS → 前端执行）
- 点击反馈（摸头 / 戳身体）、能力自适应（无动作模型退回表情）
- 衣柜：模型清单接口 + 热切换
- LLM 配置面板（热更新、关闭思考、动作试玩）
- 修复 pixi 6/7 兼容问题

## S2 收尾（2026-10-22，未发版）

- 控制器分层：`IdleController`（呼吸/眨眼/微摆）、`GazeController`（视线跟随）、`MotionController`（四级优先级 + 10s 冷却）、`ExpressionController`（权重叠加 + 300ms 缓动 + 自动释放）、`LipSync` + `AudioPlayer`（振幅法口型）、`InteractionHandler`（点击/拖拽/上报）、`CueDispatcher`
- `interaction.event` 进入 WS 契约（S3 接刺激源）
- 角色卡 × 模型交叉校验：`presentation.live2d_model` + `GET /api/v1/live2d/binding`
- 静态立绘兜底（PNG 由脚本生成）+ 情绪滤镜
- 窗口拖拽与位置记忆（`window.rs` 10 个命令 + `settings.json`）
- 桌面壳编译打通：GNU 工具链 + `rust-lld` + w64devkit binutils（Tauri CLI 2.12.4）
- 调试面板“一键 S2 自检”6 项全绿：见 [Testing](Testing.md)

## S2 剩余（不阻塞 S3）

| 项 | 原因 | 计划 |
| --- | --- | --- |
| 验收录屏（T2-14） | 当前只有截图 + 可复跑自检 | S3 验收时一并录 |
| 模型 zip 上传（T2-01 未做项） | 单人使用不需要 | S7 分发时再说 |
| 位置记忆端到端 | 代码就绪，尚未真实拖拽对账 | 下次桌面壳实测时验证 |
| 穿透/麦克风（T0-10） | Tauri 能力存在，但需热区与录音配合 | S5 / S4 |

## S3 入口（下一步）

按依赖顺序：

1. **T3-01 DevPanel 曲线最小版**：先有可视化再写引擎（否则无法调参）
2. 数据结构：`PAD` / `EmotionState`(frozen) / `Stimulus` / `EmotionSnapshot` / `StimulusSource`（10 值）
3. 七个数学原语 + 单测（纯函数，最好测）
4. 引擎主体：`apply_stimulus()` / `tick(dt)` / `advance(seconds)` / `snapshot()`
5. 接入五个耦合点（入口刺激、交互事件、prompt 注入、LLM 建议裁决、任务结果）
6. 表现映射改为 **action_map 优先 + 参数兜底**（S2 的结论）
7. 可量化验收：标签切换率、停留时长、差分速率、重复刺激衰减、静默期活跃度

## 已知技术债

| 债 | 影响 | 处理时机 |
| --- | --- | --- |
| 裸检测 + 无 CI | 远端仓库没有自动门禁 | 有 GitHub Actions 计划时补 |
| `pixi-live2d-display@0.4` 与 pixi 7 兼容垫片 | 升级 pixi 或换库时需复核 | 升级时 |
| 前端的模型选择存 localStorage | 换浏览器会丢 | S5 并入 `settings.json` |
| `ProviderFactory` 已被 `LLMSettingsService` 取代但文件仍在 | 冗余代码 | 清理时删 |
| 情感引擎缺位期间情绪来自 LLM | 标签可能跳变 | S3 解决 |
| tag 已到 `v0.2.0`，但 `__version__` / `pyproject.toml` / `package.json` / `tauri.conf.json` 仍是 `0.1.0` | HUD 与包版本显示落后一个阶段 | ✅ v0.3.0 已统一到 `0.3.0` |
| `ConnectionManager.broadcast()` 尚无调用方 | S3 主动推送前是死代码 | S3 接入 |
| `EventBus.ts` 未被主干引用 | 前端存在两条事件通道 | 需要跨模块事件时再启用，或删除 |

## 版本记录

| 版本 | 内容 | 日期 |
| --- | --- | --- |
| v0.1.0 | S1 对话闭环 | 2026-10-21 |
| v0.2.0 | S2 Live2D 呈现 | 2026-10-21 |
| v0.3.0 | S2 收尾：控制器分层 / 口型 / 交互上报 / 窗口记忆 / 桌面壳编译 | 2026-10-22 |

> `v0.1.0` → S1 完成后的 `docs:` 提交，`v0.2.0` → S2 初版提交，`v0.3.0` → S2 收尾提交；从 `v0.3.0` 起 tag 与代码内版本号（`0.3.0`）一致。

## 相关页面

- [Home](Home.md) — 当前状态总览
- [Emotion-Engine](Emotion-Engine.md) — S3 设计蓝图
- [Testing](Testing.md) — 质量门禁

