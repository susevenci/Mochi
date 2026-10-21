import { Application, Graphics } from 'pixi.js';
import { resolveConfig } from './config';
import { WSClient, type ConnectionStatus } from './net/WSClient';
import { ulid } from './net/ulid';
import { detectShell } from './shell/detect';
import type { Envelope } from './types/protocol';

const stageEl = document.querySelector<HTMLDivElement>('#stage');
const statusEl = document.querySelector<HTMLSpanElement>('#status');
const logEl = document.querySelector<HTMLDivElement>('#chat-log');
const formEl = document.querySelector<HTMLFormElement>('#chat-form');
const inputEl = document.querySelector<HTMLInputElement>('#chat-input');
const sendEl = document.querySelector<HTMLButtonElement>('#chat-send');

if (!stageEl || !statusEl || !logEl || !formEl || !inputEl || !sendEl) {
  throw new Error('missing required DOM nodes');
}

// 收窄后集中持有，避免闭包内丢失非空推断
const dom = { stage: stageEl, status: statusEl, log: logEl, form: formEl, input: inputEl, send: sendEl };

const shell = detectShell();
const config = resolveConfig();

// 透明背景是"桌宠悬浮"的物理前提（计划书 5.7.2）
const app = new Application({
  antialias: true,
  resizeTo: window,
});
// 用 renderer.background.alpha 而非 backgroundAlpha（后者在 pixi 7.4 已标记废弃）
app.renderer.background.alpha = 0;
dom.stage.appendChild(app.view as unknown as HTMLCanvasElement);

// S0/S1 的占位圆：验证渲染管线；S2 替换为 Live2DStage
const placeholder = new Graphics();
placeholder.beginFill(0xf3b6b6, 0.92).drawCircle(0, 0, 64).endFill();
app.stage.addChild(placeholder);

// 说话时的时间窗口：用于让占位角色有"正在回应"的最小反馈
let speakingUntil = 0;

app.ticker.add(() => {
  const { width, height } = app.screen;
  placeholder.position.set(width / 2, height / 2);
  placeholder.rotation += 0.004;
  const now = performance.now();
  const pulse = now < speakingUntil ? 1 + Math.sin(now / 90) * 0.05 : 1;
  placeholder.scale.set(pulse);
});

// 点击角色聚焦输入框（S2 会替换为 Live2D 的 hitTest 交互）
(app.view as unknown as HTMLCanvasElement).addEventListener('pointerdown', () => {
  dom.input.focus();
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

// ── 对话 UI（T1-10）──
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
  currentBubble = null;
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

// 开发期调试句柄（不承载业务逻辑）
(window as unknown as { mochi: unknown }).mochi = { client, shell, app };
