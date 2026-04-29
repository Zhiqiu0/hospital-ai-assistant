/**
 * AI 建议 Store（store/aiSuggestionStore.ts）
 *
 * Audit Round 4 M1 拆分：负责三类 AI 建议——检查建议 / 追问建议 / 诊断建议。
 *
 * 职责：
 *   - examSuggestions    : AI 检查建议（基础必查 / 鉴别诊断 / 高风险）+ 已开单标记
 *   - inquirySuggestions : AI 追问建议（含选项与已勾选）
 *   - diagnosisSuggestions / appliedDiagnosis : AI 诊断建议 + 已写入病历的诊断名
 *
 * 持久化（localStorage key: medassist-ai-suggestions）：
 *   全部业务字段持久化（examSuggestions 含开单状态、inquirySuggestions 含勾选选项），
 *   isExamLoading 是瞬态不持久化。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { ExamSuggestion, InquirySuggestion, DiagnosisItem } from './types'

interface AISuggestionState {
  // ── 检查建议 ──────────────────────────────────────────────
  examSuggestions: ExamSuggestion[]
  /** 检查建议是否还在加载 */
  isExamLoading: boolean

  // ── 追问建议 ──────────────────────────────────────────────
  inquirySuggestions: InquirySuggestion[]

  // ── 诊断建议 ──────────────────────────────────────────────
  diagnosisSuggestions: DiagnosisItem[]
  /** 当前已写入病历的诊断名称（用于"已写入"高亮） */
  appliedDiagnosis: string | null

  // ── actions ───────────────────────────────────────────────
  setExamSuggestions: (items: ExamSuggestion[]) => void
  setExamLoading: (v: boolean) => void
  setInquirySuggestions: (items: InquirySuggestion[]) => void
  setDiagnosisSuggestions: (items: DiagnosisItem[]) => void
  setAppliedDiagnosis: (name: string | null) => void
  /** 重置到初始状态（切换接诊 / 登出时调用） */
  reset: () => void
}

export const useAISuggestionStore = create<AISuggestionState>()(
  persist(
    set => ({
      examSuggestions: [],
      isExamLoading: false,

      inquirySuggestions: [],

      diagnosisSuggestions: [],
      appliedDiagnosis: null,

      setExamSuggestions: items => set({ examSuggestions: items }),
      setExamLoading: v => set({ isExamLoading: v }),
      setInquirySuggestions: items => set({ inquirySuggestions: items }),
      setDiagnosisSuggestions: items => set({ diagnosisSuggestions: items }),
      setAppliedDiagnosis: name => set({ appliedDiagnosis: name }),

      reset: () =>
        set({
          examSuggestions: [],
          isExamLoading: false,
          inquirySuggestions: [],
          diagnosisSuggestions: [],
          appliedDiagnosis: null,
        }),
    }),
    {
      name: 'medassist-ai-suggestions',
      // isExamLoading 是瞬态不持久化，否则刷新后 loading 状态会卡住
      partialize: state => ({
        examSuggestions: state.examSuggestions,
        inquirySuggestions: state.inquirySuggestions,
        diagnosisSuggestions: state.diagnosisSuggestions,
        appliedDiagnosis: state.appliedDiagnosis,
      }),
    }
  )
)
