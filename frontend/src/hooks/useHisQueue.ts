/**
 * HIS 叫号队列 Hook（hooks/useHisQueue.ts）
 *
 * 数据两条腿（2026-08-11 业务联动）：
 *   1. 开页/重连时拉 GET /his/queue/today（DB 权威数据，推送丢了也不丢病人）
 *   2. POST /his/queue/stream SSE 长连接实时收事件（admit 叫号 / writeback_result）
 *
 * 连接管理：
 *   - 后端保险丝关闭（503）→ enabled=false，工作台完全隐藏叫号入口
 *   - SSE 断线指数退避重连（2s 起步、30s 封顶），重连成功后重拉队列
 *   - 全程用原生 fetch（不走 axios 拦截器），503/断线不弹全局错误 toast
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuthStore } from '@/store/authStore'
import { streamSSE } from '@/services/streamSSE'

/** 今日队列条目（GET /his/queue/today 的 items 元素 / admit 事件字段子集） */
export interface HisQueueItem {
  encounter_id: string
  visit_no?: string | null
  patient_name: string
  gender?: string | null
  birth_date?: string | null
  dept_name?: string | null
  status: string // in_progress / completed
  is_first_visit?: boolean | null
  visited_at?: string | null
  /** 回写状态：success / skipped / write_failed / refresh_failed / error / null(未触发) */
  writeback_status?: string | null
}

/** SSE 事件（admit / writeback_result / connected） */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type HisQueueEvent = { type: string; [key: string]: any }

interface UseHisQueueOptions {
  /** 收到新患者叫号事件（去重后的增量），由组件决定提示音/横幅/自动接诊 */
  onAdmit?: (item: HisQueueItem) => void
  /** 收到回写结果事件 */
  onWritebackResult?: (ev: HisQueueEvent) => void
}

/** 重连退避：起步 2s，翻倍封顶 30s */
const RECONNECT_BASE_MS = 2000
const RECONNECT_MAX_MS = 30000

export function useHisQueue({ onAdmit, onWritebackResult }: UseHisQueueOptions = {}) {
  const token = useAuthStore(s => s.token)
  // enabled: null=探测中 false=保险丝关(隐藏入口) true=启用
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [connected, setConnected] = useState(false)
  const [items, setItems] = useState<HisQueueItem[]>([])
  // 回调经 ref 转发：SSE 循环只建一次，不因调用方每次渲染换回调而重连
  // （赋值放 effect 而非渲染期，符合 react ref 使用规则）
  const handlersRef = useRef({ onAdmit, onWritebackResult })
  useEffect(() => {
    handlersRef.current = { onAdmit, onWritebackResult }
  }, [onAdmit, onWritebackResult])

  // 上次快照（2026-08-29 离线审计修复）：断线窗口内叫号的患者此前只会无声
  // 出现在补拉列表里——提示音/横幅/自动接诊全挂在 SSE admit 事件上，错过就
  // 永远错过。补拉后与上次快照 diff，把漏掉的叫号/回写失败补成同款通知。
  // null = 首次加载（开页时队列里的存量患者不该触发一轮提示音轰炸）。
  const prevItemsRef = useRef<Map<string, HisQueueItem> | null>(null)

  /** 拉今日队列（开页 + 每次重连成功后调用）。返回是否可用（503 → false）。 */
  const refresh = useCallback(async (): Promise<boolean> => {
    if (!token) return false
    try {
      const res = await fetch('/api/v1/his/queue/today', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.status === 503) {
        setEnabled(false)
        return false
      }
      // 401：token 已过期/失效，停止 SSE 重连循环（2026-08-11 审计修复）：
      // 否则会无限重连绕过全局登出。返回 false 让上层循环退出。
      if (res.status === 401) return false
      // 403：未改初始密码的账号被服务端硬拦（2026-08-13 第三轮审计修复）。
      // 这不是瞬时故障——不改密永远是 403，退避重连会在改密弹窗背后每 30 秒
      // 打一次服务器，改完密码前一直打。同 401 处理：退出循环，等重登/改密后
      // token 变化触发整个 effect 重建。
      if (res.status === 403) return false
      if (!res.ok) return true // 瞬时错误：保持现状，等下次重连再拉
      const data = (await res.json()) as { items: HisQueueItem[] }
      const fresh = data.items || []
      const prev = prevItemsRef.current
      if (prev) {
        for (const it of fresh) {
          const old = prev.get(it.encounter_id)
          // 断线窗口内的新叫号：补发 onAdmit（提示音/横幅/自动接诊与实时事件同款）
          if (!old && it.status === 'in_progress') {
            handlersRef.current.onAdmit?.(it)
          }
          // 断线窗口内的回写失败：补发红色驻留通知（回写失败要医生去 HIS 兜底，
          // 错过通知只剩抽屉里的红标，医生不开抽屉就永远不知道）
          const bad = it.writeback_status
          if (bad && bad !== 'success' && old?.writeback_status !== bad) {
            handlersRef.current.onWritebackResult?.({
              type: 'writeback_result',
              encounter_id: it.encounter_id,
              ok: false,
              status: bad,
              message: '连接中断期间有病历回写未成功，请在叫号列表重试',
            })
          }
        }
      }
      prevItemsRef.current = new Map(fresh.map(x => [x.encounter_id, x]))
      setItems(fresh)
      setEnabled(true)
      return true
    } catch {
      return true // 网络抖动不改变 enabled 判定
    }
  }, [token])

  useEffect(() => {
    if (!token) return
    let stopped = false
    let ctrl: AbortController | null = null

    const run = async () => {
      // 先探测保险丝：503 直接收工，不建 SSE
      const ok = await refresh()
      if (stopped || !ok) return

      let delay = RECONNECT_BASE_MS
      while (!stopped) {
        ctrl = new AbortController()
        try {
          await streamSSE(
            '/api/v1/his/queue/stream',
            {},
            token,
            {
              onEvent: ev => {
                delay = RECONNECT_BASE_MS // 收到任何事件说明链路健康，重置退避
                if (ev.type === 'connected') {
                  setConnected(true)
                  return
                }
                if (ev.type === 'admit') {
                  const item: HisQueueItem = {
                    encounter_id: ev.encounter_id,
                    visit_no: ev.visit_no,
                    patient_name: ev.patient_name,
                    gender: ev.gender,
                    birth_date: ev.birth_date,
                    dept_name: ev.dept_name,
                    status: 'in_progress',
                    is_first_visit: ev.is_first_visit,
                    visited_at: new Date().toISOString(),
                  }
                  // 队列去重插入（重复推送 reused 时刷新条目位置即可）
                  setItems(prev => [
                    item,
                    ...prev.filter(x => x.encounter_id !== item.encounter_id),
                  ])
                  // 同步 diff 快照：实时事件已通知过，重连补拉不再重复通知
                  prevItemsRef.current?.set(item.encounter_id, item)
                  // 重复推送（医生在 HIS 反复打开）不再横幅打扰
                  if (!ev.reused) handlersRef.current.onAdmit?.(item)
                  return
                }
                if (ev.type === 'writeback_result') {
                  handlersRef.current.onWritebackResult?.(ev)
                  // 同步 diff 快照（同 admit：防重连补拉重复通知）
                  const snap = prevItemsRef.current?.get(ev.encounter_id)
                  if (snap) snap.writeback_status = ev.status
                  // 同步队列条目：成功则标记已签发；无论成败都记录回写状态
                  // （失败的条目在抽屉里显示红色标签 + 重试入口）
                  setItems(prev =>
                    prev.map(x =>
                      x.encounter_id === ev.encounter_id
                        ? {
                            ...x,
                            status: ev.ok ? 'completed' : x.status,
                            writeback_status: ev.status,
                          }
                        : x
                    )
                  )
                }
              },
            },
            { signal: ctrl.signal }
          )
        } catch (e) {
          if ((e as Error)?.name === 'AbortError') break
          // 403 与 401 同理：不是瞬时故障，重连多少次都还是 403，直接退出循环。
          // streamSSE 对非 2xx 抛的是 Error("HTTP <status>")，按消息匹配。
          const msg = (e as Error)?.message || ''
          if (msg === 'HTTP 401' || msg === 'HTTP 403') break
          // 其余断线/HTTP 错误：走退避重连
        }
        setConnected(false)
        if (stopped) break
        await new Promise(r => setTimeout(r, delay))
        delay = Math.min(delay * 2, RECONNECT_MAX_MS)
        // 重连前重拉队列：断线期间的推送事件可能已丢，DB 是权威
        const stillOk = await refresh()
        if (!stillOk) break
      }
    }

    void run()
    return () => {
      stopped = true
      ctrl?.abort()
    }
    // refresh 依赖 token；token 变化（重登）时整个循环重建
  }, [token, refresh])

  /** 手动把某接诊标记为已完成（签发后本地即时反馈，不等 SSE） */
  const markCompleted = useCallback((encounterId: string) => {
    setItems(prev =>
      prev.map(x => (x.encounter_id === encounterId ? { ...x, status: 'completed' } : x))
    )
  }, [])

  return { enabled: enabled === true, connected, items, refresh, markCompleted }
}
