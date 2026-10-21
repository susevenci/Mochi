import type { Live2DStage } from './Live2DStage';

export interface CueInput {
  motion?: string;
  priority?: string;
  emotion_label?: string;
}

const IDLE_MOTION = 'idle';
/** 动作播完后回到待机的兜底时长（motion3 若不循环，靠它复位） */
const IDLE_TIMEOUT_MS = 9000;

/**
 * 把后端的 ``performance.cue`` 应用到 Live2D 舞台。
 *
 * 映射表在后端 ``orchestration/performance.py``（唯一权威），
 * 前端不重复维护"情绪→动作"规则，只做兜底与节流。
 */
export class EmotionPresenter {
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private lastMotion = '';
  private lastAppliedAt = 0;

  constructor(private readonly stage: Live2DStage) {}

  apply(cue: CueInput): void {
    const motion = cue.motion || IDLE_MOTION;
    const now = Date.now();
    // 同一动作 800ms 内不重复触发，避免连续 cue 造成抖动
    if (motion === this.lastMotion && now - this.lastAppliedAt < 800) {
      return;
    }
    let played = false;
    if (this.stage.hasMotion(motion)) {
      played = this.stage.playMotion(motion, cue.priority === 'high' ? 'high' : 'normal');
    } else if (this.stage.expressionCount > 0) {
      // 无动作组的模型（如 VTube Studio 移植模型）退回表情反馈
      played = this.stage.playExpression(0);
    }
    if (played) {
      this.lastMotion = motion;
      this.lastAppliedAt = now;
    }
    this.scheduleIdle();
  }

  reset(): void {
    if (this.idleTimer !== null) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
    this.lastMotion = '';
  }

  private scheduleIdle(): void {
    if (this.idleTimer !== null) {
      clearTimeout(this.idleTimer);
    }
    this.idleTimer = setTimeout(() => {
      if (this.stage.hasMotion(IDLE_MOTION)) {
        this.stage.playMotion(IDLE_MOTION, 'normal');
      }
      this.lastMotion = IDLE_MOTION;
    }, IDLE_TIMEOUT_MS);
  }
}
