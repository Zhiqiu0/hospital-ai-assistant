/**
 * 病历质控 Store（store/qcStore.ts）
 *
 * Audit Round 4 M1 拆分：负责 AI 质控相关的所有状态和操作。
 *
 * 职责：
 *   - 质控运行态：isQCing（流式中）、qcLlmLoading（LLM 阶段未完成）、qcRunId
 *   - 质控结果：qcIssues（rule + llm 合并）、qcSummary、qcPass、gradeScore
 *   - 病历变更标记：isQCStale（病历改过后，质控结果按钮变"重新质控"）
 *   - 用户操作记忆：qcFixTexts（每条 issue 的 AI 修复文本）、qcWrittenIndices（已写入病历的 issue 索引）
 *
 * qcRunId 设计：
 *   每次 startQCRun 生成新的 timestamp，QCIssuePanel 监听变化重置每条 issue 的本地状态（resolved/ignored）。
 *   appendQCIssues 不更新 runId（LLM 流式追加不算新一轮，避免清掉用户操作）。
 *
 * 持久化（localStorage key: medassist-qc）：
 *   除 isQCing/qcLlmLoading/qcRunId 这类瞬态字段外全部持久化，刷新后质控结果完整恢复。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { QCIssue, GradeScore } from './types'

interface QCState {
  /** 本轮质控的 ID（timestamp 字符串），每次 startQCRun 更新 */
  qcRunId: string
  /** 流式调用是否还在跑（按钮 loading 态） */
  isQCing: boolean
  /** LLM 阶段是否还在加载（结构性 rule 已出来、LLM 建议还在路上） */
  qcLlmLoading: boolean
  /** 病历自上次质控后是否被修改过（true 时按钮显示「重新质控」） */
  isQCStale: boolean

  /** rule + llm 两阶段质控结果合并列表 */
  qcIssues: QCIssue[]
  /** 质控总结摘要 */
  qcSummary: string
  /** 是否通过质控（null 表示尚未质控） */
  qcPass: boolean | null
  /** 甲级评分 */
  gradeScore: GradeScore | null

  /** 每条 issue 对应的 AI 修复文本，key = issue 在 qcIssues 数组里的索引 */
  qcFixTexts: Record<number, string>
  /** 已写入病历的 issue 索引列表（用于在面板上显示"已写入"标记） */
  qcWrittenIndices: number[]

  // ── actions ───────────────────────────────────────────────
  /** 开始新一轮质控：生成新 runId、清空上一轮结果、重置医生操作记录 */
  startQCRun: () => void
  /** 写入质控完整结果（rule 阶段 + LLM 收尾时各调一次） */
  setQCResult: (
    issues: QCIssue[],
    summary: string,
    pass: boolean | null,
    gradeScore?: GradeScore | null
  ) => void
  /** 流式追加 LLM 建议（不更新 runId，不清空医生操作） */
  appendQCIssues: (issues: QCIssue[]) => void
  setQCSummary: (summary: string) => void
  setQCLlmLoading: (v: boolean) => void
  setQCing: (v: boolean) => void
  setQCFixTexts: (texts: Record<number, string>) => void
  setQCWrittenIndices: (indices: number[]) => void
  /**
   * 标记质控结果已过时（病历内容变化后由 recordStore 调用）。
   * 仅在已有质控结果时设为 true，否则保持原值，避免空 store 闪 stale 角标。
   */
  markStale: () => void
  /** 重置所有质控状态（切换接诊 / 登出时调用） */
  reset: () => void
}

export const useQCStore = create<QCState>()(
  persist(
    set => ({
      qcRunId: '',
      isQCing: false,
      qcLlmLoading: false,
      isQCStale: false,

      qcIssues: [],
      qcSummary: '',
      qcPass: null,
      gradeScore: null,

      qcFixTexts: {},
      qcWrittenIndices: [],

      startQCRun: () =>
        set({
          qcRunId: Date.now().toString(),
          qcIssues: [],
          qcSummary: '',
          qcPass: null,
          gradeScore: null,
          qcLlmLoading: false,
          isQCStale: false,
          qcFixTexts: {},
          qcWrittenIndices: [],
        }),

      setQCResult: (issues, summary, pass, gradeScore = null) =>
        set({ qcIssues: issues, qcSummary: summary, qcPass: pass, gradeScore }),

      appendQCIssues: issues => set(state => ({ qcIssues: [...state.qcIssues, ...issues] })),

      setQCSummary: summary => set({ qcSummary: summary }),
      setQCLlmLoading: v => set({ qcLlmLoading: v }),
      setQCing: v => set({ isQCing: v }),
      setQCFixTexts: texts => set({ qcFixTexts: texts }),
      setQCWrittenIndices: indices => set({ qcWrittenIndices: indices }),

      markStale: () =>
        set(state => ({
          // 已经有结果时才标 stale；空 store 不闪 stale 角标
          isQCStale: state.qcIssues.length > 0 || state.qcPass !== null ? true : state.isQCStale,
        })),

      reset: () =>
        set({
          qcRunId: '',
          isQCing: false,
          qcLlmLoading: false,
          isQCStale: false,
          qcIssues: [],
          qcSummary: '',
          qcPass: null,
          gradeScore: null,
          qcFixTexts: {},
          qcWrittenIndices: [],
        }),
    }),
    {
      name: 'medassist-qc',
      // 瞬态字段（isQCing/qcLlmLoading/qcRunId）不持久化，否则刷新后按钮会卡在 loading
      partialize: state => ({
        qcIssues: state.qcIssues,
        qcSummary: state.qcSummary,
        qcPass: state.qcPass,
        gradeScore: state.gradeScore,
        isQCStale: state.isQCStale,
        qcFixTexts: state.qcFixTexts,
        qcWrittenIndices: state.qcWrittenIndices,
      }),
    }
  )
)
