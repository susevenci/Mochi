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
  /** Tauri 下是 http://127.0.0.1:<动态端口>；浏览器开发态为空（走 Vite proxy） */
  apiBase: string;
}

export function resolveConfig(): RuntimeConfig {
  const injected = window.__MOCHI__;
  if (injected?.port) {
    return {
      wsUrl: `ws://127.0.0.1:${injected.port}/ws`,
      token: injected.token ?? '',
      apiBase: `http://127.0.0.1:${injected.port}`,
    };
  }
  // Tauri 边车启动后才确定端口与随机 token：Rust 侧导航到
  // index.html?port=...&token=...，这里优先读取查询参数。
  const params = new URLSearchParams(window.location.search);
  const queryPort = params.get('port');
  if (queryPort) {
    return {
      wsUrl: `ws://127.0.0.1:${queryPort}/ws`,
      token: params.get('token') ?? '',
      apiBase: `http://127.0.0.1:${queryPort}`,
    };
  }
  const port = import.meta.env.VITE_SERVER_PORT ?? '8765';
  return {
    wsUrl: `ws://127.0.0.1:${port}/ws`,
    token: import.meta.env.VITE_SERVER_TOKEN ?? '',
    apiBase: '',
  };
}
