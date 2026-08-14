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
  content: string
  recordedAt: Dayjs | null
}

export function useProgressNoteAutosave(params: {
  encounterId: string | null
  itemId: string | undefined
  content: string
  recordedAt: Dayjs | null
  /** 只读（已签发/入院记录）时不自动保存 */
  disabled: boolean
}) {
  const { encounterId, itemId, content, recordedAt, disabled } = params

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
    if (pending.content === savedRef.current) return
    try {
      await api.patch(`/encounters/${pending.encounterId}/progress-notes/${pending.itemId}`, {
        content: pending.content,
        // 本地 naive ISO（无 Z/tz），配合后端 TIMESTAMP WITHOUT TIME ZONE
        recorded_at: pending.recordedAt?.format('YYYY-MM-DDTHH:mm:ss'),
      })
      savedRef.current = pending.content
    } catch {
      // 自动保存失败不打扰医生（他随时可以点「保存草稿」拿到明确反馈）；
      // 保留 savedRef 不变，下一轮防抖会再试一次。
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
    if (disabled || !encounterId || !itemId) return
    // 首次水合（savedRef 为空）时把当前正文当作基线，不触发一次无谓的回写
    if (savedRef.current === null) {
      savedRef.current = content
      return
    }
    pendingRef.current = { encounterId, itemId, content, recordedAt }
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => void flush(), AUTOSAVE_DEBOUNCE_MS)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [content, recordedAt, encounterId, itemId, disabled, flush])

  // 卸载 / 关标签页：来不及等防抖，立刻 flush
  useEffect(() => {
    const onHide = () => void flush()
    window.addEventListener('pagehide', onHide)
    return () => {
      window.removeEventListener('pagehide', onHide)
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
