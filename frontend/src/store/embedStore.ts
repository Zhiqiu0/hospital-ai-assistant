/**
 * 嵌入模式状态存储（store/embedStore.ts）
 *
 * 用来在 WorkbenchPage 等共享组件里判断"当前是不是嵌入模式 / HIS 引用"。
 * EmbedWorkbenchPage 加载时写入，WorkbenchPage 可读但不改。
 *
 * 不 persist：嵌入会话短暂（4h token），刷新浏览器靠 URL 重新加载。
 */
import { create } from 'zustand'

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

export const useEmbedStore = create<EmbedState>(set => ({
  isEmbed: false,
  session: null,
  setEmbed: session => set({ isEmbed: true, session }),
  clearEmbed: () => set({ isEmbed: false, session: null }),
}))
