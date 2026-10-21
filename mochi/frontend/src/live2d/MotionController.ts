import type { Live2DStage } from './Live2DStage';

export type MotionPriority = 'idle' | 'normal' | 'high' | 'force';

/** 计划书 5.6.3 的四级优先级（0 最低） */
const RANK: Record<MotionPriority, number> = { idle: 0, normal: 1, high: 2, force: 3 };
/** 映射到 pixi-live2d-display 的原生优先级：1 idle / 2 normal / 3 force */
const NATIVE_PRIORITY: Record<MotionPriority, number> = { idle: 1, normal: 2, high: 3, force: 3 };

/** 同一动作 10s 内不重复播放（避免机械感） */
const COOLDOWN_MS = 10_000;
/** normal/high 队列长度上限，超出丢弃最旧 */
const QUEUE_LIMIT = 2;
/** 随机小动作间隔 8–25s */
const IDLE_MIN_MS = 8_000;
const IDLE_MAX_MS = 25_000;
/** motion3 没有回调时的兜底复位 */
const MOTION_MAX_MS = 9_000;

interface QueueItem {
  group: string;
  priority: MotionPriority;
}

export interface MotionStatus {
  playing: string | null;
  priority: MotionPriority | null;
  queue: string[];
  idlePool: string[];
}

/**
 * 动作调度（计划书 5.6.3）：四级优先级队列 + 冷却去重 + 空闲随机小动作。
 *
 * 只决定"什么时候播哪个动作"，不决定"该播什么"——后者由后端 cue 决定（不变量 I1）。
 */
export class MotionController {
  private queue: QueueItem[] = [];
  private current: { group: string; priority: MotionPriority; startedAt: number } | null = null;
  private readonly lastPlayedAt = new Map<string, number>();
  /** 正在异步启动中的动作：防止同一 tick 内连发两次绕过冷却 */
  private readonly pending = new Set<string>();
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private idlePool: string[] = [];
  private unsubscribe: (() => void) | null = null;
  private enabled = true;

  constructor(
    private readonly stage: Live2DStage,
    private readonly idleGroup = 'idle',
  ) {}

  /** 模型加载/切换后调用：重建空闲池并进入待机 */
  attach(): void {
    this.reset();
    const names = this.stage.getMotionNames();
    this.idlePool = names.filter((name) => /^idle/i.test(name) && name !== this.idleGroup);
    this.unsubscribe = this.stage.onFrame(() => this.update());
    if (this.stage.hasMotion(this.idleGroup)) {
      void this.play(this.idleGroup, 'idle');
    }
    this.scheduleIdle();
    console.info(
      `[motion] attached idleGroup=${this.idleGroup} idlePool=${this.idlePool.length}`,
    );
  }

  get status(): MotionStatus {
    return {
      playing: this.current?.group ?? null,
      priority: this.current?.priority ?? null,
      queue: this.queue.map((item) => item.group),
      idlePool: [...this.idlePool],
    };
  }

  setEnabled(value: boolean): void {
    this.enabled = value;
    if (!value) {
      this.queue = [];
      this.clearIdleTimer();
    } else {
      this.scheduleIdle();
    }
  }

  /**
   * 请求播放一个动作。返回 false 表示被冷却/优先级/能力过滤掉——
   * 调用方应当有降级路径（表情兜底），而不是当作异常。
   */
  request(group: string, priority: MotionPriority = 'normal'): boolean {
    if (!this.enabled) return false;
    if (!group || !this.stage.hasMotion(group)) return false;

    const now = performance.now();
    const last = this.lastPlayedAt.get(group) ?? 0;
    if (priority !== 'force' && now - last < COOLDOWN_MS) {
      console.debug(`[motion] cooldown ${group} (${Math.round(now - last)}ms)`);
      return false;
    }

    if (priority === 'force') {
      this.queue = [];
      void this.play(group, priority);
      return true;
    }

    if (this.current) {
      // 高优先级可打断低优先级；同级或低一级排队等待
      if (RANK[priority] > RANK[this.current.priority]) {
        void this.play(group, priority);
        return true;
      }
      if (priority === 'idle') return false;
      this.enqueue({ group, priority });
      return true;
    }

    if (priority === 'idle' && this.queue.length > 0) return false;
    void this.play(group, priority);
    return true;
  }

  /** 立刻回到待机（打断用，例如拖拽结束） */
  backToIdle(): void {
    this.queue = [];
    if (this.stage.hasMotion(this.idleGroup)) {
      void this.play(this.idleGroup, 'idle');
    }
  }

  reset(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.clearIdleTimer();
    this.queue = [];
    this.current = null;
    this.lastPlayedAt.clear();
    this.pending.clear();
    this.idlePool = [];
  }

  /** 下面这个方法只给调试面板/自检用：清掉冷却，让"去重"可以被重复验证 */
  clearCooldown(group?: string): void {
    if (group) {
      this.lastPlayedAt.delete(group);
    } else {
      this.lastPlayedAt.clear();
    }
  }

  private enqueue(item: QueueItem): void {
    this.queue.push(item);
    if (this.queue.length > QUEUE_LIMIT) {
      const dropped = this.queue.shift();
      console.debug('[motion] queue full, dropped', dropped?.group);
    }
  }

  private async play(group: string, priority: MotionPriority): Promise<void> {
    if (this.pending.has(group)) return;
    this.pending.add(group);
    // 冷却必须在 await 之前**同步**占位，否则同一 tick 内的两次 request 都会放行
    const previous = this.lastPlayedAt.get(group);
    this.lastPlayedAt.set(group, performance.now());
    try {
      const native = NATIVE_PRIORITY[priority];
      const ok = await this.stage.startMotion(group, 0, native);
      if (!ok) {
        // 启动被拒（例如被更高优先级占用）：回滚冷却，下次还能立即重试
        if (previous === undefined) {
          this.lastPlayedAt.delete(group);
        } else {
          this.lastPlayedAt.set(group, previous);
        }
        console.debug(`[motion] start rejected ${group} (priority=${priority})`);
        return;
      }
      this.current = { group, priority, startedAt: this.lastPlayedAt.get(group) ?? performance.now() };
      this.clearIdleTimer();
    } finally {
      this.pending.delete(group);
    }
  }

  private update(): void {
    if (!this.current) {
      this.drain();
      return;
    }
    const elapsed = performance.now() - this.current.startedAt;
    const finished = !this.stage.motionPlaying || elapsed > MOTION_MAX_MS;
    if (!finished) return;
    this.current = null;
    if (this.enabled) this.scheduleIdle();
    this.drain();
  }

  private drain(): void {
    if (this.current || this.queue.length === 0) return;
    const next = this.queue.shift();
    if (!next) return;
    void this.play(next.group, next.priority);
  }

  private scheduleIdle(): void {
    this.clearIdleTimer();
    if (!this.enabled) return;
    const delay = IDLE_MIN_MS + Math.random() * (IDLE_MAX_MS - IDLE_MIN_MS);
    this.idleTimer = setTimeout(() => {
      this.idleTimer = null;
      if (this.enabled && !this.current && this.queue.length === 0 && this.idlePool.length > 0) {
        const group = this.idlePool[Math.floor(Math.random() * this.idlePool.length)];
        const last = this.lastPlayedAt.get(group) ?? 0;
        if (performance.now() - last >= COOLDOWN_MS) {
          void this.play(group, 'idle');
        }
      }
      this.scheduleIdle();
    }, delay);
  }

  private clearIdleTimer(): void {
    if (this.idleTimer !== null) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
  }
}
