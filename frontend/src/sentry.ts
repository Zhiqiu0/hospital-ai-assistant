/**
 * Sentry 前端初始化（src/sentry.ts）
 *
 * 与后端 backend/app/core/sentry_init.py 配套，共用同一个 Sentry 项目：
 *   - 同样的 DSN（前端独立 DSN，后端独立 DSN，但 organization 一样）
 *   - 同样的 release（CI deploy 注入 git SHA），前后端 event 可按 release 关联
 *   - 同样的 environment（development / production）
 *
 * 配置原则（医疗合规）：
 *   1. 仅当 VITE_SENTRY_DSN 非空时启用，本地开发默认跳过
 *   2. **关闭 Session Replay**：医疗系统不能录屏（病历正文、患者姓名会被录进去）
 *   3. **关闭 Profiling**：不上报性能 trace（采样率 0）
 *   4. beforeSend 兜底脱敏：删除请求 body / 表单字段中含 password / id_card / 病历正文的部分
 *   5. 仅捕获未处理异常 + axios 主动上报，不抓 console.log 噪音
 *
 * 使用方式：
 *   在 main.tsx 第一行 import 后立即调用 initSentry()，必须早于 ReactDOM.createRoot。
 *   axios 拦截器在 src/services/api.ts 通过 Sentry.captureException 主动上报失败请求。
 */

import * as Sentry from '@sentry/react'

// ── 敏感字段名单（兜底脱敏用，前缀匹配 + 包含匹配）─────────────────────────────
// 任何 event 里如果 extra/contexts 含这些字段都会被替换为 [scrubbed]
const SENSITIVE_KEYS = [
  'password',
  'pwd',
  'token',
  'authorization',
  'id_card',
  'idcard',
  'idCard',
  'phone',
  'mobile',
  // 病历正文 / 主诉 / 诊断 / 患者姓名 这些字段在前端通常以 record* / patient* 命名
  'record',
  'patient',
  'content',
]

/**
 * 判断字段名是否敏感（小写 substring 匹配）
 */
function isSensitiveKey(key: string): boolean {
  const lower = key.toLowerCase()
  return SENSITIVE_KEYS.some(s => lower.includes(s))
}

/**
 * 递归脱敏对象：把任意层级里命中 SENSITIVE_KEYS 的字段替换为 [scrubbed]
 * 深度限制 3 层，避免循环引用 / 超大对象（如 axios config）卡死序列化
 */
function scrubObject(obj: unknown, depth = 0): unknown {
  if (depth > 3 || obj == null) return obj
  if (Array.isArray(obj)) return obj.map(item => scrubObject(item, depth + 1))
  if (typeof obj !== 'object') return obj
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    if (isSensitiveKey(k)) {
      out[k] = '[scrubbed]'
    } else {
      out[k] = scrubObject(v, depth + 1)
    }
  }
  return out
}

/**
 * beforeSend 钩子：每个 event 发送前最后一次清洗
 *
 * Sentry SDK 默认不抓 form input 的 value，但开发者主动 setExtra / setContext
 * 仍可能把敏感字段塞进 event。这里做兜底防线。
 *
 * 类型签名：Sentry SDK 2.x 的 beforeSend 接 ErrorEvent 类型（不是泛 Event），
 * 返回 ErrorEvent | null。返回 null 等于丢弃事件不发送。
 */
function scrubEvent(event: Sentry.ErrorEvent): Sentry.ErrorEvent {
  if (event.extra) {
    event.extra = scrubObject(event.extra) as Record<string, unknown>
  }
  if (event.contexts) {
    event.contexts = scrubObject(event.contexts) as Record<string, Sentry.Context>
  }
  // request.data 也清掉（如果 SDK 抓了的话）
  if (event.request?.data) {
    event.request.data = '[scrubbed]'
  }
  // 请求 query 里可能带 username 等，保留 url 路径用于聚合，清掉 query
  if (event.request?.query_string) {
    event.request.query_string = '[scrubbed]'
  }
  return event
}

/**
 * 初始化 Sentry。DSN 为空时直接跳过，本地开发零侵入。
 *
 * 环境变量：
 *   - VITE_SENTRY_DSN：项目 DSN，空 = 不启用
 *   - VITE_SENTRY_ENVIRONMENT：development / production
 *   - VITE_SENTRY_RELEASE：发布版本号（CI 注入 git SHA）
 */
export function initSentry(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined
  if (!dsn) {
    // 本地开发常态：不上报，也不打 warning（避免控制台噪音）
    return
  }

  Sentry.init({
    dsn,
    environment: (import.meta.env.VITE_SENTRY_ENVIRONMENT as string) || 'unknown',
    release: (import.meta.env.VITE_SENTRY_RELEASE as string) || undefined,

    // ── Tunnel：绕过 ad-blocker / 医院出口防火墙 ─────────────────
    // 2026-05-25 治本：医生浏览器装 ad-blocker（uBlock 等）或医院出口
    // 防火墙会拦截 *.ingest.sentry.io 海外域名，envelope 上报丢失。
    // tunnel 让上报走自己后端 /api/v1/sentry-tunnel 同源代理转发到上游，
    // 同源域名 ad-blocker 不识别就放行。
    // 后端校验：DSN host whitelist + rate limit + size limit + 5s 超时
    // 详见 backend/app/api/v1/sentry_tunnel.py
    tunnel: '/api/v1/sentry-tunnel',

    // ── 采样率 ─────────────────────────────────────────────────────
    // 性能 trace 一律不开（trace 会附带 URL / form 提交内容，避免泄露）
    tracesSampleRate: 0,
    // Session Replay：医疗系统**严禁录屏**，写死 0
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,

    // ── PII 防线 ───────────────────────────────────────────────────
    // 不抓默认 PII：cookies / IP / user agent header 里的敏感部分
    sendDefaultPii: false,
    // 兜底脱敏（删 request.data / extra 里的敏感字段）
    beforeSend: scrubEvent,

    // ── 噪音过滤 ───────────────────────────────────────────────────
    // 浏览器扩展的报错 / 老旧浏览器 chunk load 失败 不算业务 bug
    ignoreErrors: [
      // 浏览器扩展常见噪音
      'ResizeObserver loop limit exceeded',
      'ResizeObserver loop completed with undelivered notifications',
      // 用户网络抖动导致的 chunk 加载失败（业务无关）
      'ChunkLoadError',
      'Loading chunk',
      'Loading CSS chunk',
    ],

    // ── 集成 ───────────────────────────────────────────────────────
    // 用默认集成即可（自动捕获 unhandled error / unhandled rejection / console.error）
    // 显式关掉 BrowserTracing / Replay 防止任何人后续误开
    integrations: integrations =>
      integrations.filter(i => {
        const name = i.name
        return name !== 'BrowserTracing' && name !== 'Replay' && name !== 'ReplayCanvas'
      }),
  })
}

/**
 * 主动上报一个 axios 请求失败（在 api.ts 拦截器调用）
 *
 * 比 Sentry.captureException 多带几个对调试关键的 tag/extra：
 *   - tag http.status：方便按状态码聚合
 *   - tag http.url：哪个接口失败
 *   - extra：error.code / error.message / 响应 detail（脱敏后）
 *
 * 注：这里只接 axios error，调用方负责传完整 error 对象。
 */
export function captureAxiosError(error: {
  message?: string
  code?: string
  config?: { url?: string; method?: string }
  response?: { status?: number; data?: unknown }
}): void {
  // DSN 没配 → Sentry 没 init，captureException 是 no-op，无副作用
  Sentry.withScope(scope => {
    const status = error.response?.status
    const url = error.config?.url || ''
    const method = (error.config?.method || 'GET').toUpperCase()

    scope.setTag('http.status', status?.toString() || 'network_error')
    scope.setTag('http.url', url)
    scope.setTag('http.method', method)

    scope.setExtra('errorCode', error.code)
    scope.setExtra('errorMessage', error.message)
    // response.data 经 scrubEvent 二次脱敏；这里仅保留状态码与 detail 文本
    if (error.response?.data && typeof error.response.data === 'object') {
      const data = error.response.data as Record<string, unknown>
      scope.setExtra('responseDetail', data.detail || '[no detail]')
    }

    // 用 captureException 上报；如果 error 不是真正的 Error 实例，包一层
    const exc = error instanceof Error ? error : new Error(`HTTP ${status || 'NETWORK'} ${method} ${url}`)
    Sentry.captureException(exc)
  })
}
