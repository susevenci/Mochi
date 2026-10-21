import type { Envelope } from '../types/protocol';
import { ulid } from './ulid';

export type ConnectionStatus = 'connecting' | 'open' | 'closed';
export type EnvelopeHandler = (envelope: Envelope) => void;

export interface WSClientOptions {
  url: string;
  token?: string;
  heartbeatMs?: number;
  onStatus?: (status: ConnectionStatus) => void;
}

/** 指数退避：1s → 2s → 4s → … → 30s（计划书 6.1 重连约定）。 */
const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];

export class WSClient {
  private socket: WebSocket | null = null;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private attempt = 0;
  private disposed = false;
  private readonly handlers = new Map<string, Set<EnvelopeHandler>>();
  private readonly anyHandlers = new Set<EnvelopeHandler>();

  constructor(private readonly options: WSClientOptions) {}

  connect(): void {
    if (this.disposed || this.socket) return;
    this.options.onStatus?.('connecting');

    const url = this.options.token
      ? `${this.options.url}?token=${encodeURIComponent(this.options.token)}`
      : this.options.url;
    const socket = new WebSocket(url);
    this.socket = socket;

    socket.onopen = () => {
      this.attempt = 0;
      this.options.onStatus?.('open');
      this.startHeartbeat();
      // 握手即拉取全量状态（计划书 6.1）
      this.send('sys.hello', {});
    };
    socket.onmessage = (event) => this.handleMessage(event);
    socket.onclose = () => {
      this.stopHeartbeat();
      this.socket = null;
      this.options.onStatus?.('closed');
      this.scheduleReconnect();
    };
    socket.onerror = () => {
      socket.close();
    };
  }

  disconnect(): void {
    this.disposed = true;
    this.clearReconnect();
    this.stopHeartbeat();
    this.socket?.close();
    this.socket = null;
  }

  send(type: string, payload: Record<string, unknown> = {}, turnId?: string): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    const envelope: Envelope = { v: 1, type, id: ulid(), ts: Date.now() / 1000, payload };
    if (turnId) envelope.turn_id = turnId;
    this.socket.send(JSON.stringify(envelope));
  }

  on(type: string, handler: EnvelopeHandler): () => void {
    const set = this.handlers.get(type) ?? new Set<EnvelopeHandler>();
    set.add(handler);
    this.handlers.set(type, set);
    return () => set.delete(handler);
  }

  onAny(handler: EnvelopeHandler): () => void {
    this.anyHandlers.add(handler);
    return () => this.anyHandlers.delete(handler);
  }

  private handleMessage(event: MessageEvent): void {
    let envelope: Envelope;
    try {
      envelope = JSON.parse(String(event.data)) as Envelope;
    } catch {
      console.warn('[ws] 收到非 JSON 消息，已忽略');
      return;
    }
    if (typeof envelope?.type !== 'string') return;
    this.anyHandlers.forEach((handler) => handler(envelope));
    this.handlers.get(envelope.type)?.forEach((handler) => handler(envelope));
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    const ms = this.options.heartbeatMs ?? 20_000;
    this.heartbeat = setInterval(() => this.send('sys.ping', { ts: Date.now() / 1000 }), ms);
  }

  private stopHeartbeat(): void {
    if (this.heartbeat !== null) {
      clearInterval(this.heartbeat);
      this.heartbeat = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.disposed) return;
    const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)];
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private clearReconnect(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}
