import type { ExpressionController } from './ExpressionController';
import type { IdleController } from './IdleController';
import type { MotionController, MotionPriority } from './MotionController';

export interface CueInput {
  motion?: string;
  priority?: string;
  emotion_label?: string;
  expression?: string | null;
}

/** 瞬时情绪的表现自动释放时长（计划书阶段 3 验收：surprised 2.5s 内释放） */
const TRANSIENT_RELEASE_MS: Record<string, number> = {
  surprised: 2500,
};

function toPriority(raw: string | undefined): MotionPriority {
  if (raw === 'force' || raw === 'high' || raw === 'idle') return raw;
  return 'normal';
}

/**
 * ``performance.cue`` 的分发器（计划书 5.6.2 的 CueDispatcher）。
 *
 * 唯一职责：把后端的表现指令转成控制器调用。
 * 映射表在后端 ``orchestration/performance.py``（唯一权威），前端不重复维护
 * "情绪→动作"规则（不变量 I1：前端只消费，不生产情绪）。
 */
export class CueDispatcher {
  private lastCueAt = 0;
  private lastLabel = '';

  constructor(
    private readonly motion: MotionController,
    private readonly expression: ExpressionController,
    private readonly idle: IdleController,
  ) {}

  dispatch(cue: CueInput): void {
    const label = cue.emotion_label || 'neutral';
    const now = performance.now();
    // 同标签 300ms 内的重复 cue 直接吞掉：一轮 turn 里的 multiple cue 不该抖
    if (label === this.lastLabel && now - this.lastCueAt < 300) {
      return;
    }
    this.lastLabel = label;
    this.lastCueAt = now;

    // 情绪化待机：即使没有说话，身体语言也跟着情绪变（计划书 5.6.5）
    this.idle.setEmotion(label);

    let played = false;
    if (cue.motion) {
      played = this.motion.request(cue.motion, toPriority(cue.priority));
    }

    // 表情通道：后端点名了就用点名的，没点名时用同名表情兜底
    const expressionName = cue.expression || (this.hasExpression(label) ? label : null);
    if (expressionName) {
      const release = TRANSIENT_RELEASE_MS[label];
      this.expression.play(expressionName, 1, {
        autoReleaseMs: release,
      });
    }

    if (!played && !expressionName) {
      console.debug('[cue] no playable channel for', label, cue.motion);
    }
  }

  reset(): void {
    this.lastLabel = '';
    this.lastCueAt = 0;
  }

  private hasExpression(name: string): boolean {
    return this.expression.names.includes(name);
  }
}
