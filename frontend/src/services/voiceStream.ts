/**
 * 实时语音识别客户端（services/voiceStream.ts）
 *
 * 职责：
 *   1. 通过 AudioContext + ScriptProcessor 从麦克风抽取 PCM16 / 16kHz 单声道数据
 *   2. 通过 WebSocket 连接后端 /api/v1/ai/voice-stream 代理，实时上送音频帧
 *   3. 接收后端推回的识别结果（partial/final/finished）并通过回调暴露给 UI
 *
 * 使用方式：
 *   const handle = await startVoiceStream(token, {
 *     onStarted: () => ...,
 *     onPartial: (text) => ...,  // 中间结果（可能变化）
 *     onFinal:   (text) => ...,  // 终稿句子（不再变化）
 *     onError:   (msg) => ...,
 *     onFinished:() => ...,
 *   })
 *   // 停止：
 *   await handle.stop()
 */

/** 阿里云 Paraformer-realtime-v2 支持 16kHz / 8kHz 两档，这里固定 16kHz */
const TARGET_SAMPLE_RATE = 16000
/** ScriptProcessor 每帧采样数，≈128ms 延迟，兼顾实时性与 WebSocket 传输频率 */
const BUFFER_SIZE = 2048

export interface VoiceStreamCallbacks {
  /** 后端已与阿里云建立会话，客户端可开始说话 */
  onStarted?: () => void
  /** 收到中间识别结果（随后可能被新结果覆盖） */
  onPartial?: (text: string) => void
  /** 收到最终识别结果（一整句定稿，不再变化） */
  onFinal?: (text: string) => void
  /** WebSocket 或阿里云任务异常 */
  onError?: (message: string) => void
  /** 任务正常结束（stop 后由服务端确认） */
  onFinished?: () => void
}

export interface VoiceStreamHandle {
  /** 停止录音并等待识别任务收尾，超过 3s 未收到 finished 则强制关闭 */
  stop: () => Promise<void>
}

/** 建立实时语音识别会话，返回控制句柄。任何建连/鉴权异常会直接抛出，由调用方处理兜底。 */
export async function startVoiceStream(
  token: string,
  callbacks: VoiceStreamCallbacks
): Promise<VoiceStreamHandle> {
  // 1. 组装 WebSocket URL
  // 生产 wss 走独立 8443 端口（HTTP/1.1，避开主站 HTTP/2 + RFC 8441 兼容性问题）；
  // 本地 ws 通过 Vite 代理同源（dev server 不区分端口）。判断方式：当前是 https
  // 且不是 localhost → 拼 8443；否则保持原行为（host 含 dev port 5174）。
  const isHttps = window.location.protocol === 'https:'
  const wsProtocol = isHttps ? 'wss' : 'ws'
  const isLocalhost =
    window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  const wsHost =
    isHttps && !isLocalhost
      ? `${window.location.hostname}:8443` // 生产 wss 专用端口
      : window.location.host // 本地走 Vite 同源代理
  const wsUrl = `${wsProtocol}://${wsHost}/api/v1/ai/voice-stream?token=${encodeURIComponent(token)}`
  const ws = new WebSocket(wsUrl)
  ws.binaryType = 'arraybuffer'

  // 2. 等待 WebSocket 打开（失败直接 reject，调用方会走兜底）
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('WebSocket 连接超时')), 5000)
    ws.onopen = () => {
      clearTimeout(timer)
      resolve()
    }
    ws.onerror = () => {
      clearTimeout(timer)
      reject(new Error('WebSocket 连接失败'))
    }
  })

  // 3. 注册后端消息回调
  let finishedResolver: (() => void) | null = null
  ws.onmessage = event => {
    try {
      const msg = JSON.parse(event.data as string)
      switch (msg.type) {
        case 'started':
          callbacks.onStarted?.()
          break
        case 'partial':
          callbacks.onPartial?.(msg.text || '')
          break
        case 'final':
          callbacks.onFinal?.(msg.text || '')
          break
        case 'error':
          callbacks.onError?.(msg.message || '识别出错')
          break
        case 'finished':
          callbacks.onFinished?.()
          finishedResolver?.()
          break
      }
    } catch {
      // 非 JSON 消息忽略
    }
  }
  ws.onerror = () => callbacks.onError?.('WebSocket 通信异常')

  // 4. 打开麦克风 + 创建 16kHz AudioContext
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
  // sampleRate 选项在部分浏览器可能被忽略，后续用 actualRate 做重采样兜底
  const ctx: AudioContext = new AudioCtx({ sampleRate: TARGET_SAMPLE_RATE })
  const actualRate = ctx.sampleRate
  const source = ctx.createMediaStreamSource(stream)
  const processor = ctx.createScriptProcessor(BUFFER_SIZE, 1, 1)

  processor.onaudioprocess = e => {
    if (ws.readyState !== WebSocket.OPEN) return
    const input = e.inputBuffer.getChannelData(0)
    // Float32 [-1, 1] → Int16 PCM（必要时先线性插值降采样到 16kHz）
    const resampled =
      actualRate === TARGET_SAMPLE_RATE ? input : downsample(input, actualRate, TARGET_SAMPLE_RATE)
    const pcm = new Int16Array(resampled.length)
    for (let i = 0; i < resampled.length; i++) {
      const s = Math.max(-1, Math.min(1, resampled[i]))
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff
    }
    ws.send(pcm.buffer)
  }

  source.connect(processor)
  processor.connect(ctx.destination)

  // 5. 返回停止句柄：停止麦克风 → 通知后端 finish → 等 finished 或超时
  const stop = async () => {
    try {
      source.disconnect()
      processor.disconnect()
      stream.getTracks().forEach(t => t.stop())
      await ctx.close()
    } catch {
      // 清理过程中的异常不影响后续流程
    }
    if (ws.readyState === WebSocket.OPEN) {
      ws.send('finish')
      await new Promise<void>(resolve => {
        finishedResolver = resolve
        setTimeout(resolve, 3000) // 3s 超时保护
      })
      try {
        ws.close()
      } catch {}
    }
  }

  return { stop }
}

/** 简单线性插值降采样，够用于语音识别（非高保真场景） */
function downsample(input: Float32Array, inRate: number, outRate: number): Float32Array {
  if (outRate === inRate) return input
  const ratio = inRate / outRate
  const outLength = Math.floor(input.length / ratio)
  const output = new Float32Array(outLength)
  for (let i = 0; i < outLength; i++) {
    const idx = i * ratio
    const i0 = Math.floor(idx)
    const i1 = Math.min(i0 + 1, input.length - 1)
    const frac = idx - i0
    output[i] = input[i0] * (1 - frac) + input[i1] * frac
  }
  return output
}
