/**
 * 病历内容 Store（store/recordStore.ts）
 *
 * Audit Round 4 M1 拆分：负责病历正文 + AI 生成态 + 签发态。
 *
 * 职责（只管病历相关）：
 *   - recordContent（病历正文）+ recordType（门诊/住院/中医）
 *   - AI 运行态：isGenerating、isPolishing、pendingGenerate
 *   - 签发：isFinal、finalizedAt
 *
 * 不管什么：
 *   - 接诊元信息（visitType / isFirstVisit / isPatientReused / previousRecordContent）
 *     → 已经在 activeEncounterStore 里管，从那里读，避免双源
 *
 * 跨 store 联动：
 *   setRecordContent → 调用 useQCStore.markStale()，让上一轮质控结果显示"已过时"。
 *   单向依赖（record → qc），不会成环。
 *
 * 持久化（localStorage key: medassist-record）：
 *   recordContent / recordType / 签发态 持久化；
 *   isGenerating / isPolishing / pendingGenerate 是瞬态，不持久化。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { useQCStore } from './qcStore'

interface RecordState {
  // ── 病历正文 ──────────────────────────────────────────────
  recordContent: string
  recordType: string

  // ── AI 运行态（不持久化） ─────────────────────────────────
  isGenerating: boolean
  isPolishing: boolean
  /** 等待 inquiry 保存完成后再触发生成 */
  pendingGenerate: boolean

  // ── 签发 ──────────────────────────────────────────────────
  isFinal: boolean
  /** 签发时刻（zh-CN 本地化字符串），与 isFinal 联动 */
  finalizedAt: string | null

  // ── auto-save 状态（5 秒防抖保存到后端 draft） ───────────
  /** 最后一次 auto-save 成功时间戳（毫秒），0=从未保存。状态条据此显示"刚刚保存"等。 */
  recordSavedAt: number

  // ── actions ───────────────────────────────────────────────
  setRecordContent: (content: string) => void
  setRecordType: (type: string) => void
  setGenerating: (v: boolean) => void
  setPolishing: (v: boolean) => void
  setPendingGenerate: (v: boolean) => void
  setFinal: (v: boolean) => void
  setRecordSavedAt: (ts: number) => void
  /** 在病历末尾追加一段（带空行分隔，AI 续写流式输出用） */
  appendToRecord: (text: string) => void
  /** 重置到初始状态（切换接诊 / 登出时调用） */
  reset: () => void
}

export const useRecordStore = create<RecordState>()(
  persist(
    set => ({
      recordContent: '',
      recordType: 'outpatient',

      isGenerating: false,
      isPolishing: false,
      pendingGenerate: false,

      isFinal: false,
      finalizedAt: null,

      recordSavedAt: 0,

      setRecordContent: content => {
        set({ recordContent: content })
        // 病历内容变化时通知 qcStore：上一轮质控结果已过时（按钮变"重新质控"）
        useQCStore.getState().markStale()
      },

      setRecordType: type => set({ recordType: type }),

      setGenerating: v => set({ isGenerating: v }),
      setPolishing: v => set({ isPolishing: v }),
      setPendingGenerate: v => set({ pendingGenerate: v }),

      setFinal: v =>
        set({ isFinal: v, finalizedAt: v ? new Date().toLocaleString('zh-CN') : null }),

      setRecordSavedAt: ts => set({ recordSavedAt: ts }),

      appendToRecord: text =>
        set(state => ({
          recordContent: state.recordContent ? state.recordContent + '\n\n' + text : text,
        })),

      reset: () =>
        set({
          recordContent: '',
          recordType: 'outpatient',
          isGenerating: false,
          isPolishing: false,
          pendingGenerate: false,
          isFinal: false,
          finalizedAt: null,
          recordSavedAt: 0,
        }),
    }),
    {
      name: 'medassist-record',
      // 瞬态字段（isGenerating/isPolishing/pendingGenerate）不持久化
      partialize: state => ({
        recordContent: state.recordContent,
        recordType: state.recordType,
        isFinal: state.isFinal,
        finalizedAt: state.finalizedAt,
        recordSavedAt: state.recordSavedAt,
      }),
    }
  )
)
