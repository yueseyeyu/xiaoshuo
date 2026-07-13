import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 所有 /api 请求代理到 FastAPI 后端
      '/api': {
        target: 'http://127.0.0.1:8089',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    // 生产构建时生成 source map，方便调试
    sourcemap: true,
  },
})
