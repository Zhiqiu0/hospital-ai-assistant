/**
 * 语音转写本地草稿 Store（store/voiceTranscriptStore.ts）
 *
 * 解决问题：
 *   useVoiceInputCard 之前用 React useState 存转写文本/总结/对话/transcriptId，
 *   刷新页面后这些 state 全部丢失。后端只保存"已点过重新分析+上传成功"的
 *   语音；用户录完音、或手动粘贴 ASR 结果但没分析就刷新 → 数据消失。
 *
 *   本 store 把这几项以 encounterId 为 key 持久化到 localStorage：
 *     - 不同接诊互相隔离（避免串数据）
 *     - 切换患者不丢失上一个患者的转写（医生回头看历史）
 *     - 后端 snapshot 拉到更新数据时会用 setForEncounter 覆盖
 *
 * 设计取舍：
 *   - audioToken 不在这里（短期 token，每次刷新重新换）
 *   - pendingPatch 在这里（医生分析后可能离开/刷新页面，预览待应用结果不应丢——
 *     和转写、摘要一样属于流程中间态。点「插入病历」或「取消」时由调用方设 null 清空）
 *   - lastAnalyzedTranscript 在这里（用于"分析过的内容是否变化"判断，需跨刷新）
 *
 * 容量控制：
 *   localStorage 单条 ≤5MB，转写文本可能很长。这里限制最多保留 10 个 encounter，
 *   超过则按 lastWriteAt 淘汰最早的。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface DialogueItem {
  speaker: 'doctor' | 'patient' | 'uncertain'
  text: string
}

export interface VoiceTranscriptDraft {
  transcript: string
  summary: string
  speakerDialogue: DialogueItem[]
  transcriptId: string | null
  lastAnalyzedTranscript: string
  /** AI 整理结果待应用预览；null 表示未分析 / 已应用 / 已取消 */
  pendingPatch: Record<string, unknown> | null
  /** 最后一次写入时间，用于 LRU 淘汰 */
  lastWriteAt: number
}

const EMPTY_DRAFT: VoiceTranscriptDraft = {
  transcript: '',
  summary: '',
  speakerDialogue: [],
  transcriptId: null,
  lastAnalyzedTranscript: '',
  pendingPatch: null,
  lastWriteAt: 0,
}

const MAX_ENCOUNTERS = 10

interface State {
  byEncounter: Record<string, VoiceTranscriptDraft>

  /** 读取某 encounter 的草稿；不存在返回空对象（不写入） */
  get: (encounterId: string) => VoiceTranscriptDraft

  /** 写入/合并某 encounter 的草稿；超过容量则淘汰最早的 */
  setForEncounter: (
    encounterId: string,
    patch: Partial<Omit<VoiceTranscriptDraft, 'lastWriteAt'>>
  ) => void

  /** 清空某 encounter 的草稿（如：用户主动点"清空重录"） */
  clearForEncounter: (encounterId: string) => void

  /** 清空所有（如登出） */
  clearAll: () => void
}

/** 内部：超过容量时淘汰 lastWriteAt 最早的条目 */
function pruneIfOverflow(
  byEncounter: Record<string, VoiceTranscriptDraft>
): Record<string, VoiceTranscriptDraft> {
  const ids = Object.keys(byEncounter)
  if (ids.length <= MAX_ENCOUNTERS) return byEncounter
  const sorted = ids.sort((a, b) => byEncounter[a].lastWriteAt - byEncounter[b].lastWriteAt)
  const next = { ...byEncounter }
  for (const id of sorted.slice(0, ids.length - MAX_ENCOUNTERS)) {
    delete next[id]
  }
  return next
}

export const useVoiceTranscriptStore = create<State>()(
  persist(
    (set, get) => ({
      byEncounter: {},

      get: encounterId => get().byEncounter[encounterId] ?? EMPTY_DRAFT,

      setForEncounter: (encounterId, patch) => {
        set(state => {
          const existing = state.byEncounter[encounterId] ?? EMPTY_DRAFT
          const merged: VoiceTranscriptDraft = {
            ...existing,
            ...patch,
            lastWriteAt: Date.now(),
          }
          return {
            byEncounter: pruneIfOverflow({
              ...state.byEncounter,
              [encounterId]: merged,
            }),
          }
        })
      },

      clearForEncounter: encounterId => {
        set(state => {
          if (!(encounterId in state.byEncounter)) return state
          const next = { ...state.byEncounter }
          delete next[encounterId]
          return { byEncounter: next }
        })
      },

      clearAll: () => set({ byEncounter: {} }),
    }),
    {
      name: 'medassist-voice-transcripts',
      partialize: state => ({ byEncounter: state.byEncounter }),
    }
  )
)
