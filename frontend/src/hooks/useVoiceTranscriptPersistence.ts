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
import { useEffect, useRef } from 'react'
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
    // 取消标志（2026-08-11 审计修复）：快速切换接诊时，旧接诊的 workspace 请求
    // 可能在切换后才返回，其 setter 会把旧患者的转写写进新患者界面并被持久化
    // （跨患者污染 + 隐私问题）。effect 清理时置 cancelled，await 返回后先判断再写。
    let cancelled = false
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
        // 这里仅消费 snapshot.latest_voice_record；其他字段不关心，
        // 用最小化内联接口替代 any（与 SnapshotResult 不耦合，避免循环依赖）
        const snapshot = (await api.get(`/encounters/${currentEncounterId}/workspace`)) as {
          latest_voice_record?: {
            id?: string
            raw_transcript?: string
            transcript_summary?: string
            speaker_dialogue?: DialogueItem[]
          } | null
        } | null
        // 已切到别的接诊：丢弃这个迟到的响应，绝不写进当前界面
        if (cancelled) return
        const latest = snapshot?.latest_voice_record
        if (latest) {
          // ── 不覆盖更"脏"的本地草稿（2026-08-14 第七轮审计 #22）──────────────
          //
          // 原先是「后端 raw_transcript 非空就无条件写进来」。问题在于**实时
          // ASR 的文本只存在于本地**（边说边累加进 localStorage，转写过程中
          // 并不落库），而 workspace 返回的是这个接诊**上一次**已上传的
          // voice_record。于是医生说了十分钟、刷新一下页面，本地这十分钟就被
          // 后端那份旧转写整个盖掉，没有任何提示。
          //
          // 规则与第五轮病历正文的防覆盖一致：本地非空且与后端不同时，
          // 以本地为准——本地可能含有后端从没见过的内容，而后端那份医生随时
          // 能重新拉到；反过来丢掉的语音内容不可再生。
          const localIsDirty = !!draft.transcript && draft.transcript !== latest.raw_transcript
          if (latest.raw_transcript && !localIsDirty) {
            setTranscript(latest.raw_transcript)
          }
          // 摘要/分角色对话是 LLM 对 transcript 的加工结果：本地转写更新时，
          // 后端那份是对旧文本的加工，跟着一起不覆盖，免得摘要与正文对不上。
          if (latest.transcript_summary && !localIsDirty) setSummary(latest.transcript_summary)
          if (
            !localIsDirty &&
            Array.isArray(latest.speaker_dialogue) &&
            latest.speaker_dialogue.length > 0
          ) {
            setSpeakerDialogue(latest.speaker_dialogue)
          }
          // transcriptId 照常采纳：它标识后端那条 voice_record，
          // 本地继续录的内容最终也要 PATCH 到它上面去。
          if (latest.id) setTranscriptId(latest.id)
        }
      } catch {
        // 服务端拉取失败不报错，本地草稿已经显示了
      }
    }
    restore()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentEncounterId])

  // 2) 任一字段变化时写回 voiceTranscriptStore（守护见文件 docstring）
  // ── 2026-05-03 治本：currentEncounterId 切换瞬间的 state 污染 ─────────────
  // 之前用户报告"门诊转住院后，住院端语音录入区出现门诊的转写文本"——
  // 根因是本 effect 在 currentEncounterId 切换瞬间被触发：state 闭包里仍是
  // 旧 encounter 的值（同一渲染周期 React state 还没 reset），导致
  // setForEncounter(新住院ID, {transcript: 旧门诊 transcript}) 把旧数据
  // 写到新接诊 slot。effect 1 会在下次渲染异步 restore state 为新值，
  // 但污染已经发生。
  // 修法：用 ref 记录上次 encounterId，发现变化时跳过本次写入（让 effect 1
  // 先 restore 完，下次 state 变化时再正常持久化）。
  const lastEncounterRef = useRef<string | null>(null)
  useEffect(() => {
    if (!currentEncounterId) {
      lastEncounterRef.current = null
      return
    }
    if (lastEncounterRef.current !== currentEncounterId) {
      // encounter 刚切换，state 还是旧值，不能写——交给 effect 1 重置后再走
      lastEncounterRef.current = currentEncounterId
      return
    }
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
    // 只关心 state 的 7 个具体字段变化（已展开），整体 state 引用变化不应触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
