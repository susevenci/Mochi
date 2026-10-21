interface InjectedConfig {
  port?: number;
  token?: string;
}

declare global {
  interface Window {
    /** Tauri 通过 IPC 注入（计划书 5.7.4 第 5 步）。 */
    __MOCHI__?: InjectedConfig;
  }
}

export interface RuntimeConfig {
  wsUrl: string;
  token: string;
}

export function resolveConfig(): RuntimeConfig {
  const injected = window.__MOCHI__;
  if (injected?.port) {
    return {
      wsUrl: `ws://127.0.0.1:${injected.port}/ws`,
      token: injected.token ?? '',
    };
  }
  const port = import.meta.env.VITE_SERVER_PORT ?? '8765';
  return {
    wsUrl: `ws://127.0.0.1:${port}/ws`,
    token: import.meta.env.VITE_SERVER_TOKEN ?? '',
  };
}
