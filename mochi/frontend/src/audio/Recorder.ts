/**
 * 16kHz mono 录音：PCM16 → base64，按 20–64ms 帧上行。
 *
 * ``push_to_talk`` 由松手停止；``always_on`` 用本地能量 VAD 在 700ms
 * 静音后自动停止（服务端只做端点辅助，不把 VAD 延迟压进识别链路）。
 */

export interface RecorderOptions {
  mode: 'push_to_talk' | 'always_on';
  onChunk: (base64: string, seq: number) => void;
  onLevel?: (rms: number) => void;
  onAutoStop?: () => void;
  onError?: (message: string) => void;
}

const TARGET_SAMPLE_RATE = 16_000;
const VAD_THRESHOLD = 0.012;
const AUTO_STOP_SILENCE_MS = 700;
const FRAME_SAMPLES = 1024;

function toBase64(samples: Int16Array): string {
  const bytes = new Uint8Array(samples.buffer);
  let binary = '';
  const step = 0x8000;
  for (let index = 0; index < bytes.length; index += step) {
    binary += String.fromCharCode(...bytes.subarray(index, index + step));
  }
  return btoa(binary);
}

function resample(input: Float32Array, inputRate: number, outputRate: number): Float32Array {
  if (inputRate === outputRate) return input;
  const ratio = inputRate / outputRate;
  const length = Math.max(1, Math.floor(input.length / ratio));
  const output = new Float32Array(length);
  for (let index = 0; index < length; index += 1) {
    const position = index * ratio;
    const left = Math.floor(position);
    const right = Math.min(input.length - 1, left + 1);
    const fraction = position - left;
    output[index] = input[left] * (1 - fraction) + input[right] * fraction;
  }
  return output;
}

function rms(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  return Math.sqrt(sum / samples.length);
}

export class Recorder {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private seq = 0;
  private speechSeen = false;
  private silenceMs = 0;
  private active = false;
  private stopping = false;
  private mode: 'push_to_talk' | 'always_on';
  private deviceId: string | null = null;

  constructor(private readonly options: RecorderOptions) {
    this.mode = options.mode;
    this.deviceId = localStorage.getItem('mochi.micDevice');
  }

  setMode(mode: 'push_to_talk' | 'always_on'): void {
    this.mode = mode;
  }

  setDeviceId(deviceId: string): void {
    this.deviceId = deviceId || null;
  }

  get sampleRate(): number {
    return TARGET_SAMPLE_RATE;
  }

  get isActive(): boolean {
    return this.active;
  }

  async start(): Promise<void> {
    if (this.active) return;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          ...(this.deviceId ? { deviceId: { exact: this.deviceId } } : {}),
        },
      });
      this.context = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
      if (this.context.state === 'suspended') await this.context.resume();
      this.source = this.context.createMediaStreamSource(this.stream);
      this.processor = this.context.createScriptProcessor(FRAME_SAMPLES, 1, 1);
      this.seq = 0;
      this.speechSeen = false;
      this.silenceMs = 0;
      this.stopping = false;
      this.processor.onaudioprocess = (event) => this.handleFrame(event.inputBuffer.getChannelData(0));
      this.source.connect(this.processor);
      // ScriptProcessor 需要接到 destination 才会持续触发；静音节点避免回放麦克风
      const mute = this.context.createGain();
      mute.gain.value = 0;
      this.processor.connect(mute);
      mute.connect(this.context.destination);
      this.active = true;
    } catch (error) {
      this.options.onError?.(String(error));
      await this.stop();
      throw error;
    }
  }

  private handleFrame(frame: Float32Array): void {
    if (!this.active || !this.context) return;
    const pcm = resample(frame, this.context.sampleRate, TARGET_SAMPLE_RATE);
    const level = rms(pcm);
    this.options.onLevel?.(level);
    const int16 = new Int16Array(pcm.length);
    for (let index = 0; index < pcm.length; index += 1) {
      const value = Math.max(-1, Math.min(1, pcm[index]));
      int16[index] = value < 0 ? value * 0x8000 : value * 0x7fff;
    }
    this.options.onChunk(toBase64(int16), this.seq);
    this.seq += 1;

    if (this.mode !== 'always_on') return;
    const frameMs = (pcm.length / TARGET_SAMPLE_RATE) * 1000;
    if (level >= VAD_THRESHOLD) {
      this.speechSeen = true;
      this.silenceMs = 0;
    } else if (this.speechSeen) {
      this.silenceMs += frameMs;
      if (this.silenceMs >= AUTO_STOP_SILENCE_MS) {
        void this.stop().then(() => this.options.onAutoStop?.());
      }
    }
  }

  async stop(): Promise<void> {
    if (this.stopping) return;
    this.stopping = true;
    this.active = false;
    if (this.processor) {
      this.processor.onaudioprocess = null;
      this.processor.disconnect();
      this.processor = null;
    }
    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    for (const track of this.stream?.getTracks() ?? []) {
      track.stop();
    }
    this.stream = null;
    if (this.context) {
      await this.context.close().catch(() => undefined);
      this.context = null;
    }
    this.stopping = false;
  }
}
