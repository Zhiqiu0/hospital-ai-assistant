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

/**
 * 解码 JWT payload 并检查是否过期（不验证签名，仅客户端快速判断）
 * 过期、格式错误、缺少 exp 字段均视为已过期
 */
export function isTokenExpired(token: string): boolean {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return typeof payload.exp !== 'number' || payload.exp * 1000 < Date.now()
  } catch {
    return true
  }
}

interface UserInfo {
  id: string
  username: string
  real_name: string
  role: string
  department_id?: string
  department_name?: string
  /**
   * 是否必须先修改初始密码（2026-08-13 批量开户）。
   * 批量建号用全院统一初始密码便于分发，未改密的账号在后端被硬拦
   * （除改密/登出/查自己外一律 403），前端据此弹不可关闭的改密框。
   */
  must_change_password?: boolean
}

interface AuthState {
  token: string | null
  user: UserInfo | null
  /**
   * 上一次登录过的用户 ID（登出/401 清理时留存，持久化）。
   * 用途（2026-08-13 第二轮审计修复）：token 过期被踢回登录页后，同一医生
   * 重新登录时不该清空他自己没保存完的问诊/病历草稿；换个医生登录才必须清。
   * 只存 ID 不存任何 PHI。
   */
  lastUserId: string | null
  /** 当前系统模式：outpatient（门/急诊）或 inpatient（住院） */
  systemType: 'outpatient' | 'inpatient'
  /** 登录后设置 token 和用户信息 */
  setAuth: (token: string, user: UserInfo) => void
  /** 登出时清空所有认证状态（同时重置 systemType 为默认值） */
  clearAuth: () => void
  /** 切换系统工作台类型（影响工作台页面路由和 AI prompt 选择） */
  setSystemType: (type: 'outpatient' | 'inpatient') => void
  /** 标记「必须改密」——供 api.ts 收到后端 403 + X-Must-Change-Password 时兜底置位 */
  setMustChangePassword: (v: boolean) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    set => ({
      token: null,
      user: null,
      lastUserId: null,
      systemType: 'outpatient',
      setAuth: (token, user) => set({ token, user, lastUserId: user.id }),
      clearAuth: () => {
        // 登出/401 时清空跨患者敏感缓存（2026-08-11 审计修复）：patientCache 存着
        // 患者档案、voiceTranscript 存着语音转写，若不清，下一个登录本机的医生会
        // 看到上一个医生的患者数据（医疗隐私事故）。收口在 clearAuth 而非
        // resetAllWorkbench——后者还被急诊切换/取消接诊等非登出路径调用，在那里清
        // 语音草稿会丢医生未上传的内容，违背 voiceTranscriptStore「切患者不丢草稿」设计。
        // 动态 import 避免 store 顶层循环依赖。
        void import('@/store/voiceTranscriptStore').then(m =>
          m.useVoiceTranscriptStore.getState().clearAll()
        )
        void import('@/store/patientCacheStore').then(m =>
          m.usePatientCacheStore.getState().clear()
        )
        void import('@/store/aiWrittenFieldsStore').then(m =>
          m.useAiWrittenFieldsStore.getState().clear()
        )
        // lastUserId 刻意保留：供登录页判断"是不是同一个医生回来了"
        set({ token: null, user: null, systemType: 'outpatient' })
      },
      setSystemType: type => set({ systemType: type }),
      setMustChangePassword: v =>
        set(state => (state.user ? { user: { ...state.user, must_change_password: v } } : {})),
    }),
    {
      name: 'mediscribe-auth',
      // 应用启动时从 localStorage 恢复后，若 token 已过期则立即清除，避免假登录状态
      onRehydrateStorage: () => state => {
        if (state?.token && isTokenExpired(state.token)) {
          state.clearAuth()
        }
      },
    }
  )
)
