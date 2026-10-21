import { defineConfig } from 'vite';

export default defineConfig({
  // 相对 base：打包后由 Tauri 以 file/asset 协议加载
  base: './',
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    target: 'chrome110',
    outDir: 'dist',
    emptyOutDir: true,
  },
});
