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
import { useEmbedStore } from '@/store/embedStore'
import { captureAxiosError } from '@/sentry'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

// 上次成功请求的时间戳（毫秒）—— 诊断"网络断连"时输出"距上次成功 N 秒前"，
// 帮助判断是不是 HTTP/2 stale connection（典型特征：刚刷新过、间隔 > 75s 后第一次）。
// 全局单例可观察值，不需要响应式。
let lastSuccessAt = 0

/**
 * 把 URL 路径中的常见 ID（uuid / 长 hex / 中文姓名拼接段）替换成占位符，
 * 防止 PHI 进 console（医生 F12 可能截图发群里）。
 * 保留 endpoint 结构便于聚合分析（如 /encounters/:id/quick-start）。
 */
function sanitizeUrlForLog(url: string): string {
  if (!url) return ''
  return (
    url
      // UUID（含/不含连字符）
      .replace(
        /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g,
        ':uuid'
      )
      // 长 hex（>=24 字符，覆盖患者外部码 / sha 等）
      .replace(/\b[0-9a-fA-F]{24,}\b/g, ':hex')
      // 纯数字 ID（连续 6 位以上，避免误伤短数字如分页）
      .replace(/\/\d{6,}/g, '/:num')
      // query string（可能含患者姓名 / 关键词）
      .replace(/\?.*$/, '?[scrubbed]')
  )
}

// 请求拦截：自动附加 JWT Token（从 zustand 持久化 store 读取）
api.interceptors.request.use(config => {
  const { token } = useAuthStore.getState()
  if (token) config.headers.Authorization = `Bearer ${token}`
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
      // 嵌入模式（HIS 桌面 Agent 拉起）下 401 大概率是 4h embed_token 过期：
      // 跳登录页只会让医生一头雾水（嵌入会话没有账号密码概念），
      // 改为跳 /embed?expired=1 给出"请回 HIS 重新触发"的明确指引（2026-06-11 治本）
      if (useEmbedStore.getState().isEmbed) {
        useEmbedStore.getState().clearEmbed()
        useAuthStore.getState().clearAuth()
        window.location.href = '/embed?expired=1'
        return Promise.reject(error.response?.data || error)
      }
      // Token 失效或未登录 → 清除登录态并跳转，不弹 toast（页面即将刷新）
      useAuthStore.getState().clearAuth()
      window.location.href = '/login'
      return Promise.reject(error.response?.data || error)
    }

    if (status === 403) {
      message.error('权限不足，无法执行此操作')
    } else if (status === 404) {
      // 404 由调用方决定是否提示（有些 404 是正常业务流程），这里只记录
      console.warn(`[api] 404 Not Found: ${requestUrl}`)
    } else if (status != null && status >= 500) {
      message.error('服务器内部错误，请稍后重试或联系管理员')
      console.error(`[api] ${status} Server Error: ${requestUrl}`, error.response?.data)
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
      message.error('网络连接失败，请检查网络后重试')
    }

    // 上报到 Sentry：网络错误 / 5xx / 401（非登录请求） 都值得追溯
    // 403/404 不报，业务噪音；DSN 未配时 captureAxiosError 内部 no-op
    const shouldReport = !status || status >= 500 || (status === 401 && !isLoginRequest)
    if (shouldReport) {
      captureAxiosError(error)
    }

    return Promise.reject(error.response?.data || error)
  }
)

export default api
