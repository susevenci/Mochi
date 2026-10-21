import type { ShellAdapter, WindowPosition } from './ShellAdapter';

/** 浏览器开发用空实现：所有窗口操作 no-op，保证前端可在纯浏览器下调试。 */
export class WebAdapter implements ShellAdapter {
  readonly isDesktop = false;

  async setAlwaysOnTop(): Promise<void> {}

  async setClickThrough(): Promise<void> {}

  async startDragging(): Promise<void> {}

  async setPosition(): Promise<void> {}

  async getPosition(): Promise<WindowPosition> {
    return { x: 0, y: 0 };
  }

  async minimizeToTray(): Promise<void> {}

  async show(): Promise<void> {}

  async hide(): Promise<void> {}

  async setAutostart(): Promise<void> {}

  async quit(): Promise<void> {}
}
