/**
 * 语音录入卡片逻辑 hook（hooks/useVoiceInputCard.ts）
 * 管理录音、上传、结构化的全部状态与处理函数。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Modal, message } from 'antd'
import { InquiryData, useWorkbenchStore } from '@/store/workbenchStore'
import { useVoiceTranscriptStore, type DialogueItem } from '@/store/voiceTranscriptStore'
import api from '@/services/api'

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
  const { inquiry, currentPatient, currentEncounterId } = useWorkbenchStore()

  const [audioToken, setAudioToken] = useState<string | null>(null)
  const recognitionRef = useRef<any>(null)
  const mediaRecorderRef = useRef<any>(null)
  const mediaChunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const transcriptRef = useRef('')

  const [speechSupported] = useState(
    () =>
      typeof window !== 'undefined' &&
      !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)
  )
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
  const [interimText, setInterimText] = useState('')
  const [summary, setSummary] = useState('')
  const [speakerDialogue, setSpeakerDialogue] = useState<DialogueItem[]>([])

  const fullTranscript = useMemo(() => {
    return [transcript.trim(), interimText.trim()].filter(Boolean).join('\n').trim()
  }, [transcript, interimText])

  useEffect(() => {
    transcriptRef.current = fullTranscript
  }, [fullTranscript])

  useEffect(() => {
    if (!transcriptId) {
      setAudioToken(null)
      return
    }
    api
      .get(`/ai/voice-records/${transcriptId}/audio-token`)
      .then((res: any) => setAudioToken(res?.audio_token || null))
      .catch(() => setAudioToken(null))
  }, [transcriptId])

  // 切换 encounter 或刷新页面时的恢复策略：
  //   1) 先从 voiceTranscriptStore（localStorage）瞬时恢复 — 含未上传的草稿
  //   2) 再调 /workspace 取后端最新 voice_record，若有则覆盖（后端是权威）
  // 这样既不丢"录完没分析"的本地转写，也能拿到最新已上传的版本。
  useEffect(() => {
    const restore = async () => {
      if (!currentEncounterId) {
        setTranscript('')
        setInterimText('')
        setSummary('')
        setSpeakerDialogue([])
        setTranscriptId(null)
        setLastAnalyzedTranscript('')
        return
      }
      // 1) 从持久化 store 恢复
      const draft = useVoiceTranscriptStore.getState().get(currentEncounterId)
      setTranscript(draft.transcript)
      setSummary(draft.summary)
      setSpeakerDialogue(draft.speakerDialogue)
      setTranscriptId(draft.transcriptId)
      setLastAnalyzedTranscript(draft.lastAnalyzedTranscript)
      // 2) 再调后端覆盖（如果后端有更新版）
      // 守护：后端字段为空时不覆盖本地草稿（latest_voice_record 可能存在但
      // raw_transcript 为 null/空字符串）
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
  }, [currentEncounterId])

  // 把 transcript/summary/speakerDialogue/transcriptId/lastAnalyzedTranscript 任一变化
  // 同步写入 voiceTranscriptStore，刷新页面后这些数据可恢复。
  // 守护：mount 时 React 初始 useState 是空值，会先于 restore 的 setTranscript
  // 应用前触发本 effect（同一 render 周期里 effects 按声明顺序执行）。如果直接
  // 写入 store，会用空值覆盖刚 persist 恢复的内容。守护逻辑：当 store 当前
  // 有内容但要写入的值全空，跳过本次写入。用户主动清空走 handleClearTranscript
  // 里的 clearForEncounter，不依赖本 effect。
  useEffect(() => {
    if (!currentEncounterId) return
    const incoming = {
      transcript,
      summary,
      speakerDialogue,
      transcriptId,
      lastAnalyzedTranscript,
    }
    const incomingEmpty =
      !incoming.transcript &&
      !incoming.summary &&
      !incoming.transcriptId &&
      !incoming.lastAnalyzedTranscript &&
      incoming.speakerDialogue.length === 0
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
    useVoiceTranscriptStore.getState().setForEncounter(currentEncounterId, incoming)
  }, [
    currentEncounterId,
    transcript,
    summary,
    speakerDialogue,
    transcriptId,
    lastAnalyzedTranscript,
  ])

  const stopTracks = () => {
    streamRef.current?.getTracks().forEach(t => t.stop())
    streamRef.current = null
  }

  const uploadAudioBlob = async (blob: Blob, transcriptText: string) => {
    if (!blob.size) return
    setUploadingAudio(true)
    try {
      const formData = new FormData()
      formData.append('file', blob, `voice-record-${Date.now()}.webm`)
      if (currentEncounterId) formData.append('encounter_id', currentEncounterId)
      formData.append('visit_type', visitType)
      formData.append('transcript', transcriptText)
      const data: any = await api.post('/ai/voice-records/upload', formData)
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

  const stopListening = () => {
    recognitionRef.current?.stop?.()
    recognitionRef.current = null
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
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
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
        await uploadAudioBlob(blob, transcriptRef.current)
      }
      mediaRecorder.start()
      mediaRecorderRef.current = mediaRecorder

      if (speechSupported) {
        const RecognitionCtor =
          (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
        const recognition = new RecognitionCtor()
        recognition.lang = 'zh-CN'
        recognition.continuous = true
        recognition.interimResults = true
        recognition.onresult = (event: any) => {
          let finalText = ''
          let interim = ''
          for (let i = event.resultIndex; i < event.results.length; i++) {
            const text = event.results[i][0]?.transcript || ''
            if (event.results[i].isFinal) finalText += text
            else interim += text
          }
          if (finalText.trim())
            setTranscript(prev => [prev, finalText.trim()].filter(Boolean).join('\n'))
          setInterimText(interim.trim())
        }
        recognition.onerror = (event: any) => {
          if (['no-speech', 'network', 'audio-capture', 'aborted'].includes(event.error)) return
          recognitionRef.current = null
          setListening(false)
          setInterimText('')
          message.error('语音识别中断，请重试')
        }
        recognition.onend = () => {
          if (recognitionRef.current === recognition) {
            try {
              recognition.start()
              return
            } catch {}
          }
          recognitionRef.current = null
          setListening(false)
          setInterimText('')
        }
        recognition.start()
        recognitionRef.current = recognition
      } else {
        message.info('浏览器不支持实时转写，但会继续录音保存，你也可以手动补充转写文本')
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
      const data: any = await api.post('/ai/voice-structure', {
        transcript: fullTranscript,
        transcript_id: transcriptId,
        visit_type: visitType,
        patient_name: currentPatient?.name || '',
        patient_gender: currentPatient?.gender || '',
        patient_age: currentPatient?.age != null ? String(currentPatient.age) : '',
        existing_inquiry: { ...inquiry, ...getFormValues() },
      })
      const patch = (data?.inquiry || {}) as Partial<InquiryData>
      const filteredPatch = Object.fromEntries(
        Object.entries(patch).filter(([, v]) => v !== '' && v !== null && v !== undefined)
      ) as Partial<InquiryData>
      setSummary(data?.transcript_summary || '')
      setSpeakerDialogue(Array.isArray(data?.speaker_dialogue) ? data.speaker_dialogue : [])
      setTranscriptId(data?.transcript_id || transcriptId)
      setLastAnalyzedTranscript(fullTranscript)
      if (isRecordMode) {
        setPendingPatch(filteredPatch)
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
          try {
            await api.delete(`/ai/voice-records/${transcriptId}`)
          } catch {}
        }
        setTranscript('')
        setSummary('')
        setSpeakerDialogue([])
        setTranscriptId(null)
        setLastAnalyzedTranscript('')
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
    speechSupported,
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
