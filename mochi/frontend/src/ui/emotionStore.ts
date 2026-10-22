import type { EmotionUpdatePayload } from '../types/protocol';

/**
 * 前端只缓存后端快照（不变量 I1）：DevPanel 的曲线与时间轴全部来自
 * ``emotion.update`` / ``hello_ack`` / 历史接口，绝不自行插值或推测情绪。
 */
export type EmotionSnapshot = EmotionUpdatePayload;

type Listener = (snapshot: EmotionSnapshot | null, points: readonly EmotionSnapshot[]) => void;

const MAX_POINTS = 900;
let current: EmotionSnapshot | null = null;
let points: EmotionSnapshot[] = [];
const listeners = new Set<Listener>();

function timestamp(snapshot: EmotionSnapshot): number {
  return Number(snapshot.ts ?? 0);
}

function notify(): void {
  for (const listener of listeners) {
    listener(current, points);
  }
}

function trim(): void {
  if (points.length > MAX_POINTS) {
    points = points.slice(-MAX_POINTS);
  }
}

export function ingestEmotion(snapshot: EmotionSnapshot): void {
  if (!snapshot?.pad) return;
  current = snapshot;
  const ts = timestamp(snapshot);
  const last = points[points.length - 1];
  if (last && timestamp(last) === ts) {
    points[points.length - 1] = snapshot;
  } else {
    points.push(snapshot);
  }
  trim();
  notify();
}

export function loadEmotionHistory(history: EmotionSnapshot[]): void {
  const valid = history.filter((item) => item?.pad);
  if (valid.length === 0) return;
  points = [...valid].sort((a, b) => timestamp(a) - timestamp(b));
  trim();
  current = points[points.length - 1] ?? null;
  notify();
}

export function getEmotionSnapshot(): EmotionSnapshot | null {
  return current;
}

export function getEmotionPoints(): readonly EmotionSnapshot[] {
  return points;
}

export function subscribeEmotion(listener: Listener): () => void {
  listeners.add(listener);
  listener(current, points);
  return () => {
    listeners.delete(listener);
  };
}
