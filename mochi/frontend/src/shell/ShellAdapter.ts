/**
 * 桌面壳抽象（计划书 5.7.5，Plan B 对冲）。
 * 前端零 Tauri 依赖：所有窗口操作经此接口，切换 Electron 只需新增一个实现。
 */
export interface WindowPosition {
  x: number;
  y: number;
  /** DPI 缩放（物理像素 / 逻辑像素），恢复位置时用得上 */
  scale?: number;
  /** 所在显示器名（计划书 9.2.3：多显示器下标错屏幕） */
  display?: string | null;
}

export interface ShellAdapter {
  /** 是否运行在原生壳里：浏览器下为 false，用于跳过"窗口位置持久化"等桌面专属逻辑 */
  readonly isDesktop: boolean;
  setAlwaysOnTop(value: boolean): Promise<void>;
  setClickThrough(value: boolean): Promise<void>;
  startDragging(): Promise<void>;
  setPosition(x: number, y: number): Promise<void>;
  getPosition(): Promise<WindowPosition>;
  minimizeToTray(): Promise<void>;
  show(): Promise<void>;
  hide(): Promise<void>;
  setAutostart(value: boolean): Promise<void>;
  getAutostart(): Promise<boolean>;
  quit(): Promise<void>;
}
