/**
 * 问诊数据 Store（store/inquiryStore.ts）
 *
 * Audit Round 4 M1 拆分：负责工作台问诊面板的所有字段和操作。
 *
 * 职责：
 *   - 持有 InquiryData（43 字段）的当前值
 *   - inquirySavedAt 时间戳（用于"未保存/已保存"角标 + 表单同步触发）
 *   - 4 个细粒度 setter：整个表单替换 / 部分字段更新 / 追加病史 / 设置初步印象
 *
 * 持久化（localStorage key: medassist-inquiry）：
 *   inquiry / inquirySavedAt 全部持久化，刷新页面后医生填到一半的内容不丢。
 *
 * 切换接诊清空机制：
 *   activeEncounterStore.setCurrentEncounter 检测到 encounterId 变化时，
 *   会主动调用本 store 的 reset()，避免上一个患者的数据污染到下一个。
 */

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { safeLocalStorage } from '@/store/safeStorage'
import { InquiryData, defaultInquiry } from './types'

interface InquiryState {
  /** 当前接诊的全部问诊字段 */
  inquiry: InquiryData
  /** 最后一次"主动保存"的时间戳（毫秒）。0=从未保存。setInquiry 会更新它，updateInquiryFields 不会 */
  inquirySavedAt: number

  /** 整体替换 inquiry，并打"已保存"标记（手动点保存按钮时用） */
  setInquiry: (data: InquiryData) => void
  /** 部分字段更新（不打"已保存"标记，仅同步本地状态，如 AI 流式生成期间） */
  updateInquiryFields: (data: InquiryData) => void
  /** 在现病史末尾追加一段笔记（AI 语音转写、追问回答等场景） */
  appendInquiryNote: (note: string) => void
  /** 设置初步印象（AI 诊断建议一键写入用） */
  setInitialImpression: (text: string) => void
  /** 重置到初始空状态（切换接诊或登出时调用） */
  reset: () => void
  /** 归属接诊（2026-08-28 多标签页审计）：单槽 persist 在双标签页会被互相
   *  覆盖，还原时与接诊指针对不上就必须丢弃——宁可重拉，不能把甲患者的
   *  数据拼到乙患者名下（与 recordStore.ownerEncounterId 同款守卫） */
  ownerEncounterId: string | null
  bindOwner: (encounterId: string | null) => void
  /** 归属校验：对不上即 reset+重绑，返回是否通过 */
  assertOwner: (encounterId: string) => boolean
}

export const useInquiryStore = create<InquiryState>()(
  persist(
    (set, get) => ({
      ownerEncounterId: null,
      bindOwner: encounterId => set({ ownerEncounterId: encounterId }),
      assertOwner: encounterId => {
        const owner = get().ownerEncounterId
        if (owner === encounterId) return true
        // 对不上：丢弃本槽数据并绑到当前接诊（随后由水合重新灌入真实数据）
        get().reset()
        set({ ownerEncounterId: encounterId })
        return false
      },
      inquiry: defaultInquiry,
      inquirySavedAt: 0,

      setInquiry: data => set({ inquiry: data, inquirySavedAt: Date.now() }),

      updateInquiryFields: data => set({ inquiry: data }),

      appendInquiryNote: note =>
        set(state => ({
          inquiry: {
            ...state.inquiry,
            // 现病史已有内容时换行追加，避免字段被整行覆盖
            history_present_illness: state.inquiry.history_present_illness
              ? state.inquiry.history_present_illness + '\n' + note
              : note,
          },
        })),

      setInitialImpression: text =>
        set(state => ({
          inquiry: { ...state.inquiry, initial_impression: text },
        })),

      reset: () => set({ inquiry: defaultInquiry, inquirySavedAt: 0 }),
    }),
    {
      name: 'medassist-inquiry',
      // 配额安全存储（2026-08-28 多标签页审计）：写满时降级仅内存态，
      // 不在医生每次按键的调用栈里抛 QuotaExceededError
      storage: createJSONStorage(() => safeLocalStorage),
      // 全部字段都持久化，刷新页面后表单数据不丢
      partialize: state => ({
        inquiry: state.inquiry,
        inquirySavedAt: state.inquirySavedAt,
      }),
      // 版本 + migrate（2026-08-11 审计延期项）：inquiry 是扁平多字段对象，早期
      // localStorage 里的旧结构缺少后加的字段（如中医四诊/急诊留观），rehydrate 后
      // 这些字段为 undefined，组件里 .trim() / .length 会崩。用 defaultInquiry 兜底
      // 补齐所有字段，保证任何历史版本恢复后形状完整。
      version: 1,
      migrate: (persisted: unknown) => {
        const p = persisted as { inquiry?: Partial<InquiryData>; inquirySavedAt?: number } | null
        return {
          inquiry: { ...defaultInquiry, ...(p?.inquiry ?? {}) },
          inquirySavedAt: p?.inquirySavedAt ?? 0,
        }
      },
      // 每次 rehydrate 也用默认值补齐（覆盖 version 未变但字段新增的情况）
      merge: (persisted, current) => {
        const p = persisted as { inquiry?: Partial<InquiryData>; inquirySavedAt?: number } | null
        return {
          ...current,
          inquiry: { ...defaultInquiry, ...(p?.inquiry ?? {}) },
          inquirySavedAt: p?.inquirySavedAt ?? 0,
        }
      },
    }
  )
)
