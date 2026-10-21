import type { Live2DStage } from './Live2DStage';

type BlendMode = 'add' | 'multiply' | 'overwrite';

interface ExpressionParam {
  id: string;
  value: number;
  blend: BlendMode;
}

interface ExpressionDef {
  name: string;
  params: ExpressionParam[];
}

interface ActiveExpression {
  def: ExpressionDef;
  weight: number;
  target: number;
  /** 每毫秒权重变化量：fadeMs = 0 时视为瞬时 */
  rate: number;
  /** 自动释放的时间点（performance.now()），null 表示常驻 */
  releaseAt: number | null;
}

interface ExpressionJson {
  Parameters?: { Id?: string; Value?: number; Blend?: string }[];
}

/** 计划书 5.6.3：默认 300ms 缓动，避免硬切换 */
export const DEFAULT_FADE_MS = 300;

export interface ExpressionPlayOptions {
  fadeMs?: number;
  /** 瞬时表情（如 surprised）到时自动释放 */
  autoReleaseMs?: number;
}

function toBlend(raw: string | undefined): BlendMode {
  const value = (raw ?? 'Add').toLowerCase();
  if (value === 'multiply') return 'multiply';
  if (value === 'add') return 'add';
  return 'overwrite';
}

/**
 * 表情控制（计划书 5.6.3）：**权重叠加 + 300ms 缓动 + 自动释放**。
 *
 * 没有复用 pixi-live2d-display 的 ``model.expression()``，因为它一次只能挂一个表情、
 * 也不支持权重叠加。这里直接解析 ``.exp3.json`` 的参数表，在每帧最后把参数混进模型：
 * Cubism 的层级本来就是「动作 → 表情 → 物理」，写在模型求值之后正好等价。
 */
export class ExpressionController {
  private readonly defs = new Map<string, ExpressionDef>();
  private readonly active = new Map<string, ActiveExpression>();
  /**
   * 表情参数的"底值"快照（覆盖前由模型/动作/待机算出的值）。
   *
   * 必须在第一帧覆盖前捕获一次——Cubism 不会重置"没有任何动作驱动"的参数，
   * 若每帧拿 ``getParameter`` 当基底再叠加，Add 类参数会每帧累加直至饱和。
   */
  private readonly baseline = new Map<string, number>();
  private unsubscribe: (() => void) | null = null;
  private enabled = true;

  constructor(private readonly stage: Live2DStage) {}

  get names(): string[] {
    return [...this.defs.keys()];
  }

  get activeNames(): string[] {
    return [...this.active.entries()].filter(([, item]) => item.weight > 0.01).map(([name]) => name);
  }

  /** 模型切换后重新拉取表达式文件（解析失败只跳过该表情，不影响主流程） */
  async load(expressions: { name: string; url: string }[]): Promise<void> {
    this.reset();
    this.unsubscribe = this.stage.onFrame((dt) => this.update(dt));
    await Promise.all(
      expressions.map(async (item) => {
        try {
          const response = await fetch(item.url);
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const json = (await response.json()) as ExpressionJson;
          const params: ExpressionParam[] = (json.Parameters ?? [])
            .filter(
              (param): param is { Id: string; Value?: number; Blend?: string } =>
                typeof param?.Id === 'string' && this.stage.hasParameter(param.Id),
            )
            .map((param) => ({
              id: param.Id,
              value: typeof param.Value === 'number' ? param.Value : 0,
              blend: toBlend(param.Blend),
            }));
          this.defs.set(item.name, { name: item.name, params });
        } catch (error) {
          console.warn('[expression] 解析失败:', item.url, error);
        }
      }),
    );
    console.info(`[expression] loaded ${this.defs.size}/${expressions.length}`);
  }

  /**
   * 播放表情。``weight`` 是目标权重（0~1），过渡时长默认 300ms。
   * 同名表情重复调用会刷新目标权重，不会重新开始淡入。
   */
  play(name: string, weight = 1, options: ExpressionPlayOptions = {}): boolean {
    if (!this.enabled) return false;
    const def = this.defs.get(name);
    if (!def) return false;
    const fadeMs = Math.max(0, options.fadeMs ?? DEFAULT_FADE_MS);
    const existing = this.active.get(name);
    const clamped = Math.min(1, Math.max(0, weight));
    const rate = fadeMs === 0 ? 1 : 1 / fadeMs;
    this.active.set(name, {
      def,
      weight: existing?.weight ?? 0,
      target: clamped,
      rate,
      releaseAt:
        options.autoReleaseMs !== undefined && options.autoReleaseMs > 0
          ? performance.now() + options.autoReleaseMs
          : null,
    });
    return true;
  }

  /** 混合情绪：一次性给出多个表情的权重（计划书 5.6.3 的叠加用法） */
  blend(items: { name: string; weight: number }[], fadeMs = DEFAULT_FADE_MS): void {
    for (const item of items) {
      this.play(item.name, item.weight, { fadeMs });
    }
  }

  release(name: string, fadeMs = DEFAULT_FADE_MS): void {
    const item = this.active.get(name);
    if (!item) return;
    item.target = 0;
    item.releaseAt = null;
    item.rate = fadeMs <= 0 ? 1 : 1 / fadeMs;
  }

  releaseAll(fadeMs = DEFAULT_FADE_MS): void {
    for (const name of this.active.keys()) {
      this.release(name, fadeMs);
    }
  }

  setEnabled(value: boolean): void {
    this.enabled = value;
    if (!value) this.clearImmediate();
  }

  status(): { name: string; weight: number }[] {
    return [...this.active.entries()].map(([name, item]) => ({
      name,
      weight: Number(item.weight.toFixed(3)),
    }));
  }

  reset(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.defs.clear();
    this.active.clear();
    this.restoreBaseline();
  }

  private clearImmediate(): void {
    this.restoreBaseline();
    this.active.clear();
  }

  /** 把被表情覆盖过的参数写回底值（否则释放后模型会永远停在表情形变） */
  private restoreBaseline(): void {
    for (const [id, value] of this.baseline) {
      this.stage.setParameter(id, value);
    }
    this.baseline.clear();
  }

  private update(dtMs: number): void {
    const now = performance.now();

    for (const [name, item] of this.active) {
      if (item.releaseAt !== null && now >= item.releaseAt) {
        item.releaseAt = null;
        item.target = 0;
      }
      const delta = item.target - item.weight;
      const step = item.rate * dtMs;
      item.weight = Math.abs(delta) <= step ? item.target : item.weight + Math.sign(delta) * step;
      if (item.weight <= 0.001 && item.target === 0) {
        this.active.delete(name);
      }
    }

    // 每帧从底值重新聚合，写一次最终值：既支持多表情叠加，也不会自我累加
    const values = new Map<string, number>();
    for (const item of this.active.values()) {
      const { weight } = item;
      if (weight <= 0.001) continue;
      for (const param of item.def.params) {
        if (!this.baseline.has(param.id)) {
          this.baseline.set(param.id, this.stage.getParameter(param.id));
        }
        const base = this.baseline.get(param.id) ?? 0;
        const current = values.get(param.id) ?? base;
        let next = current;
        if (param.blend === 'add') {
          next = current + param.value * weight;
        } else if (param.blend === 'multiply') {
          next = current * (1 + (param.value - 1) * weight);
        } else {
          next = current + (param.value - current) * weight;
        }
        values.set(param.id, next);
      }
    }

    for (const [id, value] of values) {
      this.stage.setParameter(id, value);
    }
    // 已没有任何表情使用的参数：写回底值并忘掉快照（下次重新捕获）
    for (const id of [...this.baseline.keys()]) {
      if (!values.has(id)) {
        this.stage.setParameter(id, this.baseline.get(id) ?? 0);
        this.baseline.delete(id);
      }
    }
  }
}
