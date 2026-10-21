import { defineConfig } from 'vite';

export default defineConfig({
  // 相对 base：打包后由 Tauri 以 file/asset 协议加载
  base: './',
  server: {
    port: 5173,
    strictPort: true,
    // 后端提供 API 与 Live2D 静态资源；开发期经 proxy 走同源，避免 CORS
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      '/live2d': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
  build: {
    target: 'chrome110',
    outDir: 'dist',
    emptyOutDir: true,
  },
});
