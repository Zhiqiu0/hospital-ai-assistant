/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiProxyTarget = process.env.MEDASSIST_API_PROXY_TARGET || 'http://localhost:8010'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
        // 开启 WebSocket 代理，供 /api/v1/ai/voice-stream 实时语音识别使用
        ws: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': '/src',
    },
  },
  // 2026-06-11 性能治本：vendor 分包。React/antd 单独成 chunk——
  // 业务代码改动不影响 vendor chunk 的 hash，医院弱网环境二次访问全走缓存。
  // cornerstone 不用列：PACS 页已改路由级懒加载，rollup 自动把它分进异步 chunk
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-antd': ['antd', '@ant-design/icons'],
        },
      },
    },
  },
  // 2026-06-11 清理：cornerstone3D 全套依赖已移除（R1 切 Orthanc 服务端渲染预览图后
  // 前端不再本地解码 DICOM，cornerstone3DInit.ts 是无引用死代码），
  // 原 worker.format='es' 和 optimizeDeps codec 预打包配置都是为它服务的，一并删除
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['node_modules', 'dist'],
  },
})
