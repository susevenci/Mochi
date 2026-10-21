# Live2D Pipeline

## 模型不入库

模型体积大（单个 17–38MB）且多来自商业游戏提取，**只放在本地** `mochi/data/live2d/`，已被 `.gitignore` 排除。仓库里只保留模型目录名。

Cubism Core（`live2dcubismcore.min.js`）同样不入库，按 [Getting-Started](Getting-Started.md) 的命令下载到 `frontend/public/vendor/`。

## 目录约定

```
mochi/data/live2d/
└─ <模型名>/
   ├─ <模型名>.model3.json      ← 扫描以此文件为锚点
   ├─ <模型名>.moc3
   ├─ physics3.json
   ├─ textures/texture_00.png
   ├─ motions/*.motion3.json    ← 可选
   └─ *.exp3.json               ← 可选
```

后端 `GET /api/v1/live2d/models` 扫描 `*/*.model3.json`，返回：

```json
{"models":[
  {"id":"qiye_10","name":"qiye_10","url":"/live2d/qiye_10/qiye_10.model3.json","motions":49,"expressions":0,
   "motion_groups":["idle","touch_head","..."],"expression_names":[],"hit_areas":[],
   "lipsync_params":["ParamMouthOpenY_SD","ParamMouthOpenY_SD2","ParamMouthOpenY2"]},
  {"id":"devil","name":"devil","url":"/live2d/devil/devil.model3.json","motions":0,"expressions":7,
   "motion_groups":[],"expression_names":["exp1","..."],"hit_areas":[],"lipsync_params":[]}
],"count":2}
```

## 角色卡 × 模型交叉校验

角色卡里的 `presentation.live2d_model` 声明想要的模型，启动时后端比对：

```powershell
GET /api/v1/live2d/binding
→ {"resolved_model":"qiye_10","model_found":true,"missing_motions":[],
   "unknown_expressions":[],"warnings":[],"ok":true}
```

判定口径：`ok = model_found && missing_motions 为空 && unknown_expressions 为空`。
`missing_motions` 的基准是 `orchestration/performance.py` 的 `EMOTION_TO_MOTION` 取值集合——
模型缺哪个动作组，就直接告诉你是谁缺（前端把这些 warnings 落到控制台）。

## 能力自适应

不同来源的模型能力差异极大，前端**按实际能力降级**，而不是假设一定有动作：

| 模型能力 | 待机 | 情绪 cue | 点击反馈 | 口型 |
| --- | --- | --- | --- | --- |
| 有 `idle` + `touch_*` | 循环 `idle` + 呼吸/眨眼/微摆 | 动作 + 表情（若声明） | `touch_head` / `touch_body` | 有 LipSync 组即驱动 |
| 只有表情 | 呼吸/眨眼/微摆 | 表情权重叠加 | 表情 | 退化到 `ParamMouthOpenY` |
| 两者都没有 | 呼吸/眨眼/微摆 | 忽略并记 debug 日志 | 忽略 | 同左 |

判断入口在 `Live2DStage.caps`（`motionGroups` / `expressions` / `mouthParamIds` / `hitAreaNames`），
`CueDispatcher` 只负责分派与兜底。`qiye_10` 没有 `HitAreas`，所以点击区域走包围盒几何分区（头 30% / 脸 15% / 其余身体）。

## 获得模型

### 方式一：从合集稀疏克隆（推荐）

```powershell
python mochi\scripts\fetch_live2d.py --name qiye_10
```

`fetch_live2d.py` 用 `--filter=blob:none` + `--no-checkout` 只拉目录树，再按需 checkout 目标目录，比逐文件下载快一个数量级。

### 方式二：选型辅助

```powershell
# 列合集
python mochi\scripts\live2d_pick.py list

# 逐级浏览（逗号分隔，模糊匹配）
python mochi\scripts\live2d_pick.py files 碧蓝航线,Azue

# 看模型能力（动作/表情/贴图/LipSync 组）
python mochi\scripts\live2d_pick.py inspect 碧蓝航线,Azue,qiye_10

# 下载贴图当预览
python mochi\scripts\live2d_pick.py preview 碧蓝航线,Azue,qiye_10 qiye.png
```

### 方式三：本地 zip（VTube Studio 模型）

```python
import zipfile
zipfile.ZipFile(src, metadata_encoding="gbk").extractall(dst)  # 中文 zip 是 GBK
```

VTube Studio 模型的特点与坑：

| 现象 | 处理 |
| --- | --- |
| 文件名是中文（`小恶魔.moc3`） | 重命名为 ASCII，避免 URL 编码问题 |
| `Expressions` 为 `None`，但磁盘有 `.exp3.json` | 手动注册进 `FileReferences.Expressions` |
| `Motions` 为空 | 无法补；靠物理 + 眨眼，或退回表情反馈 |
| 7 个 exp3 实为 `Param37/38/40…` 开关 | 是**部件/配件开关**，不是面部表情，不适合情绪映射 |

规范化后的 `model3.json` 示例：

```json
{
  "Version": 3,
  "Name": "devil",
  "FileReferences": {
    "Moc": "model.moc3",
    "Textures": ["textures/texture_00.png"],
    "Physics": "physics3.json",
    "Motions": {},
    "Expressions": [{"Name": "exp1", "File": "1.exp3.json"}]
  },
  "Groups": [{"Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen", "ParamEyeROpen"]}]
}
```

## 前端模型选择与衣柜

```
bootModel()
  ├─ GET /api/v1/live2d/models + /api/v1/live2d/binding   失败 → []，不阻塞启动
  ├─ 优先级：localStorage['mochi.live2dModel'] → 角色卡声明的模型 → 清单第一个 → 内置 MODEL_URL
  └─ live2d.load(url)
        └─ 失败 → 显示静态立绘（情绪滤镜）+ 控制台告警
```

衣柜切换（设置面板或 `window.mochi.switchModel(id)`）：

```
cues.reset() → motion.reset() → expression.reset() → idle.reset() → gaze.reset() → lipSync.detach()
  → live2d.destroy() → load(新 url) → attachControllers() + expression.load() → 写 localStorage
```

## 控制器分层

| 模块 | 职责 | 关键参数 |
| --- | --- | --- |
| `Live2DStage` | 加载/布局/参数读写/`hitTest`/帧钩子 | `caps` |
| `IdleController` | 呼吸、眨眼、身体微摆；按情绪调制幅度与节奏 | `ParamBreath`、`ParamEyeLOpen/ROpen`、`ParamBodyAngleXYZ` |
| `GazeController` | 视线跟随鼠标（150ms 平滑、±0.8 限幅、闲置自张望） | `ParamEyeBallX/Y`、`ParamAngleXYZ` |
| `MotionController` | 四级优先级队列 + 10s 冷却去重 + 8–25s 随机小动作 | 动作组 |
| `ExpressionController` | 解析 `.exp3.json`、权重叠加、300ms 缓动、自动释放 | 表情参数 |
| `LipSync` | 振幅法：RMS → 伽马校正 → 开快合慢 | `Groups.LipSync` 声明的参数 |
| `AudioPlayer` | WebAudio 播放 + `AnalyserNode`；内置合成测试音 | —— |
| `InteractionHandler` | 点击/拖拽判定、命中区上报、窗口拖动 | `interaction.event` |
| `CueDispatcher` | 把 `performance.cue` 分派到上述控制器（不推演情绪） | —— |

**帧顺序很重要**：所有参数写入都挂在 `Ticker.shared` 的 `UPDATE_PRIORITY.UTILITY`（最低）上，
比模型自身的 `NORMAL` 晚执行。否则眨眼/呼吸/口型会被 Cubism 自己的参数演算盖掉（表现为“完全不眨眼”）。

模型清单由后端扫描 `*/*.model3.json` 生成，`motions` 是该文件 `FileReferences.Motions` 下所有组的动作数之和，`expressions` 是 `Expressions` 数组长度。设置面板直接展示这两个数字，作为"这个模型能演多少"的粗略指标。

## 渲染链路

```
Live2DStage.load(url)
  ├─ Live2DModel.from(url, {autoInteract:false})
  ├─ patchPixi6Interaction(model / stage)   ← 关键兼容垫片
  ├─ anchor(0.5, 0.5) + stage.addChild
  ├─ readCapabilities()   动作组 / 表情文件 / LipSync 参数 / 命中区
  ├─ layout()   scale=1 时取 getLocalBounds()，按 min(w/bw, h/bh)*0.94 缩放
  └─ 后续由 attachControllers() 接管：idle/gaze/motion/lipSync/expression 各自挂帧钩子

CueDispatcher.dispatch(cue)
  ├─ idle.setEmotion(label)                 ← 情绪化待机
  ├─ motion.request(cue.motion, priority)   ← 队列 + 冷却
  └─ expression.play(cue.expression ?? label, 1, {autoReleaseMs})
```

## 踩坑记录

| 问题 | 根因 | 修法 |
| --- | --- | --- |
| 单会话 1500+ `currentTarget.isInteractive is not a function` | `pixi-live2d-display@0.4` 面向 pixi 6，事件系统仍调 `isInteractive()` | 给 model 与 stage 补 `isInteractive = () => false` |
| 缩放异常（模型过大/过小） | `internalModel.width` 单位与 `model.width` 不一致 | 改 `scale=1` + `getLocalBounds()` |
| 加载后静止不动 | 只加载未播动作 | `MotionController.attach()` 播 `idle` |
| 写了眨眼参数但模型不眨 | 帧钩子优先级高于模型自身 | 挂到 `UPDATE_PRIORITY.UTILITY`（最后执行） |
| 口型永远是 0 | `AudioContext` 懒创建，接线时拿到 `null` | `AudioPlayer.prepare()` + LipSync 用解析器每帧重取 analyser |
| 同一动作连点两下都放行 | 冷却在 `await startMotion()` 之后才写入 | 在 `await` 前同步占位 + `pending` 集合 |
| Add 类表情参数两帧就打满 | 每帧拿 `getParameter()` 当基底，而 Cubism 不重置无人驱动的参数 | 底值快照 + 每帧只写一次终值，释放时回写底值 |
| `renderer.plugins.interaction has been deprecated` | 库内部调用 pixi 6 旧接口 | 无害警告，忽略 |
| 中文路径 404 | URL 未编码 / 文件名非 ASCII | 统一 ASCII 命名 |
| 模型加载成功但看不到 | 需要看 `[live2d] bounds=... scale=... pos=...` | 按日志判断缩放/位置，而非猜测 |

## 表情与口型的现实约束

- 碧蓝航线系模型**普遍没有 `.exp3.json`**，情绪表现只能靠动作组
- `devil` 这类 VTube 模型的 exp3 是部件开关（`Param37/38/40…`），语义不是情绪，但仍可验证“权重叠加 + 缓动”
- 因此 S3 的 `expression_map` 应改为 **action_map 优先 + 参数兜底**
- 口型在 S2 已用**振幅法**跑通（固定合成测试音）；S4 接 TTS 时只需把音频喂给 `AudioPlayer.playBuffer()`，`LipSync` 不用改

## 相关页面

- [Emotion-Engine](Emotion-Engine.md) — 情绪标签从哪来
- [Frontend](Frontend.md) — 前端整体结构
- [Troubleshooting](Troubleshooting.md) — 黑屏、缩放、兼容报错

