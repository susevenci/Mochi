/**
 * 桌面壳抽象（计划书 5.7.5，Plan B 对冲）。
 * 前端零 Tauri 依赖：所有窗口操作经此接口，切换 Electron 只需新增一个实现。
 */
export interface ShellAdapter {
  setAlwaysOnTop(value: boolean): Promise<void>;
  setClickThrough(value: boolean): Promise<void>;
  startDragging(): Promise<void>;
  setPosition(x: number, y: number): Promise<void>;
  getPosition(): Promise<{ x: number; y: number }>;
  minimizeToTray(): Promise<void>;
  show(): Promise<void>;
  hide(): Promise<void>;
  setAutostart(value: boolean): Promise<void>;
  quit(): Promise<void>;
}
