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
  // R1 sprint E：cornerstone3D 的 dicom-image-loader 内部 worker 使用 ESM
  // 动态加载 codec 包；Vite 默认 worker.format='iife' 不支持 code-splitting，
  // 必须显式切到 'es' 才能 build 通过
  worker: {
    format: 'es',
  },
  optimizeDeps: {
    // 强制预打包 dicom-image-loader 全套：codec 包是 UMD/emscripten 产物，
    // 需要 vite 的 commonjs 插件转 ESM 才能正常 default import。
    // dev 模式下 vite 不会自动追踪 dynamic import 的子依赖，必须显式列出
    // 每个 codec 包，否则首次解码 .dcm 时会报 "no default export"
    include: [
      '@cornerstonejs/dicom-image-loader',
      '@cornerstonejs/codec-charls',
      '@cornerstonejs/codec-charls/decode',
      '@cornerstonejs/codec-charls/decodewasmjs',
      '@cornerstonejs/codec-libjpeg-turbo-8bit',
      '@cornerstonejs/codec-openjpeg',
      '@cornerstonejs/codec-openjph',
    ],
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['node_modules', 'dist'],
  },
})
