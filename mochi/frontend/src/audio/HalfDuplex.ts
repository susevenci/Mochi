/**
 * 音频会话五态机（规划文档 3.5.5）。
 *
 * 规则：
 * - SPEAKING 期间不向 WS 发送音频（半双工的落地点）；
 * - INTERRUPTED 必须完成"停播放、清队列、恢复收音"三件事；
 * - 非法转移记日志，不抛异常。
 */

export type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'interrupted';

const ALLOWED: Record<VoiceState, ReadonlySet<VoiceState>> = {
  idle: new Set(['listening', 'thinking', 'speaking']),
  listening: new Set(['thinking', 'idle']),
  thinking: new Set(['speaking', 'idle', 'interrupted']),
  speaking: new Set(['interrupted', 'idle']),
  interrupted: new Set(['idle', 'listening']),
};

type Listener = (state: VoiceState, previous: VoiceState) => void;

export class HalfDuplex {
  private stateValue: VoiceState = 'idle';
  private readonly listeners = new Set<Listener>();

  get state(): VoiceState {
    return this.stateValue;
  }

  get canStartListening(): boolean {
    return this.stateValue === 'idle' || this.stateValue === 'interrupted';
  }

  get isSpeaking(): boolean {
    return this.stateValue === 'speaking';
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.stateValue, this.stateValue);
    return () => {
      this.listeners.delete(listener);
    };
  }

  transition(next: VoiceState, reason = ''): boolean {
    const previous = this.stateValue;
    if (next === previous) return true;
    if (!ALLOWED[previous].has(next)) {
      console.warn(`[voice] illegal transition ${previous} -> ${next} (${reason})`);
      return false;
    }
    this.stateValue = next;
    for (const listener of this.listeners) listener(next, previous);
    return true;
  }

  reset(): void {
    this.transition('idle', 'reset');
  }
}
