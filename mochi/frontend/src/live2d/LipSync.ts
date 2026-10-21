import type { Live2DStage } from './Live2DStage';

/** 口型张开（快）：约 26ms 到位的指数逼近 */
const OPEN_TAU_MS = 26;
/** 口型闭合（慢）：约 70ms，符合"开快合慢"的真实口型物理 */
const CLOSE_TAU_MS = 70;
/** 伽马校正系数：让小声也有可见开合（计划书 5.6.4） */
const GAIN = 3.2;
const GAMMA = 0.7;
/** 静音判定：低于这个 RMS 直接闭口，避免底噪抖动 */
const NOISE_FLOOR = 0.012;

/**
 * 波形缓冲区类型。
 * 显式推导而不是写 ``Uint8Array``：新版 TS 的 DOM 类型把 ``getByteTimeDomainData``
 * 收窄成 ``Uint8Array<ArrayBuffer>``，手写泛型在 5.4 上又无法解析，推导两头都安全。
 */
function createWaveBuffer(size: number) {
  // 显式传入 ArrayBuffer，类型才能收窄为 Uint8Array<ArrayBuffer>
  return new Uint8Array(new ArrayBuffer(size));
}

type WaveBuffer = ReturnType<typeof createWaveBuffer>;

/**
 * 口型同步 - 振幅法（计划书 5.6.4 模式 A，MVP 采用）。
 *
 * ``AnalyserNode.getByteTimeDomainData`` → RMS → 伽马校正 → 开快合慢平滑 →
 * 写入模型声明的 LipSync 参数组（qiye_10 是 ParamMouthOpenY_SD*，devil 退化为 ParamMouthOpenY）。
 * 音素法（模式 B）留给 S4 接 TTS 时间戳时再升级，接口不变。
 */
export class LipSync {
  private analyser: AnalyserNode | null = null;
  private resolver: (() => AnalyserNode | null) | null = null;
  private data: WaveBuffer | null = null;
  private mouthParamIds: string[] = [];
  private current = 0;
  private lastRms = 0;
  private unsubscribe: (() => void) | null = null;
  private enabled = true;

  constructor(private readonly stage: Live2DStage) {}

  /** 当前嘴部开合度（0~1），调试面板用它画电平表 */
  get level(): number {
    return this.current;
  }

  get rms(): number {
    return this.lastRms;
  }

  get isEnabled(): boolean {
    return this.enabled;
  }

  get params(): string[] {
    return [...this.mouthParamIds];
  }

  attach(mouthParamIds: string[], getAnalyser?: () => AnalyserNode | null): void {
    this.detach();
    this.mouthParamIds = mouthParamIds;
    // 旁路提供者：AudioContext 是懒创建的（首次播放才有），每帧再取一次比一次性接线更稳
    this.resolver = getAnalyser ?? null;
    this.unsubscribe = this.stage.onFrame((dt) => this.update(dt));
  }

  detach(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.resolver = null;
    this.analyser = null;
    this.data = null;
    this.current = 0;
    this.lastRms = 0;
  }

  /** 接上播放器的分析节点；传 null 表示停止驱动（嘴自然闭合） */
  connect(analyser: AnalyserNode | null): void {
    this.analyser = analyser;
    this.data = analyser ? createWaveBuffer(analyser.fftSize) : null;
  }

  setEnabled(value: boolean): void {
    this.enabled = value;
    if (!value) this.current = 0;
  }

  private update(dtMs: number): void {
    if (!this.enabled) return;
    this.refreshAnalyser();
    const dt = Math.max(0, Math.min(dtMs, 100));
    const target = this.readTarget();
    const tau = target > this.current ? OPEN_TAU_MS : CLOSE_TAU_MS;
    const factor = 1 - Math.exp(-dt / tau);
    this.current += (target - this.current) * factor;
    if (this.current < 0.001) this.current = 0;

    for (const id of this.mouthParamIds) {
      this.stage.setParameter(id, this.current);
    }
  }

  /** 解析器给出的节点可能从 null 变为可用（音频上下文懒创建），变化时重建缓冲区 */
  private refreshAnalyser(): void {
    if (!this.resolver) return;
    const next = this.resolver();
    if (next === this.analyser) return;
    this.analyser = next;
    this.data = next ? createWaveBuffer(next.fftSize) : null;
  }

  private readTarget(): number {
    const analyser = this.analyser;
    const data = this.data;
    if (!analyser || !data) return 0;
    analyser.getByteTimeDomainData(data);

    let sum = 0;
    for (let i = 0; i < data.length; i += 1) {
      const centered = (data[i] - 128) / 128;
      sum += centered * centered;
    }
    const rms = Math.sqrt(sum / data.length);
    this.lastRms = rms;
    if (rms < NOISE_FLOOR) return 0;
    const shaped = Math.pow(rms * GAIN, GAMMA);
    return Math.min(1, Math.max(0, shaped));
  }
}
