/**
 * 语音录音会话编排 hook（hooks/useVoiceDialogueSession.ts）
 *
 * 2026-06-11 Round 5 拆分：从 useVoiceInputCard 抽出"一次录音的完整流程编排"，
 * 即从 getUserMedia 拿麦克风 → 实时 ASR 推流 → 停止 → 录音文件归档/兜底转写
 * 的全生命周期管理。useVoiceInputCard 只保留状态聚合 + UI 操作回调。
 *
 * 语音识别方案：
 *   主路径 — 阿里云 Paraformer 实时 ASR（via 后端 WebSocket 代理 /api/v1/ai/voice-stream）
 *   兜底路径 — WebSocket 建连失败时，停止录音后音频文件上传到后端由 Qwen-Audio 整段转写
 *
 * 注意：本文件的 unmount cleanup effect 是 2026-05-03 时序 bug 的治本修复，
 * 拆分时原样保留（详见 effect 上方注释），不要精简。
 */
import { useEffect, useRef, useState } from 'react'
import { message } from '@/services/messageBridge'
import { useAuthStore } from '@/store/authStore'
import { startVoiceStream, type VoiceStreamHandle } from '@/services/voiceStream'
import { uploadVoiceAudio } from '@/services/voiceTranscriptApi'

// ── 测试期开关：录音文件是否上传到后端归档 ─────────────────────────────────────
// 测试阶段医生反复录长音频会快速吃满测试服务器磁盘（uploads/voice_records/
// 永久存盘且暂无清理机制），暂关闭文件上传，只留 ASR 转写文字走 AI 整理路径——
// 病历生成、问诊填表、AI 整理这些主流程不受影响；唯一损失是"播放原始录音"
// 功能（无 voice_record_id）。
// 上线前切回 true，并配合后端加 uploads 目录的归档/清理策略。
const ENABLE_AUDIO_UPLOAD = false

interface SessionProps {
  visitType: 'outpatient' | 'inpatient'
  /** 当前接诊 ID（无接诊时禁止开始录音） */
  currentEncounterId: string | null
  /** 已确认转写 + 实时中间结果 拼接后的完整文本（由外层 memo 计算） */
  fullTranscript: string
  setTranscript: React.Dispatch<React.SetStateAction<string>>
  setInterimText: (value: string) => void
  setTranscriptId: (value: string | null) => void
}

/**
 * 管理一次录音会话：麦克风采集、实时 ASR 推流、MediaRecorder 存档、
 * 停止后的上传/兜底转写，以及组件卸载时的强制资源释放。
 */
export function useVoiceDialogueSession({
  visitType,
  currentEncounterId,
  fullTranscript,
  setTranscript,
  setInterimText,
  setTranscriptId,
}: SessionProps) {
  // 实时 ASR 流句柄（含 stop 方法），录音期间存活
  const voiceStreamRef = useRef<VoiceStreamHandle | null>(null)
  // 录音音频文件采集器（用于存档 + 作为 WebSocket 失败时的兜底转写源）
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
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

  useEffect(() => {
    transcriptRef.current = fullTranscript
  }, [fullTranscript])

  // ── 组件卸载强制清理（2026-05-03 治本）────────────────────────────────────
  // 之前用户报告"录音中途关掉网页，再开就只录到静音、ASR 0 句、刷新或换电脑都
  // 不行，要整体关浏览器才好"——根因是本 hook 没有 unmount cleanup：
  //   1. streamRef（MediaStream）的 getUserMedia tracks 没 stop → OS 层麦克风
  //      仍被前一个 tab/路由占着，新会话 getUserMedia 拿到 stale/muted track
  //      → 前端按帧发 PCM 但全是静音 → DashScope 收到全零音频静默不回结果
  //      → 前端等几秒触发"WebSocket 连接超时" → 主动断 → sentences=0
  //   2. voiceStreamRef（wss）没显式 close → 后端那条 connection 一直挂
  //   3. mediaRecorderRef 没停 → blob 数据继续累积内存泄漏
  // 整体关浏览器 = 杀进程 = 所有 OS 麦克风占用全释放，所以"重启浏览器就好"。
  // 加 unmount cleanup 后，无论用户怎么离开（关 tab / 切路由 / 刷新页面），
  // 麦克风、wss、MediaRecorder 都会被显式释放，下次进来一定拿到干净的 stream。
  useEffect(() => {
    return () => {
      // 1. 关 wss（stop 内部会发 finish + 关 socket，失败不阻断后续清理）
      const vs = voiceStreamRef.current
      voiceStreamRef.current = null
      if (vs) {
        try {
          // stop 返回 Promise，但 unmount 不等待；catch 防 unhandled rejection
          vs.stop().catch(() => {})
        } catch {
          /* 同步异常也忽略 */
        }
      }
      // 2. 停 MediaRecorder（onstop 回调可能再触发 upload，无所谓）
      const mr = mediaRecorderRef.current
      mediaRecorderRef.current = null
      if (mr && mr.state !== 'inactive') {
        try {
          mr.stop()
        } catch {
          /* 已经停过等异常忽略 */
        }
      }
      // 3. 释放麦克风 tracks——这一步是治本的核心，不释放 OS 层麦克风就一直被占
      const stream = streamRef.current
      streamRef.current = null
      if (stream) {
        stream.getTracks().forEach(t => {
          try {
            t.stop()
          } catch {
            /* track 已经 ended 等异常忽略 */
          }
        })
      }
    }
  }, [])

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
    // 测试期跳过音频归档：保留 transcript 文本走 AI 整理；不调后端 upload，
    // 不占测试服务器磁盘；不弹"已保存" toast 避免误导。详见 ENABLE_AUDIO_UPLOAD 注释。
    if (!ENABLE_AUDIO_UPLOAD) return
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
      } catch (err) {
        streamFallbackRef.current = true
        const errMsg = (err as { message?: string })?.message || '连接失败'
        message.warning(`实时转写未启用（${errMsg}），录音继续，停止后自动云端转写`, 5)
      }

      setListening(true)
      message.success('已开始语音录入')
    } catch {
      stopTracks()
      message.error('无法访问麦克风，请检查浏览器权限')
    }
  }

  return {
    recordingSupported,
    listening,
    uploadingAudio,
    startListening,
    stopListening,
  }
}
