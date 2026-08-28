/**
 * HTTP SSE 流式请求工具（services/streamSSE.ts）
 *
 * 用途：
 *   后端 AI 接口（quick-generate / quick-polish / quick-supplement / quick-qc）
 *   均使用 SSE（text/event-stream）流式返回。本工具统一封装了：
 *     1. 鉴权头 (Bearer token) 注入
 *     2. AbortController 透传（外部可中止）
 *     3. SSE 行解析（data: 前缀 + JSON）
 *     4. 错误事件统一抛出（type=error → throw Error）
 *
 * 注意：
 *   只覆盖 HTTP/1.1 + fetch 的 SSE 场景。voiceStream.ts 走的是 WebSocket
 *   协议（实时音频 + 双向握手），不在本工具范围内。
 */

export interface SSEHandlers {
  /** 文本块到达（type=chunk）。最常见的 onChunk 封装为短路，避免每个调用方都写 type 判断。 */
  onChunk?: (text: string) => void
  /** 通用事件分发：所有非 chunk/error 事件（如 QC 的 rule_issues / llm_issues / done）走这里。 */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onEvent?: (event: { type: string; [key: string]: any }) => void
}

export interface SSEOptions {
  /** 外部 AbortSignal；调用方在卸载或主动取消时触发。 */
  signal?: AbortSignal
}

/**
 * 发起 SSE POST 请求，按行解析 data: 事件并分发到 handlers。
 *
 * 错误处理：
 *   - HTTP 非 2xx：抛 `HTTP <status>`
 *   - 服务端推回 type=error 事件：抛 `obj.message || 'STREAM_ERROR'`
 *   - signal 被 abort：抛 AbortError，调用方判 `e.name === 'AbortError'` 决定是否报错
 *
 * 调用示例：
 *   await streamSSE('/api/v1/ai/quick-generate', payload, token, {
 *     onChunk: text => append(text),
 *   }, { signal: ctrl.signal })
 */
export async function streamSSE(
  url: string,
  body: object,
  token: string,
  handlers: SSEHandlers,
  options?: SSEOptions
): Promise<void> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    signal: options?.signal,
  })
  if (!res.ok) {
    // 尽量取后端 detail（如生成锁 429 的"您有一个 AI 生成任务正在进行中"），
    // 医生看到业务文案而不是裸状态码（2026-08-28 体检）
    let detail = ''
    try {
      detail = ((await res.json()) as { detail?: string })?.detail || ''
    } catch {
      /* 非 JSON 响应体，退回状态码 */
    }
    throw new Error(detail || `HTTP ${res.status}`)
  }
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  // 断流识别（2026-08-28 体检）：后端所有 SSE 流的成功路径都以 type=done 收尾
  // （generate/polish/qc 契约）。此前网络断流被当"正常结束"静默返回——医生
  // 拿到半截正文毫无提示，随后 auto-save 还会带旧基线撞 409 误导为"他端修改"。
  // 未见 done 即抛错，让调用方的失败路径（报错+回滚原文）接管。
  let doneSeen = false
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    // SSE 协议以 \n 分行，事件之间是 data: ... 行
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data:')) continue
      let obj: { type: string; [key: string]: unknown }
      try {
        obj = JSON.parse(line.slice(5).trim())
      } catch {
        // 非 JSON 行（心跳 / 注释）忽略
        continue
      }
      if (obj.type === 'error') {
        throw new Error(typeof obj.message === 'string' ? obj.message : 'STREAM_ERROR')
      }
      if (obj.type === 'done') {
        doneSeen = true
      }
      if (obj.type === 'chunk') {
        handlers.onChunk?.(typeof obj.text === 'string' ? obj.text : '')
      }
      // onEvent 的 event 字段签名仍是 any（见接口注释），调用方按 obj.xxx 访问
      handlers.onEvent?.(obj)
    }
  }
  if (!doneSeen) {
    throw new Error('AI 数据流意外中断，请重试')
  }
}
