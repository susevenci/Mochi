import { Application, Ticker, type DisplayObject } from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display/cubism4';

// pixi.js 与 pixi-live2d-display 各自依赖一份 @pixi/*：运行时等价，类型声明不互通，故用断言桥接
type RegisterTickerArg = Parameters<typeof Live2DModel.registerTicker>[0];
Live2DModel.registerTicker(Ticker as unknown as RegisterTickerArg);

export interface StageOptions {
  /** 缩放到窗口的比例上限（留一点边距） */
  fitPadding?: number;
}

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
 * 只负责"把模型显示出来 + 播动作"，不做情绪计算：
 * 情绪由后端权威产出，前端只消费 ``performance.cue``。
 */
export class Live2DStage {
  private model: Live2DModel | null = null;
  private readonly app: Application;
  private readonly padding: number;

  constructor(app: Application, options: StageOptions = {}) {
    this.app = app;
    this.padding = options.fitPadding ?? 0.94;
  }

  get isReady(): boolean {
    return this.model !== null;
  }

  /** 模型可用的动作组名（用于调试面板） */
  getMotionNames(): string[] {
    const definitions = this.model?.internalModel.motionManager.definitions;
    if (!definitions) return [];
    return Object.keys(definitions).sort();
  }

  hasMotion(name: string): boolean {
    return this.getMotionNames().includes(name);
  }

  get expressionCount(): number {
    const manager = this.model?.internalModel.motionManager.expressionManager;
    return manager?.definitions?.length ?? 0;
  }

  playExpression(index: number): boolean {
    if (!this.model) return false;
    try {
      this.model.expression(index);
      return true;
    } catch (error) {
      console.warn('[live2d] 表情播放失败:', index, error);
      return false;
    }
  }

  async load(modelUrl: string): Promise<void> {
    const model = await Live2DModel.from(modelUrl, { autoInteract: false });
    this.model = model;
    patchPixi6Interaction(model);
    patchPixi6Interaction(this.app.stage);
    model.anchor.set(0.5, 0.5);
    this.app.stage.addChild(model as unknown as DisplayObject);
    this.layout();
    // 进入待机（qiye_10 的 idle 组默认循环）
    this.playMotion('idle', 'normal');
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

  /**
   * 点击反馈（计划书 5.6.6 的 S2 子集）：
   * 上半部分视为摸头，下半部分视为戳身体；
   * 模型没有动作组时退回表情反馈，避免"点了没反应"。
   */
  reactToTap(relativeY: number): void {
    const motion = relativeY < 0.45 ? 'touch_head' : 'touch_body';
    if (this.hasMotion(motion)) {
      this.playMotion(motion, 'high');
      return;
    }
    if (this.expressionCount > 0) {
      this.playExpression(relativeY < 0.45 ? 0 : 1);
    }
  }

  playMotion(name: string, priority: 'normal' | 'high' = 'normal'): boolean {
    const model = this.model;
    if (!model) return false;
    try {
      // pixi-live2d-display 的 priority：1 normal / 2 high / 3 force
      model.motion(name, 0, priority === 'high' ? 2 : 1);
      return true;
    } catch (error) {
      console.warn('[live2d] 动作播放失败:', name, error);
      return false;
    }
  }

  destroy(): void {
    if (!this.model) return;
    this.app.stage.removeChild(this.model as unknown as DisplayObject);
    this.model.destroy();
    this.model = null;
  }
}
