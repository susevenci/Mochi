import { Application } from 'pixi.js';
import { resolveConfig } from './config';
import { AudioPlayer } from './live2d/AudioPlayer';
import { CueDispatcher, type CueInput } from './live2d/CueDispatcher';
import { ExpressionController } from './live2d/ExpressionController';
import { GazeController } from './live2d/GazeController';
import { IdleController } from './live2d/IdleController';
import { InteractionHandler, type TapArea } from './live2d/InteractionHandler';
import { LipSync } from './live2d/LipSync';
import { Live2DStage } from './live2d/Live2DStage';
import { MotionController } from './live2d/MotionController';
import { WSClient, type ConnectionStatus } from './net/WSClient';
import { ulid } from './net/ulid';
import { detectShell } from './shell/detect';
import type { Envelope } from './types/protocol';
import { mountDevPanel } from './ui/DevPanel';
import {
  ingestEmotion,
  loadEmotionHistory,
  type EmotionSnapshot,
} from './ui/emotionStore';
import { mountSettingsPanel } from './ui/SettingsPanel';

const stageEl = document.querySelector<HTMLDivElement>('#stage');
const statusEl = document.querySelector<HTMLSpanElement>('#status');
const logEl = document.querySelector<HTMLDivElement>('#chat-log');
const formEl = document.querySelector<HTMLFormElement>('#chat-form');
const inputEl = document.querySelector<HTMLInputElement>('#chat-input');
const sendEl = document.querySelector<HTMLButtonElement>('#chat-send');
const fallbackEl = document.querySelector<HTMLImageElement>('#fallback-portrait');

if (!stageEl || !statusEl || !logEl || !formEl || !inputEl || !sendEl || !fallbackEl) {
  throw new Error('missing required DOM nodes');
}

const dom = {
  stage: stageEl,
  status: statusEl,
  log: logEl,
  form: formEl,
  input: inputEl,
  send: sendEl,
  fallback: fallbackEl,
};

const shell = detectShell();
const config = resolveConfig();
const apiHeaders: Record<string, string> = config.token
  ? { 'X-Mochi-Token': config.token }
  : {};

/** 开发期经 Vite proxy 到后端 /live2d；模型本地存放，不入库 */
const MODEL_URL = '/live2d/qiye_10/qiye_10.model3.json';
const MODEL_STORAGE_KEY = 'mochi.live2dModel';

interface Live2DModelInfo {
  id: string;
  name: string;
  url: string;
  motions: number;
  expressions: number;
  motion_groups?: string[];
  expression_names?: string[];
  hit_areas?: string[];
}

interface BindingReport {
  character_id: string;
  character_name: string;
  declared_model: string | null;
  resolved_model: string | null;
  model_found: boolean;
  missing_motions: string[];
  warnings: string[];
  ok: boolean;
}

async function fetchModels(): Promise<Live2DModelInfo[]> {
  try {
    const response = await fetch('/api/v1/live2d/models', { headers: apiHeaders });
    if (!response.ok) return [];
    const data = (await response.json()) as { models: Live2DModelInfo[] };
    return data.models;
  } catch (error) {
    console.warn('[live2d] 模型清单获取失败:', error);
    return [];
  }
}

/** 角色卡 × 模型交叉校验（T2-13）：启动时拿一次，用于选择默认模型与告警 */
async function fetchBinding(): Promise<BindingReport | null> {
  try {
    const response = await fetch('/api/v1/live2d/binding', { headers: apiHeaders });
    if (!response.ok) return null;
    return (await response.json()) as BindingReport;
  } catch (error) {
    console.warn('[live2d] 绑定校验获取失败:', error);
    return null;
  }
}

// 透明背景是"桌宠悬浮"的物理前提（计划书 5.7.2）
const app = new Application({
  antialias: true,
  resizeTo: window,
});
app.renderer.background.alpha = 0;
const canvas = app.view as unknown as HTMLCanvasElement;
dom.stage.appendChild(canvas);

const live2d = new Live2DStage(app);
const motion = new MotionController(live2d);
const expression = new ExpressionController(live2d);
const idle = new IdleController(live2d);
const gaze = new GazeController(live2d);
const lipSync = new LipSync(live2d);
const audio = new AudioPlayer();
const cues = new CueDispatcher(motion, expression, idle, live2d);

/** 模型加载失败/切换失败时的兜底：静态立绘 + 情绪滤镜，绝不白屏 */
function showFallback(reason: string): void {
  dom.fallback.hidden = false;
  console.warn('[live2d] 使用静态立绘兜底:', reason);
}

function hideFallback(): void {
  dom.fallback.hidden = true;
}

/** 模型就绪后统一接线：控制器 + 表情解析 + 口型参数 */
async function attachControllers(mouthParamIds: string[]): Promise<void> {
  idle.attach();
  gaze.attach();
  motion.attach();
  // 先建好音频图：AnalyserNode 是口型信号源，晚建一步口型就永远是 0
  audio.prepare();
  lipSync.attach(mouthParamIds, () => audio.analyser);
  if (mouthParamIds.length === 0) {
    console.warn('[lipsync] 模型没有嘴部参数，口型通道不可用');
  }
}

async function bootModel(): Promise<void> {
  const [models, binding] = await Promise.all([fetchModels(), fetchBinding()]);
  const saved = localStorage.getItem(MODEL_STORAGE_KEY);
  const preferred = saved ?? binding?.resolved_model ?? null;
  const chosen = models.find((item) => item.id === preferred) ?? models[0];
  const url = chosen?.url ?? MODEL_URL;

  if (binding && !binding.ok) {
    console.warn('[live2d] 角色卡/模型校验告警:', binding.warnings, binding.missing_motions);
  }

  try {
    const caps = await live2d.load(url);
    hideFallback();
    if (chosen) {
      localStorage.setItem(MODEL_STORAGE_KEY, chosen.id);
    }
    await attachControllers(caps.mouthParamIds);
    await expression.load(caps.expressions);
    console.info('[live2d] model loaded:', url);
  } catch (error) {
    showFallback(String(error));
  }
}

/** 衣柜：切换模型（销毁旧的再加载，失败时回退静态立绘）。 */
async function switchModel(id: string): Promise<boolean> {
  const models = await fetchModels();
  const target = models.find((item) => item.id === id);
  if (!target) {
    console.warn('[live2d] 未找到模型:', id);
    return false;
  }
  cues.reset();
  motion.reset();
  expression.reset();
  idle.reset();
  gaze.reset();
  lipSync.detach();
  live2d.destroy();
  try {
    const caps = await live2d.load(target.url);
    hideFallback();
    localStorage.setItem(MODEL_STORAGE_KEY, id);
    await attachControllers(caps.mouthParamIds);
    await expression.load(caps.expressions);
    console.info('[live2d] 已切换模型:', id);
    return true;
  } catch (error) {
    console.error('[live2d] 切换模型失败:', error);
    showFallback(String(error));
    return false;
  }
}

window.addEventListener('resize', () => {
  live2d.layout();
});

// 视线跟随：鼠标在哪，眼睛就看向哪（窗口坐标系）
window.addEventListener('pointermove', (event) => {
  gaze.lookAt(
    { x: event.clientX, y: event.clientY },
    { width: window.innerWidth, height: window.innerHeight },
  );
});

// ── 交互：点击反应 + 拖拽窗口 + interaction.event 上报（T2-08 / T2-09）──
const TAP_MOTIONS: Record<TapArea, string> = {
  head: 'touch_head',
  face: 'touch_special',
  body: 'touch_body',
};

const interaction = new InteractionHandler({
  canvas,
  stage: live2d,
  shell,
  onTap: (area) => {
    dom.input.focus();
    if (!live2d.isReady) return;
    motion.request(TAP_MOTIONS[area], 'high');
  },
  onDragStart: () => {
    if (!live2d.isReady) return;
    motion.request('touch_drag2', 'high');
  },
  onDragEnd: () => {
    motion.backToIdle();
    void persistWindowPosition();
  },
  report: (event) => {
    client.send('interaction.event', {
      type: event.type,
      area: event.area,
      count: event.count,
      x: event.x,
      y: event.y,
    });
  },
});

// ── 窗口位置记忆（计划书 5.6.6 / 9.2.3）──
interface StoredWindowPosition {
  x: number;
  y: number;
  display?: string | null;
}

async function restoreWindowPosition(): Promise<void> {
  if (!shell.isDesktop) return;
  try {
    const response = await fetch('/api/v1/config/user', { headers: apiHeaders });
    if (!response.ok) return;
    const data = (await response.json()) as { window?: { position?: StoredWindowPosition | null } };
    const position = data.window?.position;
    if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) {
      await shell.setPosition(position.x, position.y);
      console.info('[window] 恢复位置', position);
    }
  } catch (error) {
    console.warn('[window] 位置恢复失败:', error);
  }
}

async function persistWindowPosition(): Promise<void> {
  if (!shell.isDesktop) return;
  try {
    const position = await shell.getPosition();
    await fetch('/api/v1/config/user', {
      method: 'PATCH',
      headers: { ...apiHeaders, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        window: {
          position: {
            x: position.x,
            y: position.y,
            display: position.display ?? null,
            scale: position.scale ?? 1,
          },
        },
      }),
    });
    console.info('[window] 已保存位置', position);
  } catch (error) {
    console.warn('[window] 位置保存失败:', error);
  }
}

const statusText: Record<ConnectionStatus, string> = {
  connecting: 'connecting',
  open: 'connected',
  closed: 'reconnecting',
};

const client = new WSClient({
  url: config.wsUrl,
  token: config.token,
  onStatus: (status) => {
    dom.status.dataset.state = status;
    dom.status.textContent = statusText[status];
  },
});

client.on('sys.hello_ack', (envelope: Envelope) => {
  const payload = envelope.payload as {
    server_version?: unknown;
    emotion?: EmotionSnapshot | null;
  };
  console.info('[mochi] backend ready', payload);
  dom.status.textContent = `ready v${String(payload.server_version ?? '?')}`;
  if (payload.emotion) {
    ingestEmotion(payload.emotion);
    dom.fallback.dataset.emotion = payload.emotion.label ?? 'neutral';
    if (payload.emotion.pending_greeting) {
      void showPendingGreeting();
    }
  }
});

// 情绪快照（I1：后端唯一权威；前端只缓存与呈现）
client.on('emotion.update', (envelope: Envelope) => {
  const snapshot = envelope.payload as unknown as EmotionSnapshot;
  if (!snapshot?.pad) return;
  ingestEmotion(snapshot);
  dom.fallback.dataset.emotion = snapshot.label ?? 'neutral';
});

// 主动搭话：文案由后端角色卡模板给出，前端不自行生成
client.on('proactive.speak', (envelope: Envelope) => {
  const payload = envelope.payload as {
    text?: string;
    emotion_label?: string;
  };
  if (!payload.text) return;
  dom.fallback.dataset.emotion = payload.emotion_label ?? 'lonely';
  if (live2d.isReady) {
    cues.dispatch({ emotion_label: payload.emotion_label ?? 'lonely' });
  }
  const bubble = appendBubble('assistant', payload.text);
  const tag = document.createElement('span');
  tag.className = 'emotion-tag';
  tag.textContent = payload.emotion_label ?? 'lonely';
  bubble.appendChild(tag);
});

client.on('sys.error', (envelope: Envelope) => {
  console.warn('[mochi] server error', envelope.payload);
});

// ── 表现指令（S2）：情绪 → 动作/表情/待机节奏 ──
client.on('performance.cue', (envelope: Envelope) => {
  const cue = envelope.payload as CueInput;
  console.info('[live2d] cue', cue);
  dom.fallback.dataset.emotion = cue.emotion_label ?? 'neutral';
  if (!live2d.isReady) return;
  cues.dispatch(cue);
});

// ── 对话 UI（S1）──
let currentTurn: string | null = null;
let currentBubble: HTMLElement | null = null;

function appendBubble(role: 'user' | 'assistant' | 'error', text = ''): HTMLElement {
  const bubble = document.createElement('div');
  bubble.className = `bubble ${role}`;
  bubble.textContent = text;
  dom.log.appendChild(bubble);
  dom.log.scrollTop = dom.log.scrollHeight;
  return bubble;
}

let greetingShown = false;

/** 离线重逢开场白：取走后立即落库，避免重连时反复播放。 */
async function showPendingGreeting(): Promise<void> {
  if (greetingShown) return;
  greetingShown = true;
  try {
    const response = await fetch('/api/v1/emotion/greeting/consume', {
      method: 'POST',
      headers: apiHeaders,
    });
    if (!response.ok) return;
    const data = (await response.json()) as { greeting?: string | null; text?: string | null };
    if (!data.text) return;
    const bubble = appendBubble('assistant', data.text);
    const tag = document.createElement('span');
    tag.className = 'emotion-tag';
    tag.textContent = data.greeting ?? 'reunion';
    bubble.appendChild(tag);
  } catch (error) {
    console.warn('[emotion] greeting consume failed', error);
  }
}

async function loadEmotionHistoryFromApi(): Promise<void> {
  try {
    const response = await fetch('/api/v1/emotion/history?limit=600', {
      headers: apiHeaders,
    });
    if (!response.ok) return;
    const data = (await response.json()) as { history?: EmotionSnapshot[] };
    if (data.history) loadEmotionHistory(data.history);
  } catch (error) {
    console.warn('[emotion] history load failed', error);
  }
}

function setBusy(busy: boolean): void {
  dom.send.disabled = busy;
  dom.input.disabled = busy;
}

function sendCurrent(): void {
  const text = dom.input.value.trim();
  if (!text || currentTurn) return;
  appendBubble('user', text);
  dom.input.value = '';
  currentTurn = ulid();
  // 先占位，首字到达时替换，减少"没反应"的错觉
  currentBubble = appendBubble('assistant', '…');
  currentBubble.classList.add('typing');
  setBusy(true);
  client.send('chat.user_input', { text }, currentTurn);
}

dom.form.addEventListener('submit', (event) => {
  event.preventDefault();
  sendCurrent();
});

window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && currentTurn) {
    client.send('chat.interrupt', { reason: 'user' }, currentTurn);
  }
});

client.on('chat.agent_delta', (envelope: Envelope) => {
  if (!currentTurn || envelope.turn_id !== currentTurn) return;
  const payload = envelope.payload as { delta?: string };
  if (!payload.delta) return;
  if (!currentBubble) {
    currentBubble = appendBubble('assistant');
  } else if (currentBubble.classList.contains('typing')) {
    currentBubble.classList.remove('typing');
    currentBubble.textContent = '';
  }
  currentBubble.textContent = `${currentBubble.textContent ?? ''}${payload.delta}`;
  dom.log.scrollTop = dom.log.scrollHeight;
});

client.on('chat.agent_final', (envelope: Envelope) => {
  if (!currentTurn || envelope.turn_id !== currentTurn) return;
  const payload = envelope.payload as {
    text?: string;
    error?: string | null;
    emotion?: { label?: string } | null;
  };
  if (payload.text && !currentBubble) {
    currentBubble = appendBubble('assistant', payload.text);
  } else if (payload.text && currentBubble) {
    currentBubble.classList.remove('typing');
    currentBubble.textContent = payload.text;
  }
  if (payload.error && payload.error !== 'TURN_CANCELLED') {
    appendBubble('error', `（${payload.error}）`);
  }
  if (payload.emotion?.label && currentBubble) {
    const tag = document.createElement('span');
    tag.className = 'emotion-tag';
    tag.textContent = payload.emotion.label;
    currentBubble.appendChild(tag);
  }
  currentTurn = null;
  currentBubble = null;
  setBusy(false);
  dom.input.focus();
});

dom.input.focus();
client.connect();
void restoreWindowPosition();
void loadEmotionHistoryFromApi();
// 模型就绪后再显示窗口，避免白闪（Tauri 下窗口以 visible=false 启动）
void bootModel().finally(() => {
  void shell.show().catch((error: unknown) => {
    console.warn('[shell] show 失败:', error);
  });
});

// ── 配置面板与调试面板 ──
// 两个面板都是全屏遮罩：打开一个前先卸掉另一个，否则右上角按钮点不到
let unmountSettings: (() => void) | null = null;
let unmountDebug: (() => void) | null = null;

function closeSettings(): void {
  unmountSettings?.();
  unmountSettings = null;
}

function closeDebug(): void {
  unmountDebug?.();
  unmountDebug = null;
}

const settingsBtn = document.querySelector<HTMLButtonElement>('#open-settings');
const settingsRoot = document.querySelector<HTMLDivElement>('#settings-root');
settingsBtn?.addEventListener('click', (event) => {
  event.stopPropagation();
  if (!settingsRoot) {
    console.warn('[settings] #settings-root 不存在');
    return;
  }
  try {
    closeDebug();
    unmountSettings = mountSettingsPanel(settingsRoot);
    console.info('[settings] 面板已挂载');
  } catch (error) {
    console.error('[settings] 面板挂载失败:', error);
  }
});

const debugBtn = document.querySelector<HTMLButtonElement>('#open-debug');
const debugRoot = document.querySelector<HTMLDivElement>('#debug-root');
debugBtn?.addEventListener('click', (event) => {
  event.stopPropagation();
  if (!debugRoot) {
    console.warn('[debug] #debug-root 不存在');
    return;
  }
  closeSettings();
  unmountDebug = mountDevPanel(debugRoot);
});

// 开发期调试句柄（不承载业务逻辑）
(window as unknown as { mochi: unknown }).mochi = {
  client,
  shell,
  app,
  live2d,
  motion,
  expression,
  idle,
  gaze,
  lipSync,
  audio,
  cues,
  interaction,
  presenter: cues,
  switchModel,
};
