# Mochi · 情感桌宠

常驻桌面、拥有**持续情绪状态**、能文字/语音对话的 Live2D AI 桌宠。

架构思想参考 [KdaiP/EchoBot](https://github.com/KdaiP/EchoBot)，代码独立实现。

> 本 Wiki 记录**设计与实现细节**；快速开始请看仓库 [README](https://github.com/susevenci/Mochi#readme)。
> 所有页面都在 `docs/wiki/`，与代码同仓库演进。

## 三个身份

| 身份 | 说明 | 关键能力 |
| --- | --- | --- |
| 陪伴者 | 有性格、有情绪、有记忆的桌面伙伴 | 情感引擎、人格一致性、长期记忆 |
| 表演者 | 用 Live2D 把内在状态"演"出来 | 表情 / 动作 / 口型 / TTS 韵律联动 |
| 执行者 | 能调用工具完成轻量任务 | 工具循环、Skills 懒加载 |

## 当前状态

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| S0 | 环境骨架：后端 / 契约链路 / 前端 / 桌面壳配置 | ✅ 11/12（T0-10 穿透/麦克风待 S5/S4） |
| S1 | 对话闭环：Provider、角色卡、纯净上下文、流式双通道解析、WS、前端 UI | ✅ 13/13 |
| S2 | Live2D 呈现：待机/视线/表情叠加/动作队列/口型/窗口拖拽 | ✅ 14/14（2026-10-22 收尾） |
| S3 | 情感引擎：PAD 状态机、衰减、人格调制 | ⏳ 下一步 |
| S4 | 语音：ASR / TTS / 半双工 / 音频口型 | ⏳ |
| S5 | 桌面壳：边车托管、托盘、穿透 | ⏳ |
| S6 | 记忆 / Skills / 工具 | ⏳ |
| S7 | 打磨与打包 | ⏳ |

发布记录：`v0.1.0`（S1）、`v0.2.0`（S2 初次落地）、`v0.3.0`（S2 收尾：控制器分层 + 口型 + 桌面壳编译）。代码内版本号已同步到 `0.3.0`。

## 导航

### 入门

| 页面 | 内容 |
| --- | --- |
| [Getting-Started](Getting-Started.md) | 环境准备、启动、冒烟与验收命令 |
| [Troubleshooting](Troubleshooting.md) | 启动失败、思考模式、代理、编码、Live2D 黑屏 |

### 设计

| 页面 | 内容 |
| --- | --- |
| [Architecture](Architecture.md) | 分层、六条不变量、数据流、关键权衡 |
| [Orchestration](Orchestration.md) | 决策/扮演/命令、双通道解析、取消传播 |
| [Emotion-Engine](Emotion-Engine.md) | PAD 状态机设计（S3 蓝图） |
| [Live2D-Pipeline](Live2D-Pipeline.md) | 模型准备、能力自适应、衣柜、渲染踩坑 |

### 实现

| 页面 | 内容 |
| --- | --- |
| [Providers](Providers.md) | OpenAI 兼容接入、重试、关闭思考、热更新 |
| [Memory-and-Context](Memory-and-Context.md) | 短期窗口、上下文预算、I2 约束 |
| [Frontend](Frontend.md) | WSClient、对话状态机、表现层、设置面板、Shell 适配 |
| [Protocol](Protocol.md) | WS 信封与消息类型、REST 端点、错误码、契约生成 |
| [Configuration](Configuration.md) | 三层配置、数据目录、角色卡、安全约定 |
| [Code-Tour](Code-Tour.md) | 文件级代码地图与"想改 X 去哪" |
| [Testing](Testing.md) | 64 项测试分布、S2 自检、窗口取证、质量门禁 |

### 规划

| 页面 | 内容 |
| --- | --- |
| [Roadmap](Roadmap.md) | 阶段划分、遗留项、技术债 |

## 实测指标

- 流式**首 token**：本地 4B（LM Studio）185–966ms；NVIDIA 集成端点约 14s（端点固定延迟，非思考导致）
- 多轮短期记忆、角色卡热切换、情绪标签随回复产出
- Live2D：`qiye_10` 49 个动作组、点击摸头/戳身体、衣柜热切换；待机呼吸/眨眼/微摆位移可见，口型电平能打到 0.79
- 桌面壳：`class=Tauri Window` 420×560、topmost、角落像素与桌面同色（透明）
- 质量门禁：`ruff 0` / `mypy 0`（43 文件）/ `pytest 64 passed` / `tsc + vite build` 通过
