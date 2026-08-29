/**
 * 病程记录草稿自动保存（2026-08-14 第七轮审计 #34）
 *
 * 为什么需要：
 *   ProgressNotePanel 的正文只活在组件的 useState 里，既不进 store 也不落库，
 *   全靠医生自己点「保存草稿」。于是下面每一种都会**无声吞掉已写的内容**：
 *     · 在左侧时间轴点了另一份文书 —— useEffect 按新 item.id 重置正文
 *     · 关标签页 / 刷新 / 会话过期跳登录
 *     · 面板因布局切换而卸载
 *   住院一次查房要写好几份病程，写了十分钟切一下就没了，医生根本不会预期。
 *   主编辑器早就有 5 秒防抖自动保存，唯独这里没有。
 *
 * 做法与主编辑器对齐：5 秒尾防抖 + 切换条目/卸载时立即 flush。
 * 已签发（只读）的文书不参与自动保存。
 */
import { useCallback, useEffect, useRef } from 'react'
import type { Dayjs } from 'dayjs'

import api from '@/services/api'

/** 与主编辑器一致的防抖窗口 */
const AUTOSAVE_DEBOUNCE_MS = 5000

type Snapshot = {
  encounterId: string
  itemId: string
  /** 病历类型：草稿接口按 (encounter_id, record_type) 定位，不是按 id */
  recordType: string
  content: string
  recordedAt: Dayjs | null
}

export function useProgressNoteAutosave(params: {
  encounterId: string | null
  itemId: string | undefined
  /** 病历类型（course_record / senior_round …），草稿接口据此定位 */
  recordType: string | undefined
  content: string
  recordedAt: Dayjs | null
  /** 只读（已签发/入院记录）时不自动保存 */
  disabled: boolean
}) {
  const { encounterId, itemId, recordType, content, recordedAt, disabled } = params

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 最近一次「已知落库」的正文：用它判断脏，避免刚水合就回写一遍
  const savedRef = useRef<string | null>(null)
  // 当前待保存快照。用 ref 而不是闭包捕获——切换条目时要把**上一条**的内容
  // 存到**上一条**的 id 上，闭包里的值那会儿已经被 useEffect 重置了。
  const pendingRef = useRef<Snapshot | null>(null)

  const flush = useCallback(async () => {
    const pending = pendingRef.current
    pendingRef.current = null
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    if (!pending) return
    // 脏判断含记录时间（2026-08-28 补记链路修复）：只改 DatePicker 不改正文时
    // 原判断直接跳过 flush，医生选的"实际记录时点"永远到不了后端
    const snapKey = `${pending.recordedAt?.format('YYYY-MM-DDTHH:mm:ss') ?? ''}\u0001${pending.content}`
    if (snapKey === savedRef.current) return
    try {
      // 走正式病历的草稿保存（2026-08-14 统一文书模型）：
      // 原先打的是 progress-notes，那张表没有版本、没有签名链、不回写 HIS、
      // 不进任何病历列表，而界面上同样显示「已签发」。
      await api.post('/medical-records/auto-save-draft', {
        encounter_id: pending.encounterId,
        record_type: pending.recordType,
        content: pending.content,
        // 本地 naive ISO（无 Z/tz），配合后端 TIMESTAMP WITHOUT TIME ZONE。
        // 这是"这份文书对应的诊疗时点"，与系统录入时间差得多会被标为补记。
        recorded_at: pending.recordedAt?.format('YYYY-MM-DDTHH:mm:ss'),
      })
      savedRef.current = snapKey
    } catch {
      // 失败必须把快照放回去（2026-08-29 离线审计修复）：flush 开头已把
      // pendingRef 清空，原实现失败后不回填——"下一轮防抖会再试"只有正文
      // **再次变化**才成立，医生写完停笔后这次失败的增量就永远丢了：切条目
      // /关页时的 flush 读到的是空快照，直接早退。回填后，切条目/卸载/网络
      // 恢复（下方 online 监听）的每次 flush 都能重试这份内容。
      // 若失败期间医生又输入了新内容（pendingRef 已被新快照占据），
      // 新快照本就包含全部最新正文，旧快照丢弃无损。
      if (!pendingRef.current) {
        pendingRef.current = pending
      }
    }
  }, [])

  // 条目切换：先把上一条 flush 掉，再把基线切到新条目
  useEffect(() => {
    void flush()
    savedRef.current = null
    // 只在 itemId 变化时跑；flush 用的是 ref 里的旧快照，与新 item 无关
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemId])

  // 正文变化 → 记快照 + 重置防抖
  useEffect(() => {
    if (disabled || !encounterId || !itemId || !recordType) return
    // 首次水合（savedRef 为空）时把当前状态当作基线，不触发一次无谓的回写
    // （基线含记录时间，与 flush 的脏判断同一复合键口径）
    if (savedRef.current === null) {
      savedRef.current = `${recordedAt?.format('YYYY-MM-DDTHH:mm:ss') ?? ''}\u0001${content}`
      return
    }
    pendingRef.current = { encounterId, itemId, recordType, content, recordedAt }
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => void flush(), AUTOSAVE_DEBOUNCE_MS)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [content, recordedAt, encounterId, itemId, recordType, disabled, flush])

  // 卸载 / 关标签页：来不及等防抖，立刻 flush。
  // online：断网期间失败回填的快照（见 flush catch）在网络恢复时自动补传，
  // 医生停笔不动也能恢复（2026-08-29 离线审计）。
  useEffect(() => {
    const onHide = () => void flush()
    const onOnline = () => void flush()
    window.addEventListener('pagehide', onHide)
    window.addEventListener('online', onOnline)
    return () => {
      window.removeEventListener('pagehide', onHide)
      window.removeEventListener('online', onOnline)
      void flush()
    }
  }, [flush])

  /** 手动保存成功后调用，把基线对齐，避免紧接着又自动回写一次 */
  const markSaved = useCallback((saved: string) => {
    savedRef.current = saved
    pendingRef.current = null
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  return { flush, markSaved }
}
