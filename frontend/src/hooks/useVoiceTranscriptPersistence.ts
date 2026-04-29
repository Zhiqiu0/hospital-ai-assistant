/**
 * 语音转写跨刷新持久化（hooks/useVoiceTranscriptPersistence.ts）
 *
 * 从 useVoiceInputCard 抽出（Audit Round 4 M6），独立处理两件事：
 *   1) 切换接诊/刷新页面时，按"先本地 store → 再后端权威"的优先级恢复转写状态
 *   2) 状态任一字段变化时，写回 voiceTranscriptStore（持久化到 localStorage）
 *
 * 守护逻辑（重要 — 不要省略）：
 *   useState 初始空值会在 restore 设置真实值之前就触发 persist effect，
 *   如果直接覆盖 store 会用空值清掉刚 restore 的内容。所以本 hook 在
 *   "incoming 全空 + store 已有内容"时跳过本次写入；用户主动清空走外层
 *   handleClearTranscript 调 clearForEncounter，不依赖本 hook。
 */
import { useEffect } from 'react'
import api from '@/services/api'
import { useVoiceTranscriptStore, type DialogueItem } from '@/store/voiceTranscriptStore'

interface VoiceTranscriptState {
  transcript: string
  summary: string
  speakerDialogue: DialogueItem[]
  transcriptId: string | null
  lastAnalyzedTranscript: string
  pendingPatch: Record<string, unknown> | null
}

interface VoiceTranscriptSetters {
  setTranscript: (value: string) => void
  setInterimText: (value: string) => void
  setSummary: (value: string) => void
  setSpeakerDialogue: (value: DialogueItem[]) => void
  setTranscriptId: (value: string | null) => void
  setLastAnalyzedTranscript: (value: string) => void
  setPendingPatch: (value: Record<string, unknown> | null) => void
}

/**
 * 订阅当前 encounter 的转写恢复 + 持久化。
 *
 * @param currentEncounterId 当前接诊 ID（null 时清空所有状态）
 * @param state              当前 hook 内的转写状态（用于持久化）
 * @param setters            React setter 集合（用于恢复）
 */
export function useVoiceTranscriptPersistence(
  currentEncounterId: string | null,
  state: VoiceTranscriptState,
  setters: VoiceTranscriptSetters
) {
  const {
    setTranscript,
    setInterimText,
    setSummary,
    setSpeakerDialogue,
    setTranscriptId,
    setLastAnalyzedTranscript,
    setPendingPatch,
  } = setters

  // 1) 切换 encounter 或刷新页面时的恢复策略：本地 store → 后端权威
  useEffect(() => {
    const restore = async () => {
      if (!currentEncounterId) {
        setTranscript('')
        setInterimText('')
        setSummary('')
        setSpeakerDialogue([])
        setTranscriptId(null)
        setLastAnalyzedTranscript('')
        setPendingPatch(null)
        return
      }
      // 先本地 store 恢复（含未上传的草稿）
      const draft = useVoiceTranscriptStore.getState().get(currentEncounterId)
      setTranscript(draft.transcript)
      setSummary(draft.summary)
      setSpeakerDialogue(draft.speakerDialogue)
      setTranscriptId(draft.transcriptId)
      setLastAnalyzedTranscript(draft.lastAnalyzedTranscript)
      setPendingPatch(draft.pendingPatch)
      // 再调后端覆盖（如果后端有更新版）
      // 守护：后端字段为空时不覆盖本地草稿
      try {
        const snapshot: any = await api.get(`/encounters/${currentEncounterId}/workspace`)
        const latest = snapshot?.latest_voice_record
        if (latest) {
          if (latest.raw_transcript) setTranscript(latest.raw_transcript)
          if (latest.transcript_summary) setSummary(latest.transcript_summary)
          if (Array.isArray(latest.speaker_dialogue) && latest.speaker_dialogue.length > 0) {
            setSpeakerDialogue(latest.speaker_dialogue)
          }
          if (latest.id) setTranscriptId(latest.id)
        }
      } catch {
        // 服务端拉取失败不报错，本地草稿已经显示了
      }
    }
    restore()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentEncounterId])

  // 2) 任一字段变化时写回 voiceTranscriptStore（守护见文件 docstring）
  useEffect(() => {
    if (!currentEncounterId) return
    const incomingEmpty =
      !state.transcript &&
      !state.summary &&
      !state.transcriptId &&
      !state.lastAnalyzedTranscript &&
      state.speakerDialogue.length === 0
    if (incomingEmpty) {
      const cur = useVoiceTranscriptStore.getState().get(currentEncounterId)
      const curHasContent =
        !!cur.transcript ||
        !!cur.summary ||
        !!cur.transcriptId ||
        !!cur.lastAnalyzedTranscript ||
        cur.speakerDialogue.length > 0
      if (curHasContent) return
    }
    useVoiceTranscriptStore.getState().setForEncounter(currentEncounterId, state)
  }, [
    currentEncounterId,
    state.transcript,
    state.summary,
    state.speakerDialogue,
    state.transcriptId,
    state.lastAnalyzedTranscript,
    state.pendingPatch,
  ])
}
