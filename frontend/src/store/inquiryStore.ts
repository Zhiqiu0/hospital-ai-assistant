/**
 * 问诊数据 Store（store/inquiryStore.ts）
 *
 * Audit Round 4 M1 拆分：负责工作台问诊面板的所有字段和操作。
 *
 * 职责：
 *   - 持有 InquiryData（38+ 字段）的当前值
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
import { persist } from 'zustand/middleware'
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
}

export const useInquiryStore = create<InquiryState>()(
  persist(
    set => ({
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
      // 全部字段都持久化，刷新页面后表单数据不丢
      partialize: state => ({
        inquiry: state.inquiry,
        inquirySavedAt: state.inquirySavedAt,
      }),
    }
  )
)
