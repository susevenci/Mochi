import type { Live2DStage } from './Live2DStage';

/** 平滑时间常数：计划书 5.6.5 要求"带 150ms 延迟" */
const SMOOTH_TAU_MS = 150;
/** 眼球最大偏转（Cubism 参数范围 -1~1） */
const MAX_EYE = 0.8;
/** 头部跟随幅度（度）：只做轻微带动，避免和动作抢参数 */
const MAX_HEAD_X = 10;
const MAX_HEAD_Y = 6;
const HEAD_WEIGHT = 0.35;
/** 无鼠标输入多久后开始"自己看四周" */
const DRIFT_AFTER_MS = 15_000;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

interface PointerSample {
  x: number;
  y: number;
}

/**
 * 视线跟随（计划书 5.6.5）。
 *
 * 输入是窗口内的鼠标位置，输出是眼球与头部的偏转参数：
 * 归一化到 [-1, 1] → 限幅 → 150ms 指数平滑 → 写参数。
 * 鼠标长时间不动时自己"看四周"，保证桌面上的角色不是死物。
 */
export class GazeController {
  private unsubscribe: (() => void) | null = null;
  private targetX = 0;
  private targetY = 0;
  private currentX = 0;
  private currentY = 0;
  private nextDriftAt = 0;
  private driftX = 0;
  private driftY = 0;
  private enabled = true;

  constructor(private readonly stage: Live2DStage) {}

  attach(): void {
    this.detach();
    this.unsubscribe = this.stage.onFrame((dt) => this.update(dt));
    this.nextDriftAt = performance.now() + DRIFT_AFTER_MS;
  }

  detach(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
  }

  setEnabled(value: boolean): void {
    this.enabled = value;
    if (!value) {
      this.targetX = 0;
      this.targetY = 0;
    }
  }

  get isEnabled(): boolean {
    return this.enabled;
  }

  /** 由 InteractionHandler 在 pointermove 时喂入窗口内坐标 */
  lookAt(pointer: PointerSample, viewport: { width: number; height: number }): void {
    if (!this.enabled || viewport.width <= 0 || viewport.height <= 0) return;
    // 以窗口中心为原点归一化：屏幕边缘 = ±1
    const nx = ((pointer.x / viewport.width) * 2 - 1) * 1.15;
    const ny = ((pointer.y / viewport.height) * 2 - 1) * 1.15;
    this.targetX = clamp(nx, -1, 1);
    this.targetY = clamp(ny, -1, 1);
    this.nextDriftAt = performance.now() + DRIFT_AFTER_MS;
  }

  reset(): void {
    this.detach();
    this.targetX = 0;
    this.targetY = 0;
    this.currentX = 0;
    this.currentY = 0;
  }

  private update(dt: number): void {
    const now = performance.now();
    if (this.enabled && now > this.nextDriftAt) {
      // 长时间没有鼠标输入：随机看向别处，再慢慢回中
      this.driftX = (Math.random() * 2 - 1) * 0.6;
      this.driftY = (Math.random() * 2 - 1) * 0.4;
      this.targetX = this.driftX;
      this.targetY = this.driftY;
      this.nextDriftAt = now + 4000 + Math.random() * 5000;
    }

    const factor = 1 - Math.exp(-Math.max(dt, 0) / SMOOTH_TAU_MS);
    this.currentX += (this.targetX - this.currentX) * factor;
    this.currentY += (this.targetY - this.currentY) * factor;

    const eyeX = this.currentX * MAX_EYE;
    const eyeY = this.currentY * MAX_EYE;
    this.stage.setParameter('ParamEyeBallX', eyeX);
    this.stage.setParameter('ParamEyeBallY', eyeY);
    this.stage.setParameter('ParamAngleX', eyeX * MAX_HEAD_X * HEAD_WEIGHT);
    this.stage.setParameter('ParamAngleY', -eyeY * MAX_HEAD_Y * HEAD_WEIGHT);
    // 侧看时头略歪，看起来更"活"
    this.stage.setParameter('ParamAngleZ', eyeX * 4 * HEAD_WEIGHT);
  }
}
