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
  /** 归属接诊（2026-08-28 多标签页审计）：单槽 persist 在双标签页会被互相
   *  覆盖，还原时与接诊指针对不上就必须丢弃——宁可重拉，不能把甲患者的
   *  数据拼到乙患者名下（与 recordStore.ownerEncounterId 同款守卫） */
  ownerEncounterId: string | null
  bindOwner: (encounterId: string | null) => void
  /** 归属校验：对不上即 reset+重绑，返回是否通过 */
  assertOwner: (encounterId: string) => boolean
}

export const useAISuggestionStore = create<AISuggestionState>()(
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
        // 归属必须随数据一起持久化（2026-08-29 对抗复核抓漏）：漏了它则每次
        // 刷新 owner 恒 null，水合 assertOwner 必失配把刚恢复的数据全清
        ownerEncounterId: state.ownerEncounterId,
        examSuggestions: state.examSuggestions,
        inquirySuggestions: state.inquirySuggestions,
        diagnosisSuggestions: state.diagnosisSuggestions,
        appliedDiagnosis: state.appliedDiagnosis,
      }),
    }
  )
)
