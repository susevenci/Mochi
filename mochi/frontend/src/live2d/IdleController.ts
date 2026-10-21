import type { Live2DStage } from './Live2DStage';

/** 情绪对"身体语言"的调制（计划书 5.6.5 的情绪化待机） */
interface EmotionProfile {
  swayAmp: number;
  breathAmp: number;
  /** 眨眼间隔区间（毫秒） */
  blinkMin: number;
  blinkMax: number;
  /** 闭眼停留时长倍率：越困越想多眯一会儿 */
  blinkHoldScale: number;
}

const DEFAULT_PROFILE: EmotionProfile = {
  swayAmp: 1,
  breathAmp: 1,
  blinkMin: 2000,
  blinkMax: 6000,
  blinkHoldScale: 1,
};

const EMOTION_PROFILES: Record<string, Partial<EmotionProfile>> = {
  happy: { swayAmp: 1.2, breathAmp: 1.1, blinkMin: 2600, blinkMax: 5000 },
  excited: { swayAmp: 1.35, breathAmp: 1.35, blinkMin: 1800, blinkMax: 3600 },
  amused: { swayAmp: 1.15, blinkMin: 2400, blinkMax: 5000 },
  affectionate: { swayAmp: 0.9, breathAmp: 0.95, blinkMin: 3200, blinkMax: 7000 },
  shy: { swayAmp: 0.8, blinkMin: 3000, blinkMax: 6500 },
  proud: { swayAmp: 1.1, blinkMin: 2800, blinkMax: 5600 },
  curious: { swayAmp: 1.1, blinkMin: 2200, blinkMax: 4800 },
  surprised: { swayAmp: 0.6, breathAmp: 1.3, blinkMin: 1200, blinkMax: 2200 },
  angry: { swayAmp: 1.8, breathAmp: 1.25, blinkMin: 3200, blinkMax: 7000 },
  sad: { swayAmp: 0.7, breathAmp: 0.8, blinkMin: 4200, blinkMax: 9000 },
  lonely: { swayAmp: 0.75, breathAmp: 0.85, blinkMin: 4600, blinkMax: 9500 },
  bored: { swayAmp: 0.85, blinkMin: 4000, blinkMax: 8000 },
  sleepy: { swayAmp: 0.45, breathAmp: 0.7, blinkMin: 7000, blinkMax: 14_000, blinkHoldScale: 2.2 },
  worried: { swayAmp: 0.9, blinkMin: 3400, blinkMax: 6600 },
  hurt: { swayAmp: 0.65, breathAmp: 0.8, blinkMin: 5000, blinkMax: 10_000 },
};

/** 1D 平滑噪声：用整数格点哈希 + smoothstep 插值近似 Perlin（足够做身体微摆） */
function hash1(n: number): number {
  const x = Math.sin(n * 127.1) * 43758.5453;
  return x - Math.floor(x);
}

function smoothstep(t: number): number {
  return t * t * (3 - 2 * t);
}

function noise1(x: number): number {
  const i = Math.floor(x);
  const f = x - i;
  const a = hash1(i);
  const b = hash1(i + 1);
  return (a + (b - a) * smoothstep(f)) * 2 - 1;
}

type BlinkPhase = 'open' | 'closing' | 'closed' | 'opening';

/**
 * 待机行为（计划书 5.6.5）——"没有一秒是完全静止的"。
 *
 * 驱动四件事：呼吸（ParamBreath）、眨眼（ParamEyeLOpen/ParamEyeROpen）、
 * 身体微摆（ParamBodyAngleX/Y/Z，Perlin 噪声）、以及按情绪缩放它们的幅度。
 * 视线跟随在 GazeController 里（它需要鼠标输入，职责不同）。
 */
export class IdleController {
  private unsubscribe: (() => void) | null = null;
  private profile: EmotionProfile = { ...DEFAULT_PROFILE };
  private emotionLabel = 'neutral';
  private enabled = true;

  // 呼吸
  private breathPhase = Math.random() * Math.PI * 2;
  private breathPeriodMs = 4000;

  // 眨眼
  private blinkPhase: BlinkPhase = 'open';
  private blinkElapsed = 0;
  private nextBlinkIn = 3000;
  private doubleBlinkPending = false;

  // 微摆
  private swayTime = 0;

  constructor(private readonly stage: Live2DStage) {}

  get currentEmotion(): string {
    return this.emotionLabel;
  }

  attach(): void {
    this.detach();
    this.unsubscribe = this.stage.onFrame((dt) => this.update(dt));
    this.scheduleNextBlink();
    this.syncProfile();
  }

  detach(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
  }

  /** 情绪化待机：同一套待机动作，情绪不同则节奏与幅度不同 */
  setEmotion(label: string): void {
    this.emotionLabel = label;
    this.syncProfile();
  }

  setEnabled(value: boolean): void {
    this.enabled = value;
  }

  reset(): void {
    this.detach();
    this.emotionLabel = 'neutral';
    this.syncProfile();
    this.blinkPhase = 'open';
    this.doubleBlinkPending = false;
    this.scheduleNextBlink();
  }

  private syncProfile(): void {
    this.profile = { ...DEFAULT_PROFILE, ...(EMOTION_PROFILES[this.emotionLabel] ?? {}) };
  }

  private scheduleNextBlink(): void {
    const { blinkMin, blinkMax } = this.profile;
    this.nextBlinkIn = blinkMin + Math.random() * Math.max(1, blinkMax - blinkMin);
  }

  private update(dtMs: number): void {
    if (!this.enabled) return;
    const dt = Math.min(dtMs, 100); // 切后台回来时别跳帧
    this.updateBreath(dt);
    this.updateBlink(dt);
    this.updateSway(dt);
  }

  private updateBreath(dt: number): void {
    this.breathPhase += (dt / this.breathPeriodMs) * Math.PI * 2;
    if (this.breathPhase > Math.PI * 2) {
      this.breathPhase -= Math.PI * 2;
      // 每个周期换一次时长，避免机械节拍（3.5–4.5s）
      this.breathPeriodMs = 3500 + Math.random() * 1000;
    }
    const wave = (Math.sin(this.breathPhase) + 1) / 2; // 0..1
    this.stage.setParameter('ParamBreath', wave * this.profile.breathAmp);
  }

  private updateBlink(dt: number): void {
    switch (this.blinkPhase) {
      case 'open': {
        this.nextBlinkIn -= dt;
        if (this.nextBlinkIn <= 0) {
          this.blinkPhase = 'closing';
          this.blinkElapsed = 0;
        }
        this.writeEyes(1);
        return;
      }
      case 'closing': {
        this.blinkElapsed += dt;
        const progress = Math.min(1, this.blinkElapsed / 90);
        this.writeEyes(1 - progress);
        if (progress >= 1) {
          this.blinkPhase = 'closed';
          this.blinkElapsed = 0;
        }
        return;
      }
      case 'closed': {
        this.blinkElapsed += dt;
        const hold = 60 * this.profile.blinkHoldScale;
        this.writeEyes(0);
        if (this.blinkElapsed >= hold) {
          this.blinkPhase = 'opening';
          this.blinkElapsed = 0;
        }
        return;
      }
      case 'opening': {
        this.blinkElapsed += dt;
        const progress = Math.min(1, this.blinkElapsed / 110);
        this.writeEyes(progress);
        if (progress < 1) return;
        this.blinkPhase = 'open';
        this.blinkElapsed = 0;
        // 偶尔"双眨"：连续两次更好看
        if (this.doubleBlinkPending) {
          this.doubleBlinkPending = false;
          this.nextBlinkIn = 120;
        } else {
          this.doubleBlinkPending = Math.random() < 0.18;
          this.scheduleNextBlink();
        }
        return;
      }
    }
  }

  private writeEyes(open: number): void {
    this.stage.setParameter('ParamEyeLOpen', open);
    this.stage.setParameter('ParamEyeROpen', open);
  }

  private updateSway(dt: number): void {
    this.swayTime += dt / 1000;
    const amp = this.profile.swayAmp;
    // 两个不相关频率叠加，避免看出正弦周期
    const n = noise1(this.swayTime * 0.33) * 0.7 + noise1(this.swayTime * 0.11 + 17.3) * 0.3;
    const n2 = noise1(this.swayTime * 0.27 + 5.1) * 0.7 + noise1(this.swayTime * 0.09 + 41.7) * 0.3;
    const n3 = noise1(this.swayTime * 0.21 + 11.9) * 0.75 + noise1(this.swayTime * 0.07 + 3.3) * 0.25;
    this.stage.setParameter('ParamBodyAngleX', n * 3.2 * amp);
    this.stage.setParameter('ParamBodyAngleY', n2 * 1.8 * amp);
    this.stage.setParameter('ParamBodyAngleZ', n3 * 1.6 * amp);
  }
}
