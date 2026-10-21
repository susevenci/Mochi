import { Application, Point, Ticker, UPDATE_PRIORITY, type DisplayObject } from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display/cubism4';

// pixi.js 与 pixi-live2d-display 各自依赖一份 @pixi/*：运行时等价，类型声明不互通，故用断言桥接
type RegisterTickerArg = Parameters<typeof Live2DModel.registerTicker>[0];
Live2DModel.registerTicker(Ticker as unknown as RegisterTickerArg);

/**
 * CubismModel 的最小结构（只声明我们真正调用的方法）。
 * 用结构化类型而不是 any：写错参数名时 tsc 能拦下来。
 */
export interface CoreModelLike {
  getParameterIndex(id: string): number;
  getParameterValueById(id: string): number;
  setParameterValueById(id: string, value: number, weight?: number): void;
  getParameterCount(): number;
  getParameterId(index: number): string;
}

interface ExpressionRef {
  name: string;
  /** 已按 model3.json 目录解析过的绝对（站点相对）URL */
  url: string;
}

/** 模型能力清单：控制器据此决定"能驱动什么"，能力缺失时降级而不是报错。 */
export interface ModelCapabilities {
  name: string;
  url: string;
  motionGroups: string[];
  expressions: ExpressionRef[];
  /** LipSync 组里的嘴部参数；模型没声明组时退化为探测到的 ParamMouthOpenY* */
  mouthParamIds: string[];
  hitAreaNames: string[];
  parameterCount: number;
}

export interface StageOptions {
  /** 缩放到窗口的比例上限（留一点边距） */
  fitPadding?: number;
}

interface ModelJson {
  Name?: string;
  FileReferences?: {
    Expressions?: { Name?: string; File?: string }[];
  };
  Groups?: { Target?: string; Name?: string; Ids?: string[] }[];
  HitAreas?: { Name?: string; Id?: string }[];
}

/** 嘴部参数的兜底探测顺序：自定义模型常用带后缀的变体 */
const MOUTH_FALLBACK_PARAMS = [
  'ParamMouthOpenY',
  'ParamMouthOpenY2',
  'ParamMouthOpenY_SD',
  'ParamMouthOpenY_SD2',
];

/**
 * 帧钩子优先级：pixi 里数值越大越先执行（INTERACTION=50 > NORMAL=0 > LOW=-25 > UTILITY=-50）。
 * 模型自身注册在 NORMAL(0)，我们用最低的 UTILITY 保证参数写入发生在 Cubism 求值之后，
 * 否则眨眼/呼吸/口型会被模型自带的参数演算覆盖。
 */
const FRAME_PRIORITY = UPDATE_PRIORITY.UTILITY;

/**
 * pixi-live2d-display 0.4 面向 pixi 6，事件系统仍会调用 ``isInteractive()``；
 * 在 pixi 7 上该方法已被 ``eventMode`` 取代，会抛 TypeError 刷屏。
 * 显式补一个空实现，让交互判定安全地返回"不可交互"。
 */
function patchPixi6Interaction(target: object): void {
  const candidate = target as { isInteractive?: () => boolean };
  if (typeof candidate.isInteractive !== 'function') {
    candidate.isInteractive = () => false;
  }
}

/**
 * Live2D 呈现层（计划书 5.6.2）。
 *
 * 只负责"把模型显示出来 + 暴露可驱动的参数/动作/命中区域"，不做业务决策：
 * 情绪由后端权威产出，控制器只消费 ``performance.cue``（不变量 I1）。
 */
export class Live2DStage {
  private model: Live2DModel | null = null;
  private capabilities: ModelCapabilities | null = null;
  private readonly app: Application;
  private readonly padding: number;
  private readonly frameListeners = new Set<(dtMs: number) => void>();
  private frameHooked = false;

  constructor(app: Application, options: StageOptions = {}) {
    this.app = app;
    this.padding = options.fitPadding ?? 0.94;
  }

  get isReady(): boolean {
    return this.model !== null;
  }

  get caps(): ModelCapabilities | null {
    return this.capabilities;
  }

  private get core(): CoreModelLike | null {
    const internal = this.model?.internalModel as unknown as { coreModel?: CoreModelLike };
    return internal?.coreModel ?? null;
  }

  /**
   * 注册每帧回调（在 Cubism 求值之后执行）。
   * 返回取消订阅函数，便于控制器随模型切换一起卸载。
   */
  onFrame(listener: (dtMs: number) => void): () => void {
    this.frameListeners.add(listener);
    this.ensureFrameHook();
    return () => this.frameListeners.delete(listener);
  }

  private ensureFrameHook(): void {
    if (this.frameHooked) return;
    Ticker.shared.add(this.tickFrame, this, FRAME_PRIORITY);
    this.frameHooked = true;
  }

  private tickFrame(): void {
    if (this.frameListeners.size === 0) return;
    const dt = Ticker.shared.deltaMS;
    for (const listener of this.frameListeners) {
      try {
        listener(dt);
      } catch (error) {
        console.warn('[live2d] 帧回调异常:', error);
      }
    }
  }

  // ── 参数读写 ──

  hasParameter(id: string): boolean {
    const core = this.core;
    if (!core) return false;
    try {
      return core.getParameterIndex(id) >= 0;
    } catch {
      return false;
    }
  }

  getParameter(id: string): number {
    const core = this.core;
    if (!core) return 0;
    try {
      return core.getParameterValueById(id);
    } catch {
      return 0;
    }
  }

  setParameter(id: string, value: number): boolean {
    const core = this.core;
    if (!core) return false;
    try {
      if (core.getParameterIndex(id) < 0) return false;
      core.setParameterValueById(id, value);
      return true;
    } catch {
      return false;
    }
  }

  /** 供调试面板展示的可写参数快照 */
  sampleParameters(ids: string[]): Record<string, number> {
    const out: Record<string, number> = {};
    for (const id of ids) {
      out[id] = this.getParameter(id);
    }
    return out;
  }

  // ── 动作 / 表情元数据 ──

  getMotionNames(): string[] {
    const definitions = this.model?.internalModel.motionManager.definitions;
    if (!definitions) return [];
    return Object.keys(definitions).sort();
  }

  hasMotion(name: string): boolean {
    return this.getMotionNames().includes(name);
  }

  get expressionCount(): number {
    return this.capabilities?.expressions.length ?? 0;
  }

  getExpressionNames(): string[] {
    return (this.capabilities?.expressions ?? []).map((item) => item.name);
  }

  /**
   * 立即播放动作（绕过优先级队列）。
   * 只给调试面板/手动试玩用；对话驱动的表现一律走 MotionController。
   */
  playMotion(name: string, priority: 'normal' | 'high' = 'normal'): boolean {
    const model = this.model;
    if (!model) return false;
    try {
      // pixi-live2d-display 的 priority：1 idle / 2 normal / 3 force
      void model.motion(name, 0, priority === 'high' ? 3 : 2);
      return true;
    } catch (error) {
      console.warn('[live2d] 动作播放失败:', name, error);
      return false;
    }
  }

  /** 底层动作启动（由 MotionController 的优先级队列调用） */
  async startMotion(group: string, index: number, priority: number): Promise<boolean> {
    const model = this.model;
    if (!model) return false;
    try {
      return await model.motion(group, index, priority);
    } catch (error) {
      console.warn('[live2d] 动作启动失败:', group, error);
      return false;
    }
  }

  /** 当前是否有动作在播（MotionController 靠它判定"播完了"） */
  get motionPlaying(): boolean {
    const manager = this.model?.internalModel.motionManager as unknown as
      | { playing?: boolean }
      | undefined;
    return Boolean(manager?.playing);
  }

  getMotionCount(group: string): number {
    const definitions = this.model?.internalModel.motionManager.definitions;
    const specs = definitions?.[group];
    return Array.isArray(specs) ? specs.length : 0;
  }

  playExpressionIndex(index: number): boolean {
    if (!this.model) return false;
    try {
      void this.model.expression(index);
      return true;
    } catch (error) {
      console.warn('[live2d] 表情播放失败:', index, error);
      return false;
    }
  }

  // ── 命中检测 ──

  /**
   * 屏幕坐标 → 模型命中区域。
   * 模型没定义 HitAreas 时（qiye_10 就是这种），返回空数组，
   * 由 InteractionHandler 用包围盒几何分区兜底。
   */
  hitTest(clientX: number, clientY: number): string[] {
    const model = this.model;
    if (!model) return [];
    try {
      const local = model.toModelPosition(new Point(clientX, clientY));
      return model.internalModel.hitTest(local.x, local.y);
    } catch (error) {
      console.warn('[live2d] hitTest 失败:', error);
      return [];
    }
  }

  /** 模型在当前画布上的包围盒（屏幕坐标），用于几何分区与拖拽判定 */
  getModelBounds(): { x: number; y: number; width: number; height: number } | null {
    const model = this.model;
    if (!model) return null;
    const bounds = model.getBounds();
    if (!bounds.width || !bounds.height) return null;
    return { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height };
  }

  // ── 生命周期 ──

  async load(modelUrl: string): Promise<ModelCapabilities> {
    const model = await Live2DModel.from(modelUrl, { autoInteract: false });
    this.model = model;
    this.capabilities = this.readCapabilities(model, modelUrl);
    patchPixi6Interaction(model);
    patchPixi6Interaction(this.app.stage);
    model.anchor.set(0.5, 0.5);
    this.app.stage.addChild(model as unknown as DisplayObject);
    this.layout();
    this.ensureFrameHook();
    console.info(
      `[live2d] loaded ${this.capabilities.name} ` +
        `motions=${this.capabilities.motionGroups.length} ` +
        `expressions=${this.capabilities.expressions.length} ` +
        `mouth=${this.capabilities.mouthParamIds.join('|') || 'none'} ` +
        `hitAreas=${this.capabilities.hitAreaNames.join('|') || 'none'}`,
    );
    return this.capabilities;
  }

  private readCapabilities(model: Live2DModel, modelUrl: string): ModelCapabilities {
    const internal = model.internalModel as unknown as {
      settings: { json?: ModelJson; resolveURL(path: string): string };
      motionManager: { definitions?: Record<string, unknown[]> };
    };
    const json = internal.settings.json ?? {};
    const expressions: ExpressionRef[] = (json.FileReferences?.Expressions ?? [])
      .filter((item): item is { Name: string; File: string } => Boolean(item?.Name && item?.File))
      .map((item) => ({ name: item.Name, url: internal.settings.resolveURL(item.File) }));

    const lipSyncGroup = (json.Groups ?? []).find((group) => group.Name === 'LipSync');
    let mouthParamIds = (lipSyncGroup?.Ids ?? []).filter((id) => this.parameterExists(model, id));
    if (mouthParamIds.length === 0) {
      mouthParamIds = MOUTH_FALLBACK_PARAMS.filter((id) => this.parameterExists(model, id));
    }

    const core = (internal as unknown as { coreModel?: CoreModelLike }).coreModel;

    return {
      name: json.Name ?? modelUrl.split('/').slice(-2, -1)[0] ?? 'live2d',
      url: modelUrl,
      motionGroups: Object.keys(internal.motionManager.definitions ?? {}).sort(),
      expressions,
      mouthParamIds,
      hitAreaNames: (json.HitAreas ?? [])
        .map((area) => area.Name)
        .filter((name): name is string => Boolean(name)),
      parameterCount: core?.getParameterCount() ?? 0,
    };
  }

  private parameterExists(model: Live2DModel, id: string): boolean {
    try {
      const core = (model.internalModel as unknown as { coreModel?: CoreModelLike }).coreModel;
      return Boolean(core && core.getParameterIndex(id) >= 0);
    } catch {
      return false;
    }
  }

  layout(): void {
    const model = this.model;
    if (!model) return;
    const width = this.app.screen.width;
    const height = this.app.screen.height;
    // 用 scale=1 时的实际包围盒计算，避免 internalModel 尺寸单位不一致
    model.scale.set(1);
    const bounds = model.getLocalBounds();
    const baseWidth = bounds.width || 1;
    const baseHeight = bounds.height || 1;
    const scale = Math.min(width / baseWidth, height / baseHeight) * this.padding;
    model.scale.set(scale);
    // 略微下移，让头部留出对话气泡的位置
    model.position.set(width / 2, height / 2 + height * 0.06);
    console.info(
      `[live2d] bounds=${Math.round(baseWidth)}x${Math.round(baseHeight)} ` +
        `scale=${scale.toFixed(4)} pos=(${Math.round(width / 2)},${Math.round(
          height / 2 + height * 0.06,
        )})`,
    );
  }

  destroy(): void {
    this.capabilities = null;
    if (!this.model) return;
    this.app.stage.removeChild(this.model as unknown as DisplayObject);
    this.model.destroy();
    this.model = null;
  }
}
