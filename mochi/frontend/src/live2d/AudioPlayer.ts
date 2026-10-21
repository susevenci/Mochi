/** 测试音的采样率：24k 足够覆盖口型判断，体积也小 */
const TEST_SAMPLE_RATE = 24_000;
/** 默认音量：桌宠不该吓人 */
const DEFAULT_VOLUME = 0.35;

/**
 * 音频播放器 + RMS 分析（计划书 5.6.4 的"口型驱动源"）。
 *
 * S2 用合成的"说话"测试音验证振幅法口型；S4 接 TTS 时把下行音频喂给
 * ``playBuffer()`` 即可复用同一条链路（AudioBufferSourceNode → AnalyserNode → 输出）。
 */
export class AudioPlayer {
  private context: AudioContext | null = null;
  private analyserNode: AnalyserNode | null = null;
  private gainNode: GainNode | null = null;
  private source: AudioBufferSourceNode | null = null;
  private playing = false;
  private volume = DEFAULT_VOLUME;

  get analyser(): AnalyserNode | null {
    return this.analyserNode;
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  setVolume(value: number): void {
    this.volume = Math.min(1, Math.max(0, value));
    if (this.gainNode) {
      this.gainNode.gain.value = this.volume;
    }
  }

  /**
   * 提前建好音频图（含 AnalyserNode）。
   * AnalyserNode 是口型的信号源，而 AudioContext 又只能懒创建——
   * 启动时先建一次，LipSync 才能拿到非空节点。
   */
  prepare(): AnalyserNode | null {
    this.ensureContext();
    return this.analyserNode;
  }

  /** 浏览器要求用户手势后才能出声：这里统一 resume，失败不抛给上层 */
  private ensureContext(): AudioContext | null {
    if (typeof AudioContext === 'undefined') {
      console.warn('[audio] 当前环境不支持 WebAudio');
      return null;
    }
    if (!this.context) {
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.2;
      const gain = context.createGain();
      gain.gain.value = this.volume;
      analyser.connect(gain);
      gain.connect(context.destination);
      this.context = context;
      this.analyserNode = analyser;
      this.gainNode = gain;
    }
    if (this.context.state === 'suspended') {
      void this.context.resume();
    }
    return this.context;
  }

  async playUrl(url: string): Promise<void> {
    const context = this.ensureContext();
    if (!context) return;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`音频下载失败: HTTP ${response.status}`);
    const data = await response.arrayBuffer();
    const buffer = await context.decodeAudioData(data);
    this.playBuffer(buffer);
  }

  playBuffer(buffer: AudioBuffer): void {
    const context = this.ensureContext();
    if (!context || !this.analyserNode) return;
    this.stop();
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.analyserNode);
    source.onended = () => {
      if (this.source === source) {
        this.playing = false;
        this.source = null;
      }
    };
    this.source = source;
    this.playing = true;
    source.start();
  }

  /** 固定测试音频：合成的 14 个音节，用来观察"嘴部开合与音量相关" */
  async playTestSequence(): Promise<void> {
    const context = this.ensureContext();
    if (!context) return;
    this.playBuffer(this.synthesizeSpeech(context));
  }

  stop(): void {
    if (this.source) {
      try {
        this.source.stop();
      } catch {
        // 停止未启动的音源会抛 InvalidStateError，忽略即可
      }
      this.source.disconnect();
      this.source = null;
    }
    this.playing = false;
  }

  /**
   * 合成"说话"波形：多个带包络的音节，基频随机，做振幅调制的目的
   * 就是让 AnalyserNode 的 RMS 呈现类似人声的起伏（而不是恒定正弦）。
   */
  private synthesizeSpeech(context: BaseAudioContext): AudioBuffer {
    const syllableCount = 14;
    const syllableMs = 210;
    const gapMs = 95;
    const totalMs = syllableCount * (syllableMs + gapMs) + 200;
    const length = Math.ceil((totalMs / 1000) * TEST_SAMPLE_RATE);
    const buffer = context.createBuffer(1, length, TEST_SAMPLE_RATE);
    const data = buffer.getChannelData(0);

    let cursor = 100; // 开头留 100ms 静音
    for (let index = 0; index < syllableCount; index += 1) {
      const start = Math.floor((cursor / 1000) * TEST_SAMPLE_RATE);
      const durationMs = syllableMs * (0.8 + Math.random() * 0.45);
      const count = Math.floor((durationMs / 1000) * TEST_SAMPLE_RATE);
      const f0 = 110 + Math.random() * 120;
      // 每 3 个音节歇一长口，像说话的换气
      const breathPause = index > 0 && index % 5 === 0 ? 260 : 0;

      for (let i = 0; i < count; i += 1) {
        const t = i / TEST_SAMPLE_RATE;
        const progress = i / count;
        const envelope = Math.sin(Math.PI * progress) ** 2;
        const vibrato = 1 + 0.02 * Math.sin(2 * Math.PI * 5.5 * t);
        const sample =
          Math.sin(2 * Math.PI * f0 * vibrato * t) +
          0.45 * Math.sin(2 * Math.PI * f0 * 2 * t) +
          0.2 * Math.sin(2 * Math.PI * f0 * 3 * t) +
          0.05 * (Math.random() * 2 - 1);
        const position = start + i;
        if (position < data.length) {
          data[position] += sample * envelope * 0.32;
        }
      }
      cursor += durationMs + gapMs + breathPause;
    }
    return buffer;
  }
}
