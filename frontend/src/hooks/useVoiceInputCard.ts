/**
 * 语音录入卡片逻辑 hook（hooks/useVoiceInputCard.ts）
 * 管理录音、上传、结构化的全部状态与处理函数。
 *
 * 语音识别方案：
 *   主路径 — 阿里云 Paraformer 实时 ASR（via 后端 WebSocket 代理 /api/v1/ai/voice-stream）
 *   兜底路径 — WebSocket 建连失败时，停止录音后音频文件上传到后端由 Qwen-Audio 整段转写
 *
 * Audit Round 4 M6 拆分：
 *   - API 调用集中 → services/voiceTranscriptApi.ts
 *   - 转写跨刷新恢复/持久化 → hooks/useVoiceTranscriptPersistence.ts
 *   - 本 hook 主体保留：录音 / 实时 ASR 编排 + 状态聚合 + UI 操作回调
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Modal, message } from 'antd'
import { InquiryData } from '@/store/types'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { useActiveEncounterStore, useCurrentPatient } from '@/store/activeEncounterStore'
import { useVoiceTranscriptStore, type DialogueItem } from '@/store/voiceTranscriptStore'
import { useAuthStore } from '@/store/authStore'
import { startVoiceStream, type VoiceStreamHandle } from '@/services/voiceStream'
import {
  deleteVoiceRecord,
  fetchAudioToken,
  filterPatch,
  structureVoice,
  uploadVoiceAudio,
} from '@/services/voiceTranscriptApi'
import { useVoiceTranscriptPersistence } from '@/hooks/useVoiceTranscriptPersistence'
import { dedupeVitalSignsAgainstRecord } from '@/utils/inquiryUtils'

interface Props {
  visitType: 'outpatient' | 'inpatient'
  getFormValues: () => Record<string, any>
  onApplyInquiry: (patch: Partial<InquiryData>) => void
  onApplyToRecord?: (patch: Partial<InquiryData>) => void
}

export function useVoiceInputCard({
  visitType,
  getFormValues,
  onApplyInquiry,
  onApplyToRecord,
}: Props) {
  const isRecordMode = !!onApplyToRecord
  const inquiry = useInquiryStore(s => s.inquiry)
  // 病历草稿全文：续录场景下优先作为 LLM 增量分析的"已知信息基线"，因为它含医生手改
  const recordContent = useRecordStore(s => s.recordContent)
  const currentPatient = useCurrentPatient()
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)

  const [audioToken, setAudioToken] = useState<string | null>(null)
  // 实时 ASR 流句柄（含 stop 方法），录音期间存活
  const voiceStreamRef = useRef<VoiceStreamHandle | null>(null)
  // 录音音频文件采集器（用于存档 + 作为 WebSocket 失败时的兜底转写源）
  const mediaRecorderRef = useRef<any>(null)
  const mediaChunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const transcriptRef = useRef('')
  // 本次录音阿里云实时 ASR 是否可用。false 则停止后走后端整段转写兜底
  const streamFallbackRef = useRef(false)

  // 浏览器是否支持 MediaRecorder（录音存档的基础能力）
  const [recordingSupported] = useState(
    () => typeof window !== 'undefined' && typeof MediaRecorder !== 'undefined'
  )
  const [listening, setListening] = useState(false)
  const [uploadingAudio, setUploadingAudio] = useState(false)
  const [structuring, setStructuring] = useState(false)
  const [pendingPatch, setPendingPatch] = useState<Partial<InquiryData> | null>(null)
  const [transcriptId, setTranscriptId] = useState<string | null>(null)
  const [transcript, setTranscript] = useState('')
  const [lastAnalyzedTranscript, setLastAnalyzedTranscript] = useState('')
  // 最近一次实时识别的中间结果（partial），附加在 transcript 末尾渲染
  const [interimText, setInterimText] = useState('')
  const [summary, setSummary] = useState('')
  const [speakerDialogue, setSpeakerDialogue] = useState<DialogueItem[]>([])

  const fullTranscript = useMemo(() => {
    return [transcript.trim(), interimText.trim()].filter(Boolean).join(' ').trim()
  }, [transcript, interimText])

  useEffect(() => {
    transcriptRef.current = fullTranscript
  }, [fullTranscript])

  // 拉一次性 audio token（给 <audio> 鉴权播放原始录音）
  useEffect(() => {
    if (!transcriptId) {
      setAudioToken(null)
      return
    }
    fetchAudioToken(transcriptId).then(setAudioToken)
  }, [transcriptId])

  // 切换 encounter / 刷新时：本地 store 先恢复 → 后端权威覆盖；状态变化写回 store
  useVoiceTranscriptPersistence(
    currentEncounterId,
    {
      transcript,
      summary,
      speakerDialogue,
      transcriptId,
      lastAnalyzedTranscript,
      pendingPatch: pendingPatch as Record<string, unknown> | null,
    },
    {
      setTranscript,
      setInterimText,
      setSummary,
      setSpeakerDialogue,
      setTranscriptId,
      setLastAnalyzedTranscript,
      setPendingPatch: v => setPendingPatch(v as Partial<InquiryData> | null),
    }
  )

  const stopTracks = () => {
    streamRef.current?.getTracks().forEach(t => t.stop())
    streamRef.current = null
  }

  /**
   * 上传录音音频文件。
   * - transcriptText 非空：仅归档（后端跳过整段转写）
   * - transcriptText 为空：后端 Qwen-Audio 兜底转写（仅当实时 ASR 未成功时触发）
   */
  const uploadAudioBlob = async (blob: Blob, transcriptText: string) => {
    if (!blob.size) return
    setUploadingAudio(true)
    try {
      const data = await uploadVoiceAudio(blob, transcriptText, {
        encounterId: currentEncounterId,
        visitType,
      })
      if (data?.voice_record_id) setTranscriptId(data.voice_record_id)
      if (data?.transcript && !transcriptText.trim()) {
        setTranscript(data.transcript)
        message.success('语音已保存，云端转写完成')
      } else {
        message.success('原始语音已保存')
      }
    } catch {
      message.error('原始语音保存失败')
    } finally {
      setUploadingAudio(false)
    }
  }

  const stopListening = async () => {
    // 先停实时 ASR（发送 finish + 等待 finished，最多 3s）
    const voiceStream = voiceStreamRef.current
    voiceStreamRef.current = null
    if (voiceStream) {
      try {
        await voiceStream.stop()
      } catch {
        // stop 过程失败不阻塞后续录音文件上传
      }
    }
    // 再停 MediaRecorder（onstop 中会触发音频文件上传）
    const mr = mediaRecorderRef.current
    if (mr && mr.state !== 'inactive') mr.stop()
    else stopTracks()
    mediaRecorderRef.current = null
    setListening(false)
    setInterimText('')
  }

  const startListening = async () => {
    if (!recordingSupported) {
      message.warning('当前浏览器不支持录音保存，建议使用最新版 Chrome / Edge')
      return
    }
    if (!currentEncounterId) {
      message.warning('请先新建接诊，再开始语音录入')
      return
    }
    const token = useAuthStore.getState().token
    if (!token) {
      message.error('登录状态已失效，请重新登录')
      return
    }
    try {
      streamFallbackRef.current = false
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      // MediaRecorder 始终启动，用于录音存档 + WebSocket 失败时的兜底转写源
      const mediaRecorder = new MediaRecorder(stream)
      mediaChunksRef.current = []
      mediaRecorder.ondataavailable = (e: BlobEvent) => {
        if (e.data.size > 0) mediaChunksRef.current.push(e.data)
      }
      mediaRecorder.onstop = async () => {
        const blob = new Blob(mediaChunksRef.current, {
          type: mediaRecorder.mimeType || 'audio/webm',
        })
        mediaChunksRef.current = []
        stopTracks()
        // 实时 ASR 可用时把已识别文本附上，后端跳过整段转写；失败时传空串触发兜底
        const transcriptForUpload = streamFallbackRef.current ? '' : transcriptRef.current
        await uploadAudioBlob(blob, transcriptForUpload)
      }
      mediaRecorder.start()
      mediaRecorderRef.current = mediaRecorder

      // 启动实时 ASR；失败则走兜底（录音照常进行，停止后整段转写）
      try {
        const handle = await startVoiceStream(token, {
          onPartial: text => setInterimText(text),
          onFinal: text => {
            // 终稿句追加到主 transcript，partial 清空等待下一句
            if (text.trim()) {
              setTranscript(prev => [prev, text.trim()].filter(Boolean).join(' '))
            }
            setInterimText('')
          },
          onError: msg => {
            // 连接中途失败：标记走兜底；UI 提示一次即可
            if (!streamFallbackRef.current) {
              streamFallbackRef.current = true
              message.warning(`实时转写中断：${msg}，录音继续进行，停止后自动云端转写`, 5)
            }
          },
        })
        voiceStreamRef.current = handle
      } catch (err: any) {
        streamFallbackRef.current = true
        message.warning(
          `实时转写未启用（${err?.message || '连接失败'}），录音继续，停止后自动云端转写`,
          5
        )
      }

      setListening(true)
      message.success('已开始语音录入')
    } catch {
      stopTracks()
      message.error('无法访问麦克风，请检查浏览器权限')
    }
  }

  const handleContinueRecording = async () => {
    if (transcript.trim()) setTranscript(prev => prev.trimEnd() + '\n--- 续录 ---\n')
    startListening()
  }

  const doStructure = async () => {
    setStructuring(true)
    try {
      const data = await structureVoice({
        fullTranscript,
        transcriptId,
        visitType,
        patient: currentPatient
          ? {
              name: currentPatient.name,
              gender: currentPatient.gender || '',
              age: currentPatient.age,
            }
          : null,
        existingInquiry: { ...inquiry, ...getFormValues() },
        // 病历草稿非空时作为权威基线传给 LLM，让续录场景只输出新增/修正字段，
        // 避免整段覆盖把医生在病历里的手改冲掉。草稿为空时后端会回退到 existingInquiry。
        existingRecord: recordContent || undefined,
      })
      const filteredPatch = filterPatch((data?.inquiry || {}) as Partial<InquiryData>)
      // 追记模式下对 vital_signs 嵌套子字段做基线去重——LLM 对嵌套子字段层级
      // 增量约束遵守得不严，常把基线已有的体温/脉搏等数值重复输出，前端兜底剔除
      const dedupedPatch = isRecordMode
        ? (dedupeVitalSignsAgainstRecord(
            filteredPatch as Record<string, unknown>,
            recordContent
          ) as Partial<InquiryData>)
        : filteredPatch
      setSummary(data?.transcript_summary || '')
      setSpeakerDialogue(Array.isArray(data?.speaker_dialogue) ? data.speaker_dialogue : [])
      setTranscriptId(data?.transcript_id || transcriptId)
      setLastAnalyzedTranscript(fullTranscript)
      if (isRecordMode) {
        setPendingPatch(dedupedPatch)
        message.success('AI 整理完成，请确认下方内容后点击「插入病历」')
      } else {
        onApplyInquiry(filteredPatch)
        message.success('已根据语音内容整理问诊字段，保存后将同步到病历')
      }
    } catch {
      message.error('语音整理失败，请重试')
    } finally {
      setStructuring(false)
    }
  }

  const handleStructure = () => {
    if (listening) {
      message.warning('请先停止当前录音，再进行 AI 整理')
      return
    }
    if (!fullTranscript) {
      message.warning('请先进行语音录入或粘贴转写内容')
      return
    }
    if (lastAnalyzedTranscript && lastAnalyzedTranscript === fullTranscript) {
      Modal.confirm({
        title: '转写内容未变化',
        content: '当前转写与上次分析完全相同，重新分析将覆盖已有问诊内容和病历草稿，确认继续？',
        okText: '确认重新分析',
        cancelText: '取消',
        onOk: doStructure,
      })
      return
    }
    doStructure()
  }

  const handleClearTranscript = () => {
    Modal.confirm({
      title: '确认清空重录？',
      content: '将删除此段录音及转写内容，删除后不可恢复。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        if (transcriptId) {
          await deleteVoiceRecord(transcriptId)
        }
        setTranscript('')
        setSummary('')
        setSpeakerDialogue([])
        setTranscriptId(null)
        setLastAnalyzedTranscript('')
        // pendingPatch 也要清——否则 React state 仍有值会触发 persistence
        // effect 把 patch 重新写回 store，把刚 clearForEncounter 的清空覆盖掉
        setPendingPatch(null)
        // 同步清掉 store 中本 encounter 的草稿，避免下次刷新又"恢复"
        if (currentEncounterId) {
          useVoiceTranscriptStore.getState().clearForEncounter(currentEncounterId)
        }
      },
    })
  }

  const handleApplyPatch = () => {
    if (pendingPatch) {
      onApplyToRecord!(pendingPatch)
      setPendingPatch(null)
    }
  }

  return {
    isRecordMode,
    recordingSupported,
    listening,
    uploadingAudio,
    structuring,
    pendingPatch,
    setPendingPatch,
    transcriptId,
    transcript,
    setTranscript,
    lastAnalyzedTranscript,
    interimText,
    setInterimText,
    summary,
    speakerDialogue,
    fullTranscript,
    audioToken,
    startListening,
    stopListening,
    handleContinueRecording,
    handleStructure,
    handleClearTranscript,
    handleApplyPatch,
  }
}
