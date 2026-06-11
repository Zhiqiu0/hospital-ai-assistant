/**
 * 桌面 Agent HTTP 客户端（services/desktopAgent.ts）
 *
 * 嵌入模式专用：通过 127.0.0.1:7788 调本机桌面 Agent。
 * 区别于 services/api.ts（调云端后端 mediscribe.cn）。
 *
 * 端口选择策略：
 *   - 默认 7788
 *   - 占用时 Agent 会切换到 7789-7799，启动时把实际端口写到 URL
 *     hash（#agent_port=xxx），前端从 URL 读
 *
 * 安全：
 *   - 所有请求带 Authorization: Bearer <embed_token>（URL 拿来的）
 *   - CORS 由 Agent 端配置：仅允许 https://mediscribe.cn / http://localhost:5174
 */

import { useAuthStore } from '@/store/authStore'

const DEFAULT_AGENT_PORT = 7788
const AGENT_PORT_RANGE = [7788, 7789, 7790, 7791, 7792]

interface PingResponse {
  status: 'ok'
  version: string
  his_detected: boolean
  his_brand?: string
}

interface FillRequest {
  encounter_id: string
  fields: Array<{
    section: 'intake' | 'record' | 'diagnosis'
    field_key: string
    value: unknown
  }>
}

interface FillFieldResult {
  field_key: string
  his_automation_id?: string | null
  status: 'success' | 'failed' | 'skipped' | 'fallback_clipboard'
  duration_ms: number
  error_message?: string | null
}

interface FillResult {
  status: 'success' | 'partial' | 'failed'
  encounter_id: string
  total_fields: number
  succeeded: number
  failed: number
  duration_ms: number
  field_results: FillFieldResult[]
}

class DesktopAgentClient {
  private port: number = DEFAULT_AGENT_PORT
  private cachedPing: { result: PingResponse; at: number } | null = null

  /** 每次请求时从 authStore 实时拿 token,刷新后不丢(authStore localStorage persist) */
  private getToken(): string | null {
    return useAuthStore.getState().token
  }

  /** @deprecated 保留兼容,token 现在统一从 authStore 取 */
  setToken(_token: string) {
    /* no-op: 改为每次请求时从 authStore.getState().token 读 */
  }

  /** 尝试在端口范围内找到运行中的 Agent，找到后绑定端口供后续调用 */
  async discover(): Promise<boolean> {
    for (const port of AGENT_PORT_RANGE) {
      try {
        const r = await fetch(`http://127.0.0.1:${port}/ping`, {
          method: 'GET',
          // 不带 Authorization，ping 接口公开（探测 Agent 是否在）
          signal: AbortSignal.timeout(500),
        })
        if (r.ok) {
          this.port = port
          return true
        }
      } catch {
        /* 端口未开 / 超时，继续下一个 */
      }
    }
    return false
  }

  /** 探测 Agent 是否在线 + HIS 状态。结果缓存 3 秒避免高频抖动 */
  async ping(): Promise<PingResponse | null> {
    const now = Date.now()
    if (this.cachedPing && now - this.cachedPing.at < 3000) {
      return this.cachedPing.result
    }
    try {
      const r = await fetch(`http://127.0.0.1:${this.port}/ping`, {
        method: 'GET',
        signal: AbortSignal.timeout(1500),
      })
      if (!r.ok) return null
      const result = (await r.json()) as PingResponse
      this.cachedPing = { result, at: now }
      return result
    } catch {
      this.cachedPing = null
      return null
    }
  }

  /** 调用 Agent 把生成的病历填入 HIS */
  async fill(req: FillRequest): Promise<FillResult> {
    const token = this.getToken()
    if (!token) {
      throw new Error('未登录，无法调用 Agent')
    }
    const r = await fetch(`http://127.0.0.1:${this.port}/fill`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(req),
      // 整体填入预期 < 40 秒（YAML global_settings.total_timeout_s）
      signal: AbortSignal.timeout(60_000),
    })
    if (!r.ok) {
      throw new Error(`Agent 填入失败：HTTP ${r.status}`)
    }
    return r.json()
  }

  /** 订阅填入进度 WebSocket，回调收到每个字段的填入事件 */
  connectProgress(onEvent: (e: FillFieldResult & { progress?: number }) => void): WebSocket {
    const token = this.getToken()
    if (!token) {
      throw new Error('未登录，无法订阅进度')
    }
    // 通过 query 传 token（WebSocket 协议不支持自定义请求头）
    const ws = new WebSocket(
      `ws://127.0.0.1:${this.port}/progress?token=${encodeURIComponent(token)}`
    )
    ws.onmessage = e => {
      try {
        onEvent(JSON.parse(e.data))
      } catch {
        /* 忽略无法解析的消息 */
      }
    }
    return ws
  }
}

export const desktopAgent = new DesktopAgentClient()
export type { FillRequest, FillResult, FillFieldResult, PingResponse }
