import type { ShellAdapter, WindowPosition } from './ShellAdapter';

type InvokeFn = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;

interface TauriInternals {
  invoke?: InvokeFn;
}

/**
 * Tauri 实现。通过 ``window.__TAURI_INTERNALS__.invoke`` 调用 Rust 命令，
 * 不引入 @tauri-apps/api 依赖，保证浏览器构建零负担。
 * Rust 侧命令名与 desktop/src-tauri/src/window.rs 一一对应（S5 落地）。
 */
export class TauriAdapter implements ShellAdapter {
  readonly isDesktop = true;

  private invoke(): InvokeFn {
    const internals = (window as unknown as { __TAURI_INTERNALS__?: TauriInternals })
      .__TAURI_INTERNALS__;
    if (!internals?.invoke) {
      throw new Error('Tauri runtime not available');
    }
    return internals.invoke;
  }

  async setAlwaysOnTop(value: boolean): Promise<void> {
    await this.invoke()('set_always_on_top', { value });
  }

  async setClickThrough(value: boolean): Promise<void> {
    await this.invoke()('set_click_through', { value });
  }

  async startDragging(): Promise<void> {
    await this.invoke()('start_dragging');
  }

  async setPosition(x: number, y: number): Promise<void> {
    await this.invoke()('set_position', { x, y });
  }

  async getPosition(): Promise<WindowPosition> {
    return (await this.invoke()('get_position')) as WindowPosition;
  }

  async minimizeToTray(): Promise<void> {
    await this.invoke()('minimize_to_tray');
  }

  async show(): Promise<void> {
    await this.invoke()('show_window');
  }

  async hide(): Promise<void> {
    await this.invoke()('hide_window');
  }

  async setAutostart(value: boolean): Promise<void> {
    await this.invoke()('set_autostart', { value });
  }

  async quit(): Promise<void> {
    await this.invoke()('quit_app');
  }
}
