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
import { message } from 'antd'
import { useAuthStore } from '@/store/authStore'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

// 请求拦截：自动附加 JWT Token（从 zustand 持久化 store 读取）
api.interceptors.request.use(config => {
  const { token } = useAuthStore.getState()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截：统一错误处理
api.interceptors.response.use(
  // 成功响应直接返回 data，调用方无需 .data 解包
  response => response.data,
  error => {
    const status: number | undefined = error.response?.status
    const requestUrl: string = error.config?.url || ''
    const isLoginRequest = requestUrl.includes('/auth/login')

    if (status === 401 && !isLoginRequest) {
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
      message.error('网络连接失败，请检查网络后重试')
    }

    return Promise.reject(error.response?.data || error)
  }
)

export default api
