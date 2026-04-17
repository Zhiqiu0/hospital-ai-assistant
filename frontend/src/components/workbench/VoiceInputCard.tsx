/**
 * 语音输入卡片（components/workbench/VoiceInputCard.tsx）
 *
 * 提供完整的语音录制→转写→结构化流程：
 *   1. 录音：调用浏览器 MediaRecorder API，实时推送 timeslice 片段
 *   2. 上传：录音完成后调用 POST /ai/voice-records/upload（含 ASR 转写）
 *   3. 结构化：调用 POST /ai/voice-structure，LLM 解析转写文本为问诊字段 + 病历草稿
 *   4a. 问诊模式（未锁定）：通过 onApplyInquiry 回调将字段填入左侧问诊表单
 *   4b. 追记模式（已锁定）：通过 onApplyToRecord 回调将字段写入病历对应章节
 *       结构化完成后先展示预览，医生确认后再点「插入病历」写入
 *
 * 音频播放安全机制：
 *   先调用 GET /ai/voice-records/{id}/audio-token 获取 5 分钟短期令牌，
 *   避免完整 JWT 出现在 audio src URL / 服务器日志中。
 *
 * Props：
 *   visitType:        决定使用门诊还是住院语音结构化 prompt
 *   getFormValues:    获取当前问诊表单现有值（传给结构化 API 作为上下文）
 *   onApplyInquiry:   问诊模式回调，接收结构化字段 patch，填入左侧表单
 *   onApplyToRecord:  追记模式回调（可选），接收结构化字段 patch，写入病历章节
 *                     传入此 prop 则进入追记模式，不传则为问诊模式
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, Input, List, Modal, Space, Tag, Typography, message } from 'antd'
import {
  AudioOutlined,
  PauseCircleOutlined,
  RobotOutlined,
  DeleteOutlined,
  FileTextOutlined,
  SaveOutlined,
  MedicineBoxOutlined,
} from '@ant-design/icons'
import { InquiryData, useWorkbenchStore } from '@/store/workbenchStore'
import { FIELD_NAME_LABEL, FIELD_TO_SECTION } from './qcFieldMaps'
import api from '@/services/api'

const { TextArea } = Input
const { Text } = Typography

type VoiceInputCardProps = {
  visitType: 'outpatient' | 'inpatient'
  /** 获取当前问诊表单现有值，作为 AI 结构化的上下文 */
  getFormValues: () => Record<string, any>
  /** 问诊模式：结构化完成后填入左侧表单 */
  onApplyInquiry: (patch: Partial<InquiryData>) => void
  /** 追记模式（可选）：传入此 prop 后结构化结果进入预览，确认后写入病历章节 */
  onApplyToRecord?: (patch: Partial<InquiryData>) => void
}

type DialogueItem = {
  speaker: 'doctor' | 'patient' | 'uncertain'
  text: string
}

const SPEAKER_META: Record<string, { color: string; label: string }> = {
  doctor: { color: 'blue', label: '医生' },
  patient: { color: 'green', label: '患者' },
  uncertain: { color: 'orange', label: '待确认' },
}

export default function VoiceInputCard({
  visitType,
  getFormValues,
  onApplyInquiry,
  onApplyToRecord,
}: VoiceInputCardProps) {
  /** 追记模式：onApplyToRecord 存在时为 true */
  const isRecordMode = !!onApplyToRecord
  const { inquiry, currentPatient, currentEncounterId } = useWorkbenchStore()

  // Bug B 修复：不再把完整会话 JWT 放入 audio src URL（会被服务器日志记录）。
  // 改为按需请求 5 分钟短期音频令牌，过期自动失效且只绑定特定音频文件。
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

  /**
   * 追记模式下的待确认 patch：AI 整理完成后暂存，等待医生点「插入病历」再写入。
   * 问诊模式下此值始终为 null（直接回填表单，无需预览确认）。
   */
  const [pendingPatch, setPendingPatch] = useState<Partial<InquiryData> | null>(null)

  const [transcriptId, setTranscriptId] = useState<string | null>(null)
  const [transcript, setTranscript] = useState('')
  const [lastAnalyzedTranscript, setLastAnalyzedTranscript] = useState('')
  const [interimText, setInterimText] = useState('')
  const [summary, setSummary] = useState('')
  const [speakerDialogue, setSpeakerDialogue] = useState<DialogueItem[]>([])

  const fullTranscript = useMemo(() => {
    const merged = [transcript.trim(), interimText.trim()].filter(Boolean).join('\n')
    return merged.trim()
  }, [transcript, interimText])

  useEffect(() => {
    transcriptRef.current = fullTranscript
  }, [fullTranscript])

  // transcriptId 变化时（新录音上传完成 / 切换接诊），获取新的短期音频令牌
  useEffect(() => {
    if (!transcriptId) {
      setAudioToken(null)
      return
    }
    // 请求短期音频令牌（有效期 5 分钟），失败时静默处理（audio 元素会显示加载失败）
    api
      .get(`/ai/voice-records/${transcriptId}/audio-token`)
      .then((res: any) => setAudioToken(res?.audio_token || null))
      .catch(() => setAudioToken(null))
  }, [transcriptId])

  useEffect(() => {
    const restoreLatestVoice = async () => {
      if (!currentEncounterId) {
        setTranscript('')
        setInterimText('')
        setSummary('')
        setSpeakerDialogue([])
        setTranscriptId(null)
        return
      }
      try {
        const snapshot: any = await api.get(`/encounters/${currentEncounterId}/workspace`)
        const latest = snapshot?.latest_voice_record
        if (latest) {
          setTranscript(latest.raw_transcript || '')
          setSummary(latest.transcript_summary || '')
          setSpeakerDialogue(Array.isArray(latest.speaker_dialogue) ? latest.speaker_dialogue : [])
          setTranscriptId(latest.id || null)
        } else {
          setTranscript('')
          setSummary('')
          setSpeakerDialogue([])
          setTranscriptId(null)
        }
      } catch {
        setTranscript('')
        setSummary('')
        setSpeakerDialogue([])
        setTranscriptId(null)
      }
    }

    restoreLatestVoice()
  }, [currentEncounterId])

  const stopTracks = () => {
    streamRef.current?.getTracks().forEach(track => track.stop())
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
      // 若后端返回了云端转写结果，且本地转写为空，则使用云端结果
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

    const mediaRecorder = mediaRecorderRef.current
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop()
    } else {
      stopTracks()
    }

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
      mediaRecorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) mediaChunksRef.current.push(event.data)
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
          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const text = event.results[i][0]?.transcript || ''
            if (event.results[i].isFinal) {
              finalText += text
            } else {
              interim += text
            }
          }
          if (finalText.trim()) {
            setTranscript(prev => [prev, finalText.trim()].filter(Boolean).join('\n'))
          }
          setInterimText(interim.trim())
        }

        recognition.onerror = (event: any) => {
          // 这些错误是暂时性的（蓝牙切换/网络抖动/静音），让 onend 自动重启
          if (['no-speech', 'network', 'audio-capture', 'aborted'].includes(event.error)) return
          // 真正的权限错误才停止
          recognitionRef.current = null
          setListening(false)
          setInterimText('')
          message.error('语音识别中断，请重试')
        }

        recognition.onend = () => {
          if (recognitionRef.current === recognition) {
            // 意外中断（网络超时、静音等）—— 重启保持连续录音
            try {
              recognition.start()
              return
            } catch {
              // 重启失败，真正停止
            }
          }
          // 主动调用 stopListening() 后 recognitionRef.current 已为 null，正常收尾
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
    if (transcript.trim()) {
      setTranscript(prev => prev.trimEnd() + '\n--- 续录 ---\n')
    }
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
      // 只应用非空字段，防止覆盖已有内容
      const filteredPatch = Object.fromEntries(
        Object.entries(patch).filter(([, v]) => v !== '' && v !== null && v !== undefined)
      ) as Partial<InquiryData>

      setSummary(data?.transcript_summary || '')
      setSpeakerDialogue(Array.isArray(data?.speaker_dialogue) ? data.speaker_dialogue : [])
      setTranscriptId(data?.transcript_id || transcriptId)
      setLastAnalyzedTranscript(fullTranscript)

      if (isRecordMode) {
        // 追记模式：暂存 patch，展示预览，等待医生点「插入病历」确认
        setPendingPatch(filteredPatch)
        message.success('AI 整理完成，请确认下方内容后点击「插入病历」')
      } else {
        // 问诊模式：直接回填左侧问诊表单
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

  return (
    <Card
      size="small"
      style={{ marginBottom: 12, borderRadius: 10, background: '#f8fbff', borderColor: '#dbeafe' }}
      bodyStyle={{ padding: 12 }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <Space size={8}>
          <Tag color="blue" style={{ marginRight: 0 }}>
            语音录入
          </Tag>
          <Text style={{ fontSize: 12, color: '#475569' }}>
            保存原始录音与转写，并让 AI 识别对话结构
          </Text>
        </Space>
        <Space size={6}>
          {uploadingAudio && <Tag color="purple">上传并转写中...</Tag>}
          {listening && <Tag color="red">录音中</Tag>}
        </Space>
      </div>

      {(!speechSupported || !recordingSupported) && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 10 }}
          message="当前浏览器能力有限，建议使用最新版 Chrome / Edge；若不支持实时转写，仍可手动粘贴转写文本再点 AI 整理。"
        />
      )}

      <Space wrap style={{ marginBottom: 10 }}>
        {listening ? (
          /* 录音中：只显示停止按钮 */
          <Button
            danger
            type="primary"
            icon={<PauseCircleOutlined />}
            onClick={stopListening}
            style={{ borderRadius: 6 }}
          >
            停止录音
          </Button>
        ) : fullTranscript ? (
          /* 有内容、未录音：继续录音 + AI整理 + 清空 */
          <>
            <Button
              icon={<AudioOutlined />}
              onClick={handleContinueRecording}
              style={{ borderRadius: 6 }}
            >
              继续录音
            </Button>
            <Button
              type="primary"
              icon={<RobotOutlined />}
              loading={structuring}
              onClick={handleStructure}
              style={{
                borderRadius: 6,
                background: lastAnalyzedTranscript === fullTranscript ? '#0ea5e9' : '#7c3aed',
                borderColor: lastAnalyzedTranscript === fullTranscript ? '#0ea5e9' : '#7c3aed',
              }}
            >
              {lastAnalyzedTranscript === fullTranscript ? '重新分析' : 'AI分析并整理'}
            </Button>
            <Button
              icon={<DeleteOutlined />}
              onClick={() => {
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
                      } catch {
                        // 静默处理，即使后端删除失败也清空前端
                      }
                    }
                    setTranscript('')
                    setSummary('')
                    setSpeakerDialogue([])
                    setTranscriptId(null)
                  },
                })
              }}
              style={{ borderRadius: 6 }}
            >
              清空重录
            </Button>
          </>
        ) : (
          /* 初始状态：只显示开始录音 */
          <Button
            type="primary"
            icon={<AudioOutlined />}
            onClick={startListening}
            style={{ borderRadius: 6 }}
          >
            开始录音
          </Button>
        )}
      </Space>

      <TextArea
        rows={6}
        value={fullTranscript}
        onChange={e => {
          setTranscript(e.target.value)
          setInterimText('')
        }}
        placeholder="这里会实时显示语音转写内容，也支持手动粘贴第三方 ASR 的转写文本"
        style={{ borderRadius: 8, marginBottom: 8 }}
      />

      {summary && (
        <Alert
          type="info"
          showIcon
          icon={<FileTextOutlined />}
          message="本段对话摘要"
          description={summary}
          style={{ marginBottom: 8 }}
        />
      )}

      {speakerDialogue.length > 0 && (
        <Card
          size="small"
          style={{ marginBottom: 8, borderRadius: 8, background: '#fff' }}
          bodyStyle={{ padding: 10 }}
        >
          <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Tag color="cyan" style={{ marginRight: 0 }}>
              角色分析
            </Tag>
            <Text style={{ fontSize: 12, color: '#64748b' }}>
              AI 会尽量区分医生与患者；不确定内容会单独标记
            </Text>
          </div>
          <List
            size="small"
            dataSource={speakerDialogue}
            renderItem={item => (
              <List.Item style={{ padding: '6px 0', borderBlockEnd: '1px solid #f1f5f9' }}>
                <Space align="start">
                  <Tag
                    color={SPEAKER_META[item.speaker]?.color || 'default'}
                    style={{ marginRight: 0 }}
                  >
                    {SPEAKER_META[item.speaker]?.label || '待确认'}
                  </Tag>
                  <Text style={{ fontSize: 12 }}>{item.text}</Text>
                </Space>
              </List.Item>
            )}
          />
        </Card>
      )}

      {/* 模式说明文字：追记模式与问诊模式提示不同 */}
      <Text style={{ fontSize: 12, color: '#64748b' }}>
        {isRecordMode
          ? '语音原文会在后台保存；AI整理后展示预览，确认无误后点击「插入病历」写入对应章节。'
          : '语音原文会在后台保存；AI整理后会自动回填问诊字段，点击「保存问诊信息」后同步到病历编辑区。'}
      </Text>

      {/* 追记模式下的结构化结果预览区 */}
      {isRecordMode && pendingPatch && Object.keys(pendingPatch).length > 0 && (
        <div
          style={{
            marginTop: 10,
            background: '#f0fdf4',
            border: '1px solid #86efac',
            borderRadius: 8,
            padding: '10px 12px',
          }}
        >
          <Text
            strong
            style={{ fontSize: 12, color: '#166534', display: 'block', marginBottom: 6 }}
          >
            AI 整理结果（确认后插入病历）：
          </Text>
          {/* 遍历 patch 中有值且有章节映射的字段，展示字段名→内容 */}
          {Object.entries(pendingPatch)
            .filter(
              ([k, v]) => v && FIELD_TO_SECTION[k] !== undefined && FIELD_TO_SECTION[k] !== ''
            )
            .map(([k, v]) => (
              <div key={k} style={{ fontSize: 12, marginBottom: 4, lineHeight: 1.5 }}>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {FIELD_NAME_LABEL[k] || k}（{FIELD_TO_SECTION[k]}）：
                </Text>
                <Text style={{ fontSize: 12 }}>{String(v)}</Text>
              </div>
            ))}
          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
            <Button
              type="primary"
              size="small"
              icon={<MedicineBoxOutlined />}
              onClick={() => {
                // 将 patch 传给父组件的 onApplyToRecord 回调，写入病历章节
                onApplyToRecord!(pendingPatch)
                setPendingPatch(null)
              }}
              style={{ borderRadius: 6, background: '#16a34a', borderColor: '#16a34a' }}
            >
              插入病历
            </Button>
            <Button size="small" onClick={() => setPendingPatch(null)} style={{ borderRadius: 6 }}>
              取消
            </Button>
          </div>
        </div>
      )}
      {transcriptId && (
        <div style={{ marginTop: 8 }}>
          <div
            style={{
              background: '#f1f5f9',
              borderRadius: 8,
              padding: '8px 12px',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}
          >
            <SaveOutlined style={{ color: '#64748b', fontSize: 13, flexShrink: 0 }} />
            <Text style={{ fontSize: 12, color: '#475569', flexShrink: 0 }}>
              录音 #{transcriptId.slice(-6).toUpperCase()}
            </Text>
            {/* 使用短期音频令牌（5分钟过期），避免完整会话 JWT 出现在 URL/日志中 */}
            {audioToken ? (
              <audio
                controls
                src={`/api/v1/ai/voice-records/${transcriptId}/audio?token=${audioToken}`}
                style={{ flex: 1, height: 32, minWidth: 0 }}
              />
            ) : (
              <Text style={{ fontSize: 12, color: '#94a3b8' }}>音频加载中...</Text>
            )}
          </div>
        </div>
      )}
    </Card>
  )
}
