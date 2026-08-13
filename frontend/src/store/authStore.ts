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
        clearPatientScopedData()
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

/**
 * 清空所有「跟着患者走」的本地敏感数据（2026-08-11 审计修复；2026-08-13 收口）。
 *
 * patientCache 存患者档案、voiceTranscript 存语音转写、profileEdit 存医生还没
 * 保存的既往史/过敏史草稿——都是 PHI 且都持久化在本机。不清的话，下一个在这台
 * 诊室电脑上登录的医生会看到上一个医生的患者数据，属医疗隐私事故。
 *
 * 为什么要收口成一个函数（2026-08-13 第五轮审计修复）：
 * 原先这段逻辑只写在 clearAuth 里，而「医生 A 不登出、医生 B 直接在登录页登录」
 * 走的是另一条路径（LoginPage 只调 resetAllWorkbench），根本不经过 clearAuth——
 * 于是换人登录时这些 PHI 原样留着。诊室电脑多人共用是医院常态，这条路径比正常
 * 登出更常见。收口后两条路径都调同一个函数，不会再漏。
 *
 * 注意别放进 resetAllWorkbench：后者还被急诊切换/取消接诊等非换人路径调用，
 * 在那里清语音草稿会丢医生未上传的内容，违背 voiceTranscriptStore 的设计。
 *
 * 动态 import 避免 store 顶层循环依赖。
 */
export function clearPatientScopedData(): void {
  void import('@/store/voiceTranscriptStore').then(m =>
    m.useVoiceTranscriptStore.getState().clearAll()
  )
  void import('@/store/patientCacheStore').then(m => m.usePatientCacheStore.getState().clear())
  void import('@/store/aiWrittenFieldsStore').then(m =>
    m.useAiWrittenFieldsStore.getState().clear()
  )
  void import('@/store/patientProfileEditStore').then(m =>
    m.usePatientProfileEditStore.getState().reset()
  )
}
