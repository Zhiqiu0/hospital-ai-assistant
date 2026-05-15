/// <reference types="vite/client" />

/**
 * Vite 环境变量类型声明
 *
 * 所有 VITE_* 前缀的变量都会被 Vite 在 build 时 inline 到 bundle，
 * 这里给 TypeScript 提供类型支持，避免 import.meta.env.VITE_X 报错。
 */
interface ImportMetaEnv {
  readonly VITE_SENTRY_DSN?: string
  readonly VITE_SENTRY_ENVIRONMENT?: string
  readonly VITE_SENTRY_RELEASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
