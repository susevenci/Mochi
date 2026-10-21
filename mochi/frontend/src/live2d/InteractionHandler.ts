import type { ShellAdapter } from '../shell/ShellAdapter';
import type { Live2DStage } from './Live2DStage';

/** 点击区域（计划书 5.6.6 的三种命中区） */
export type TapArea = 'head' | 'face' | 'body';

/** 区域 → 上报给后端的情感刺激标签（StimulusTag） */
const AREA_TO_STIMULUS: Record<TapArea, string> = {
  head: 'pat_head',
  face: 'touch_face',
  body: 'poke_body',
};

/** 拖动判定阈值：超过 6px 才算拖拽，否则视为点击（计划书 5.6.6） */
const DRAG_THRESHOLD_PX = 6;
/** 单次按住的时长上限：超过就不算"点击"了 */
const TAP_MAX_MS = 5000;
/** 反复戳判定窗口与其阈值 */
const TEASE_WINDOW_MS = 10_000;
const TEASE_THRESHOLD = 10;

export interface InteractionEvent {
  type: string;
  area: TapArea | 'drag';
  /** 同一个区域 10s 内的累计次数（后端 S3 用它做 habituation） */
  count: number;
  x: number;
  y: number;
}

export interface InteractionHandlerOptions {
  canvas: HTMLCanvasElement;
  stage: Live2DStage;
  shell: ShellAdapter;
  /** 点击命中区域后的表现回调（播动作/表情） */
  onTap?: (area: TapArea) => void;
  /** 开始/结束拖拽（用于播"挣扎"动作、保存窗口位置） */
  onDragStart?: () => void;
  onDragEnd?: () => void;
  /** 上报 interaction.event；没有 WS 连接时传 undefined 也能工作 */
  report?: (event: InteractionEvent) => void;
}

function areaFromHitArea(name: string): TapArea | null {
  const lower = name.toLowerCase();
  if (lower.includes('head')) return 'head';
  if (lower.includes('face')) return 'face';
  if (lower.includes('body') || lower.includes('arm') || lower.includes('hand')) return 'body';
  return null;
}

/**
 * 交互处理（计划书 5.6.6）：hitTest 命中区域 → interaction.event 上报；
 * 点击 vs 拖拽判定 → ``startDragging()`` 移动窗口。
 *
 * 模型没定义 ``HitAreas`` 时（qiye_10 就是这种）用包围盒几何分区兜底：
 * 上 30% 算头、30%~45% 算脸、其余算身体——保证"点了有反应"。
 */
export class InteractionHandler {
  private readonly canvas: HTMLCanvasElement;
  private readonly stage: Live2DStage;
  private readonly shell: ShellAdapter;
  private readonly options: InteractionHandlerOptions;
  private readonly tapHistory = new Map<TapArea, number[]>();

  private pressed = false;
  private dragging = false;
  private startX = 0;
  private startY = 0;
  private startAt = 0;
  private pressArea: TapArea | null = null;

  constructor(options: InteractionHandlerOptions) {
    this.options = options;
    this.canvas = options.canvas;
    this.stage = options.stage;
    this.shell = options.shell;
    this.canvas.addEventListener('pointerdown', this.handlePointerDown);
    window.addEventListener('pointermove', this.handlePointerMove);
    window.addEventListener('pointerup', this.handlePointerUp);
  }

  detach(): void {
    this.canvas.removeEventListener('pointerdown', this.handlePointerDown);
    window.removeEventListener('pointermove', this.handlePointerMove);
    window.removeEventListener('pointerup', this.handlePointerUp);
  }

  /** 由 main 在 pointermove 时调用，避免重复绑定 */
  static normalize(event: PointerEvent): { x: number; y: number } {
    return { x: event.clientX, y: event.clientY };
  }

  private handlePointerDown = (event: PointerEvent): void => {
    if (event.button !== 0) return;
    this.pressed = true;
    this.dragging = false;
    this.startX = event.clientX;
    this.startY = event.clientY;
    this.startAt = performance.now();
    this.pressArea = this.resolveArea(event.clientX, event.clientY);
  };

  private handlePointerMove = (event: PointerEvent): void => {
    if (!this.pressed || this.dragging) return;
    const dx = event.clientX - this.startX;
    const dy = event.clientY - this.startY;
    if (Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;

    this.dragging = true;
    this.options.onDragStart?.();
    // Tauri 下由系统接管拖拽；浏览器下是 no-op，不影响其它逻辑
    void this.shell.startDragging().catch((error: unknown) => {
      console.warn('[interaction] startDragging 失败:', error);
    });
    this.report({ type: 'dragged', area: 'drag', count: 1, x: 0, y: 0 });
  };

  private handlePointerUp = (event: PointerEvent): void => {
    if (!this.pressed) return;
    this.pressed = false;

    if (this.dragging) {
      this.dragging = false;
      this.options.onDragEnd?.();
      return;
    }

    const held = performance.now() - this.startAt;
    const moved = Math.hypot(event.clientX - this.startX, event.clientY - this.startY);
    if (held > TAP_MAX_MS || moved > DRAG_THRESHOLD_PX) return;

    const area = this.pressArea ?? this.resolveArea(event.clientX, event.clientY);
    if (!area) return; // 点在透明区域：不当成抚摸

    this.options.onTap?.(area);
    const count = this.trackTap(area);
    const type = count > TEASE_THRESHOLD ? 'teased' : AREA_TO_STIMULUS[area];
    this.report({
      type,
      area,
      count,
      x: event.clientX,
      y: event.clientY,
    });
  };

  /** 命中区域：优先用模型 HitAreas，其次用包围盒分区 */
  private resolveArea(x: number, y: number): TapArea | null {
    const areas = this.stage.hitTest(x, y);
    for (const name of areas) {
      const mapped = areaFromHitArea(name);
      if (mapped) return mapped;
    }
    if (areas.length > 0) return 'body';

    const bounds = this.stage.getModelBounds();
    if (!bounds) return null;
    if (x < bounds.x || x > bounds.x + bounds.width) return null;
    if (y < bounds.y || y > bounds.y + bounds.height) return null;
    const relativeY = (y - bounds.y) / bounds.height;
    if (relativeY < 0.3) return 'head';
    if (relativeY < 0.45) return 'face';
    return 'body';
  }

  private trackTap(area: TapArea): number {
    const now = performance.now();
    const history = (this.tapHistory.get(area) ?? []).filter((ts) => now - ts < TEASE_WINDOW_MS);
    history.push(now);
    this.tapHistory.set(area, history);
    return history.length;
  }

  private report(event: InteractionEvent): void {
    console.info('[interaction]', event.type, event.area, `count=${event.count}`);
    this.options.report?.(event);
  }
}
