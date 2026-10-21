import { Application, Graphics } from 'pixi.js';
import { resolveConfig } from './config';
import { EmotionPresenter } from './live2d/EmotionPresenter';
import { Live2DStage } from './live2d/Live2DStage';
import { WSClient, type ConnectionStatus } from './net/WSClient';
import { ulid } from './net/ulid';
import { detectShell } from './shell/detect';
import type { Envelope } from './types/protocol';
import { mountSettingsPanel } from './ui/SettingsPanel';

const stageEl = document.querySelector<HTMLDivElement>('#stage');
const statusEl = document.querySelector<HTMLSpanElement>('#status');
const logEl = document.querySelector<HTMLDivElement>('#chat-log');
const formEl = document.querySelector<HTMLFormElement>('#chat-form');
const inputEl = document.querySelector<HTMLInputElement>('#chat-input');
const sendEl = document.querySelector<HTMLButtonElement>('#chat-send');

if (!stageEl || !statusEl || !logEl || !formEl || !inputEl || !sendEl) {
  throw new Error('missing required DOM nodes');
}

const dom = { stage: stageEl, status: statusEl, log: logEl, form: formEl, input: inputEl, send: sendEl };

const shell = detectShell();
const config = resolveConfig();

/** 开发期经 Vite proxy 到后端 /live2d；模型本地存放，不入库 */
const MODEL_URL = '/live2d/qiye_10/qiye_10.model3.json';
const MODEL_STORAGE_KEY = 'mochi.live2dModel';

interface Live2DModelInfo {
  id: string;
  name: string;
  url: string;
  motions: number;
  expressions: number;
}

async function loadAvatarModels(): Promise<Live2DModelInfo[]> {
  const headers: Record<string, string> = {};
  if (config.token) {
    headers['X-Mochi-Token'] = config.token;
  }
  try {
    const response = await fetch('/api/v1/live2d/models', { headers });
    if (!response.ok) {
      return [];
    }
    const data = (await response.json()) as { models: Live2DModelInfo[] };
    return data.models;
  } catch (error) {
    console.warn('[live2d] 模型清单获取失败:', error);
    return [];
  }
}

// 透明背景是"桌宠悬浮"的物理前提（计划书 5.7.2）
const app = new Application({
  antialias: true,
  resizeTo: window,
});
app.renderer.background.alpha = 0;
dom.stage.appendChild(app.view as unknown as HTMLCanvasElement);

// 模型加载失败时的兜底占位（计划书 5.6.7）
const fallback = new Graphics();
fallback.beginFill(0xf3b6b6, 0.92).drawCircle(0, 0, 64).endFill();
fallback.visible = false;
app.stage.addChild(fallback);

const live2d = new Live2DStage(app);
const presenter = new EmotionPresenter(live2d);

let speakingUntil = 0;

app.ticker.add(() => {
  const { width, height } = app.screen;
  fallback.position.set(width / 2, height / 2);
  if (fallback.visible) {
    fallback.rotation += 0.004;
  }
  const now = performance.now();
  fallback.scale.set(now < speakingUntil ? 1 + Math.sin(now / 90) * 0.05 : 1);
});

async function bootModel(): Promise<void> {
  const models = await loadAvatarModels();
  const saved = localStorage.getItem(MODEL_STORAGE_KEY);
  const chosen = models.find((item) => item.id === saved) ?? models[0];
  const url = chosen?.url ?? MODEL_URL;
  try {
    await live2d.load(url);
    if (chosen) {
      localStorage.setItem(MODEL_STORAGE_KEY, chosen.id);
    }
    console.info('[live2d] model loaded:', url);
  } catch (error) {
    console.warn('[live2d] 模型加载失败，回退占位圆:', error);
    fallback.visible = true;
  }
}

/** 衣柜：切换模型（销毁旧的再加载，失败时回退占位圆）。 */
async function switchModel(id: string): Promise<boolean> {
  const models = await loadAvatarModels();
  const target = models.find((item) => item.id === id);
  if (!target) {
    console.warn('[live2d] 未找到模型:', id);
    return false;
  }
  presenter.reset();
  live2d.destroy();
  try {
    await live2d.load(target.url);
    fallback.visible = false;
    localStorage.setItem(MODEL_STORAGE_KEY, id);
    console.info('[live2d] 已切换模型:', id);
    return true;
  } catch (error) {
    console.error('[live2d] 切换模型失败:', error);
    fallback.visible = true;
    return false;
  }
}

window.addEventListener('resize', () => {
  live2d.layout();
});

void bootModel();

// 点击角色：聚焦输入框 + 播放摸头/戳身体反应
(app.view as unknown as HTMLCanvasElement).addEventListener('pointerdown', (event) => {
  dom.input.focus();
  const canvas = app.view as unknown as HTMLCanvasElement;
  const rect = canvas.getBoundingClientRect();
  const relativeY = rect.height > 0 ? (event.clientY - rect.top) / rect.height : 0.5;
  live2d.reactToTap(relativeY);
});

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
  const payload = envelope.payload as { server_version?: unknown };
  console.info('[mochi] backend ready', payload);
  dom.status.textContent = `ready v${String(payload.server_version ?? '?')}`;
});

client.on('sys.error', (envelope: Envelope) => {
  console.warn('[mochi] server error', envelope.payload);
});

// ── 表现指令（S2）：情绪 → Live2D 动作 ──
client.on('performance.cue', (envelope: Envelope) => {
  const cue = envelope.payload as { motion?: string; priority?: string; emotion_label?: string };
  console.info('[live2d] cue', cue);
  if (!live2d.isReady) return;
  presenter.apply(cue);
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
  speakingUntil = performance.now() + 160;
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
  speakingUntil = 0;
  setBusy(false);
  dom.input.focus();
});

dom.input.focus();
client.connect();

// ── LLM 配置面板（可热切换模型服务）──
const settingsBtn = document.querySelector<HTMLButtonElement>('#open-settings');
const settingsRoot = document.querySelector<HTMLDivElement>('#settings-root');
settingsBtn?.addEventListener('click', (event) => {
  event.stopPropagation();
  if (!settingsRoot) {
    console.warn('[settings] #settings-root 不存在');
    return;
  }
  try {
    mountSettingsPanel(settingsRoot);
    console.info('[settings] 面板已挂载');
  } catch (error) {
    console.error('[settings] 面板挂载失败:', error);
  }
});

// 开发期调试句柄（不承载业务逻辑）
(window as unknown as { mochi: unknown }).mochi = {
  client,
  shell,
  app,
  live2d,
  presenter,
  switchModel,
};
