/**
 * AudioWorklet processor —— 实时语音录入用（public/voice-stream-processor.js）
 *
 * 用途：在 audio rendering thread 上抽取麦克风原始 PCM 数据，通过 MessagePort
 * 转发到主线程，主线程负责 PCM16 编码 + WebSocket 上送。
 *
 * 替代旧的 ScriptProcessorNode（已 deprecated），消除 console
 *   "[Deprecation] ScriptProcessorNode is deprecated. Use AudioWorkletNode instead."
 *
 * 为什么放 public/ 而不是 src/：
 *   AudioWorklet 必须由浏览器以独立模块方式加载（audio rendering thread），
 *   不能通过 Vite 打包进 main bundle。放 public/ 目录后 Vite 会原样 copy 到
 *   dist/，URL 直接走 /voice-stream-processor.js 即可，无需走模块系统。
 *
 * 加载方式（主线程 voiceStream.ts）：
 *   await audioContext.audioWorklet.addModule('/voice-stream-processor.js')
 *   const node = new AudioWorkletNode(audioContext, 'voice-stream-processor')
 *
 * 注意：本文件运行在受限的 AudioWorkletGlobalScope 环境，
 *   - 没有 window / document / 任何 DOM API
 *   - 不能 import npm 包
 *   - 复杂逻辑（PCM16 转换、降采样）都在主线程做，本文件只做"取数 + 转发"
 */

class VoiceStreamProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]
    if (input && input[0] && input[0].length > 0) {
      // copy 一份再 transfer——audio thread 内部的 input buffer 是复用的，
      // 直接 transfer 原 buffer 会导致下一次 process 拿到 detached buffer 抛错。
      const out = new Float32Array(input[0].length)
      out.set(input[0])
      this.port.postMessage(out, [out.buffer])
    }
    return true
  }
}

registerProcessor('voice-stream-processor', VoiceStreamProcessor)
