/**
 * 嵌入模式状态存储（store/embedStore.ts）
 *
 * 用来在 WorkbenchPage 等共享组件里判断"当前是不是嵌入模式 / HIS 引用"。
 * EmbedWorkbenchPage 加载时写入，WorkbenchPage 可读但不改。
 *
 * persist 用 sessionStorage：
 *   - 刷新页面 → 状态保留（医生 F5 工作台不丢嵌入态）
 *   - 关 tab / 关浏览器 → 状态清除（下次必须从 /embed 重新进，符合"4h 短暂会话"语义）
 *   - 跨 tab 不共享（嵌入会话本来就是单 tab 单医生）
 *   - SaaS 用户开新 tab 是干净 session，不受残留影响
 */
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

export interface EmbedSession {
  encounter_id: string
  patient_id: string | null
  patient_name: string | null
  visit_type: string
  is_first_visit: boolean
  his_ref: {
    his_brand: string
    hospital_code: string
    his_patient_no: string
    his_visit_no?: string | null
  }
}

interface EmbedState {
  /** true = 当前是金算盘等 HIS 嵌入模式 */
  isEmbed: boolean
  session: EmbedSession | null
  setEmbed: (session: EmbedSession) => void
  clearEmbed: () => void
}

export const useEmbedStore = create<EmbedState>()(
  persist(
    set => ({
      isEmbed: false,
      session: null,
      setEmbed: session => set({ isEmbed: true, session }),
      clearEmbed: () => set({ isEmbed: false, session: null }),
    }),
    {
      name: 'mediscribe-embed',
      // sessionStorage：刷新保留，关 tab 自动失效
      storage: createJSONStorage(() => sessionStorage),
    }
  )
)
