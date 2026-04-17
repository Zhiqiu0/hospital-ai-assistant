/**
 * 认证状态 Store（store/authStore.ts）
 *
 * 使用 zustand + persist 中间件管理登录状态：
 *   - token:      JWT 访问令牌，由 api.ts 请求拦截器自动附加到请求头
 *   - user:       当前用户信息（id/username/real_name/role/department）
 *   - systemType: 当前工作台类型（'outpatient' 门/急诊 | 'inpatient' 住院）
 *                 影响工作台页面路由和 prompt 选择
 *
 * persist 配置：
 *   name: 'mediscribe-auth' → 存储到 localStorage，页面刷新后自动恢复登录状态
 *
 * 使用示例：
 *   const { token, user, setAuth, clearAuth } = useAuthStore()
 *   setAuth(token, user)  // 登录后调用
 *   clearAuth()           // 登出或 401 时调用
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UserInfo {
  id: string
  username: string
  real_name: string
  role: string
  department_id?: string
  department_name?: string
}

interface AuthState {
  token: string | null
  user: UserInfo | null
  /** 当前系统模式：outpatient（门/急诊）或 inpatient（住院） */
  systemType: 'outpatient' | 'inpatient'
  /** 登录后设置 token 和用户信息 */
  setAuth: (token: string, user: UserInfo) => void
  /** 登出时清空所有认证状态（同时重置 systemType 为默认值） */
  clearAuth: () => void
  /** 切换系统工作台类型（影响工作台页面路由和 AI prompt 选择） */
  setSystemType: (type: 'outpatient' | 'inpatient') => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    set => ({
      token: null,
      user: null,
      systemType: 'outpatient',
      setAuth: (token, user) => set({ token, user }),
      clearAuth: () => set({ token: null, user: null, systemType: 'outpatient' }),
      setSystemType: type => set({ systemType: type }),
    }),
    { name: 'mediscribe-auth' }
  )
)
