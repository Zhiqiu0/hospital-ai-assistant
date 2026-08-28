/**
 * API 客户端配置（services/api.ts）
 *
 * 基于 axios 封装全局 HTTP 客户端：
 *   - baseURL: /api/v1（由 Vite proxy 转发到后端 :8010）
 *   - timeout: 120s（AI 生成/质控接口耗时较长）
 *   - 请求拦截：从 zustand authStore 自动读取 token 附加到 Authorization 头
 *   - 响应拦截：统一处理常见错误状态码：
 *       401 → 清除登录态 + 跳转 /login（除登录请求本身外）
 *       403 → 弹 toast "权限不足"
 *       404 → 仅 console.warn，由调用方决定是否显示提示
 *       5xx → 弹 toast "服务器内部错误"
 *       网络断连 → 弹 toast "网络连接失败"
 *   - 响应拦截中 response.data 被直接返回，调用方无需写 .data 解包
 */

import axios from 'axios'
import { message } from '@/services/messageBridge'
import { useAuthStore } from '@/store/authStore'
import { captureAxiosError } from '@/sentry'
import { sanitizeUrlForLog } from '@/services/urlSanitize'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

// 上次成功请求的时间戳（毫秒）—— 诊断"网络断连"时输出"距上次成功 N 秒前"，
// 帮助判断是不是 HTTP/2 stale connection（典型特征：刚刷新过、间隔 > 75s 后第一次）。
// 全局单例可观察值，不需要响应式。
let lastSuccessAt = 0

// 请求拦截：自动附加 JWT Token（从 zustand 持久化 store 读取）
api.interceptors.request.use(config => {
  const { token } = useAuthStore.getState()
  if (token) config.headers.Authorization = `Bearer ${token}`
  // 同步 AI 端点超时放宽到 300s 对齐 nginx（2026-08-28 体检）：
  // LLM 单次调用上限 270s，全局 120s 会让前端先报错、后端继续跑完照常计费，
  // 医生重试等于双份烧钱。SSE 端点走 fetch 不受本超时影响；
  // 调用方显式传 timeout 时不覆盖。
  if (config.url?.startsWith('/ai/') && config.timeout === 120000) {
    config.timeout = 300000
  }
  return config
})

// 响应拦截：统一错误处理
api.interceptors.response.use(
  // 成功响应直接返回 data，调用方无需 .data 解包
  response => {
    // 记录最近一次成功请求时间，用于诊断"网络断连"是不是 stale connection
    lastSuccessAt = Date.now()
    return response.data
  },
  error => {
    const status: number | undefined = error.response?.status
    const requestUrl: string = error.config?.url || ''
    const isLoginRequest = requestUrl.includes('/auth/login')

    if (status === 401 && !isLoginRequest) {
      // Token 失效或未登录 → 清除登录态并跳转，不弹 toast（页面即将刷新）
      useAuthStore.getState().clearAuth()
      window.location.href = '/login'
      return Promise.reject(error.response?.data ?? error)
    }

    if (status === 403) {
      // 首登强改密（2026-08-13）：后端对未改密账号一律 403 并带此头。
      // 这里置位让全局弹窗弹出，而不是弹"权限不足"——那会让医生以为账号没开通。
      // 兼顾老会话：localStorage 里的登录态可能还没有 must_change_password 字段。
      if (error.response?.headers?.['x-must-change-password'] === '1') {
        useAuthStore.getState().setMustChangePassword(true)
      } else {
        message.error('权限不足，无法执行此操作')
      }
    } else if (status === 404) {
      // 404 由调用方决定是否提示（有些 404 是正常业务流程），这里只记录
      console.warn(`[api] 404 Not Found: ${sanitizeUrlForLog(requestUrl)}`)
    } else if (status != null && status >= 500) {
      message.error('服务器内部错误，请稍后重试或联系管理员')
      console.error(
        `[api] ${status} Server Error: ${sanitizeUrlForLog(requestUrl)}`,
        error.response?.data
      )
    } else if (!status) {
      // status 为 undefined：网络断连、请求超时或 CORS 错误
      // ── 诊断日志（2026-05-25 治本辅助）──────────────────────────────
      // 用户报"intermittent 网络失败、刷新就好"反复出现，服务端日志全干净，
      // 强烈疑似 HTTP/2 stale connection 复用。这里输出结构化诊断，下次复现
      // 时医生 F12 一翻就能告诉运维：URL/code/距上次成功多少秒/导航历史。
      // URL 已 sanitize（去 uuid / 长 hex / 纯数字 ID / query string）防 PHI。
      const sanitizedUrl = sanitizeUrlForLog(requestUrl)
      const sinceLastSuccess =
        lastSuccessAt > 0 ? `${Math.round((Date.now() - lastSuccessAt) / 1000)}s ago` : 'never'
      const errCode = (error as { code?: string }).code || 'unknown'
      const errMsg = (error as { message?: string }).message || ''
      console.error(
        `[api 网络断连] url=${sanitizedUrl} method=${(error.config?.method || 'GET').toUpperCase()} code=${errCode} msg="${errMsg}" lastSuccess=${sinceLastSuccess} navType=${(performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined)?.type || 'unknown'} online=${navigator.onLine}`
      )
      // 超时与断网分文案（2026-08-28 弱网审计）：ECONNABORTED 是"网络通、
      // 服务器慢"——引导医生"立即重试"只会加倍压服务器，且把运维排查方向
      // 带偏成网络问题
      if (errCode === 'ECONNABORTED') {
        message.error('服务器响应超时（网络正常），请稍候片刻再试')
      } else {
        message.error('网络连接失败，请检查网络后重试')
      }
    }

    // 上报到 Sentry：网络错误 / 5xx / 401（非登录请求） 都值得追溯
    // 403/404 不报，业务噪音；DSN 未配时 captureAxiosError 内部 no-op
    const shouldReport = !status || status >= 500 || (status === 401 && !isLoginRequest)
    if (shouldReport) {
      captureAxiosError(error)
    }

    // 附加式保留 HTTP 状态码（2026-08-11 审计修复）：原先 reject error.response?.data
    // 会丢掉 status，调用方（如 useAutoSaveDraft 的 409 乐观锁冲突分支）永远读不到
    // status，冲突检测形同虚设。这里在 data 是对象时附加 status（不覆盖 data 已有的
    // 同名字段），对只读 detail 的旧调用方零破坏。
    const data = error.response?.data
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      return Promise.reject({ status, ...data })
    }
    return Promise.reject(data ?? error)
  }
)

export default api
