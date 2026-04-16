import axios from 'axios'
import { message } from 'antd'
import { useAuthStore } from '@/store/authStore'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

// 请求拦截：自动附加 Token
api.interceptors.request.use(config => {
  const { token } = useAuthStore.getState()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截：统一错误处理
api.interceptors.response.use(
  response => response.data,
  error => {
    const status: number | undefined = error.response?.status
    const requestUrl: string = error.config?.url || ''
    const isLoginRequest = requestUrl.includes('/auth/login')

    if (status === 401 && !isLoginRequest) {
      // Token 失效 → 清除登录态并跳转，不弹 toast（页面即将刷新）
      useAuthStore.getState().clearAuth()
      window.location.href = '/login'
      return Promise.reject(error.response?.data || error)
    }

    if (status === 403) {
      message.error('权限不足，无法执行此操作')
    } else if (status === 404) {
      // 404 一般由调用方决定是否提示，这里只记录，不弹 toast
      console.warn(`[api] 404 Not Found: ${requestUrl}`)
    } else if (status != null && status >= 500) {
      message.error('服务器内部错误，请稍后重试或联系管理员')
      console.error(`[api] ${status} Server Error: ${requestUrl}`, error.response?.data)
    } else if (!status) {
      // 网络断连或超时
      message.error('网络连接失败，请检查网络后重试')
    }

    return Promise.reject(error.response?.data || error)
  }
)

export default api
