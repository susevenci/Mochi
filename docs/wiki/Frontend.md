# Frontend · 前端

前端只有两个职责：**把模型画出来**、**把对话显示出来**。所有状态判断都在后端，前端不做情绪计算（I1/I3）。

## 技术栈与形态

| 项 | 选型 | 说明 |
| --- | --- | --- |
| 构建 | Vite 5 | `base: './'`，打包后可由 Tauri 以 file/asset 协议加载 |
| 语言 | TypeScript 5.4 | `tsc --noEmit` 作为类型门禁 |
| 渲染 | pixi.js 7.4.2 | 透明背景 WebGL 画布 |
| Live2D | pixi-live2d-display 0.4（cubism4） | 需要官方 Cubism Core 运行时 |
| 面板 UI | Preact 11 | 只有设置面板用它；Live2D 层零框架依赖 |
| 桌面壳 | Tauri 2（S5） | 通过 `ShellAdapter` 抽象，浏览器下为 no-op |

## 模块地图

```
src/
├─ main.ts                 入口：装配 pixi / WS / 控制器 / 面板
├─ config.ts               运行时配置（注入 > 环境变量 > 默认）
├─ net/
│  ├─ WSClient.ts          WS 连接、心跳、退避重连、按 type 分发
│  ├─ EventBus.ts          通用事件总线（当前未在主干使用）
│  └─ ulid.ts              前端 ULID（与后端同构）
├─ live2d/
│  ├─ Live2DStage.ts       加载 / 布局 / 参数读写 / hitTest / 帧钩子
│  ├─ IdleController.ts    呼吸、眨眼、身体微摆（情绪化待机）
│  ├─ GazeController.ts    视线跟随（150ms 平滑 + 闲置自张望）
│  ├─ MotionController.ts  四级优先级队列 + 10s 冷却 + 随机小动作
│  ├─ ExpressionController.ts  表情权重叠加 + 300ms 缓动 + 自动释放
│  ├─ LipSync.ts           振幅法口型（RMS → 嘴部参数）
│  ├─ AudioPlayer.ts       WebAudio 播放 + AnalyserNode + 合成测试音
│  ├─ InteractionHandler.ts  点击/拖拽判定与 interaction.event 上报
│  └─ CueDispatcher.ts     消费 performance.cue，分派给上述控制器
├─ ui/
│  ├─ SettingsPanel.tsx    LLM 配置 / 衣柜 / 动作试玩
│  └─ DevPanel.tsx         S2 调试面板：电平表 / 手动触发 / 一键自检
├─ shell/
│  ├─ ShellAdapter.ts      窗口能力接口（含 isDesktop 标记）
│  ├─ TauriAdapter.ts      invoke 到 Rust 命令（`window.rs`）
│  ├─ WebAdapter.ts        浏览器 no-op 实现
│  └─ detect.ts            运行时选择实现
├─ types/protocol.ts       **生成物**，禁止手改
└─ styles/global.css       气泡、输入框、HUD、面板、兜底立绘样式
```

## 启动时序

```
main.ts
  ├─ new Application({antialias}) + background.alpha = 0
  ├─ new Live2DStage / Motion / Expression / Idle / Gaze / LipSync / AudioPlayer / CueDispatcher
  ├─ bootModel()
  │    ├─ GET /api/v1/live2d/models + /api/v1/live2d/binding
  │    ├─ 优先级：localStorage → 角色卡声明 → 清单第一个 → 内置 URL
  │    └─ load(url) → attachControllers() → expression.load()
  ├─ restoreWindowPosition()（仅 Tauri）→ shell.show()（避免白闪）
  ├─ WSClient.connect()
  │    └─ onopen → sys.hello → sys.hello_ack → HUD 显示 ready v<version>
  └─ 绑定输入框、Esc、点击/拖拽、鼠标移动（视线）、齿轮与锤子按钮
```

`WSClient` 与模型加载是并行的：模型慢不应阻塞对话，对话也不应等模型。

## WSClient

| 能力 | 实现 |
| --- | --- |
| 鉴权 | `?token=`（来自 `resolveConfig()`） |
| 握手 | 连接后立即发 `sys.hello` |
| 心跳 | 每 20s 发 `sys.ping` |
| 重连 | 指数退避 `1s → 2s → 4s → 8s → 16s → 30s`，成功后 `attempt=0` |
| 订阅 | `on(type, handler)` 返回取消函数；`onAny` 监听全部 |
| 发送 | `send(type, payload, turnId?)`，自动填 `v/id/ts` |
| 坏消息 | 非 JSON 或缺少 `type` 直接忽略并 warn |

生成期间连接必须保持可读——`chat.interrupt` 依赖它。连接一旦断开，服务端下一次推送失败并结束本轮 Task，前端需要重连后重发；没有自动补发机制。

## 对话状态机（`main.ts`）

```
idle ──submit──▶ streaming（currentTurn=turn_id，占位气泡"…"）
streaming ──agent_delta──▶ 追加文本
streaming ──agent_final──▶ idle（定稿、显示情绪标签、解锁输入）
streaming ──Esc──▶ chat.interrupt ──▶ agent_final(error=TURN_CANCELLED) ──▶ idle
```

约定：

- 同一时刻只允许一轮（`currentTurn !== null` 时忽略新输入）。
- 收到的消息按 `turn_id` 过滤，避免上一轮的迟到增量污染新气泡。
- `agent_final.text` 会覆盖整个气泡，保证定稿与流式文本一致。
- `error` 不是 `TURN_CANCELLED` 时追加一条错误气泡，但界面不崩。
- 情绪标签来自 `final.emotion.label`，只用于显示，不参与任何逻辑。

## 表现层

```
performance.cue
  └─ CueDispatcher.dispatch()
       ├─ idle.setEmotion(label)                 ← 身体语言跟着情绪变
       ├─ motion.request(motion, priority)       ← 队列 + 10s 冷却
       └─ expression.play(cue.expression ?? label, 1, {autoReleaseMs})
```

`Live2DStage` 的能力自适应与缩放细节见 [Live2D-Pipeline](Live2D-Pipeline.md)。

点击与拖拽由 `InteractionHandler` 接管：优先 `hitTest`，模型没定义 `HitAreas`
（`qiye_10` 就是）时按包围盒分区（上 30% 头 / 30%~45% 脸 / 其余身体）；
位移超过 6px 视为拖拽→调 `startDragging()` 拖窗口，松手后把位置写回 `settings.json`。
每次点击都上报 `interaction.event`（S3 的情绪刺激源会消费它）。

## 设置面板

`SettingsPanel.tsx` 用 Preact 写成，但仍挂载在原生 DOM 容器 `#settings-root` 上。它通过 `window.mochi` 句柄访问舞台与模型切换函数，避免把 pixi 实例塞进 props。

面板包含四块：

| 区块 | 交互 |
| --- | --- |
| LLM 配置 | base_url / api_key / 模型下拉 / 关闭思考；"保存并获取模型"会先 PATCH 再 GET `/api/v1/llm/models` |
| 衣柜 | 下拉切换模型，成功后刷新动作列表 |
| 动作试玩 | 选动作 → 以 `high` 优先级播放 |
| 状态行 | 展示当前密钥掩码、保存结果、切换结果 |

密钥输入框保存后立即清空，界面只显示掩码提示。

## 配置注入

`config.ts` 的优先级：

```
window.__MOCHI__ {port, token}   ← Tauri IPC 注入
  > import.meta.env.VITE_SERVER_PORT / VITE_SERVER_TOKEN
  > 默认 127.0.0.1:8765
```

浏览器开发时走环境变量与 Vite proxy；桌面壳运行时由 Rust 侧注入真实端口与随机 token。

## 构建与代理

```powershell
cd mochi/frontend
npm run dev        # 5173，/api 与 /live2d 代理到 8765
npm run build      # tsc --noEmit && vite build
npm run typecheck  # 仅类型检查
npm run gen:types  # 重新生成 types/protocol.ts
```

代理在 `vite.config.ts` 中配置，改完必须重启 dev server。CSP 在 Tauri 配置里单独声明 `connect-src ws://127.0.0.1:8765`。

## 调试面板

右上角锤子按钮（`#open-debug`）打开 `DevPanel.tsx`，三块：

| 区块 | 内容 |
| --- | --- |
| 口型 | 实时 level/rms 电平表；"播放测试音频"（合成 14 音节）+ 停止 |
| 动作 | 当前播放与队列；force / high / normal 三档试触发 |
| 表情 | 选表情 + 权重；叠加 / 释放全部；显示当前权重 |

底部"运行 S2 自检"约 12s，检查 6 项并输出✓/✗与实测值：
模型加载、动作能力、待机（呼吸/微摆）、眨眼、口型振幅、动作冷却去重。
这是 S2 的可复跑验收证据（比录屏更容易回归）。

## 调试

```js
window.mochi = { client, shell, app, live2d, motion, expression, idle, gaze, lipSync, audio, cues, interaction, switchModel }
```

常用：

| 目的 | 命令 |
| --- | --- |
| 看舞台能力 | `mochi.live2d.caps` |
| 手动播动作（绕队列） | `mochi.live2d.playMotion('wedding', 'high')` |
| 走队列播动作 | `mochi.motion.request('touch_head', 'force')` |
| 读/写参数 | `mochi.live2d.getParameter('ParamMouthOpenY_SD')` |
| 手动切模型 | `await mochi.switchModel('qiye_10')` |
| 手动发消息 | `mochi.client.send('chat.user_input', {text:'你好'}, 'T1')` |

## 相关页面

- [Protocol](Protocol.md) — 消息类型
- [Live2D-Pipeline](Live2D-Pipeline.md) — 模型与渲染细节
- [Configuration](Configuration.md) — 端口与 token 从哪来
