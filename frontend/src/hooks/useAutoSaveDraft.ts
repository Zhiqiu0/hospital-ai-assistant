/**
 * 病历编辑器 auto-save hook（hooks/useAutoSaveDraft.ts）
 *
 * 治本目标：
 *   医生在编辑器里输入到一半，浏览器崩溃 / 不小心关标签 / 网络中断 / logout 时
 *   不丢数据。每 5 秒把当前 recordContent 防抖保存到后端，后端 UPSERT 当前
 *   draft 版本（不爆版本号）。
 *
 * 行为约定：
 *   - 5 秒防抖：医生连续输入时只发最后一次的内容，不刷请求
 *   - 跳空：recordContent 空 / 跟上次保存内容一样 → 不发请求
 *   - 跳已签发：isFinal=true 时不再 auto-save（医生已签发的病历不允许覆盖）
 *   - 失败兜底：网络失败 → IndexedDB 队列存草稿，下次成功时一并补发
 *   - 乐观锁：保存成功后记录 updated_at，下次发请求带回；后端检测到不一致返 409
 *   - encounter 切换：切到新接诊时上次草稿失效，从新草稿基线开始
 *
 * 状态对外：
 *   - savedAt：最后一次成功保存时间戳，状态条显示"X 秒前已保存"
 *   - savingState：'idle' / 'saving' / 'saved' / 'queued' / 'conflict'
 *
 * 不做的事：
 *   - 不做编辑历史快照（每次只保留当前内容，历史靠版本号机制）
 *   - 不做实时协作 OT/CRDT（医生场景不需要多人同时编辑同一份病历）
 */
import { useEffect, useRef, useState } from 'react'
import { message } from 'antd'
import api from '@/services/api'
import { useRecordStore } from '@/store/recordStore'
import { enqueueDraft, flushDraftQueue, type DraftPayload } from '@/services/draftQueue'

const DEBOUNCE_MS = 5000

export type AutoSaveState = 'idle' | 'saving' | 'saved' | 'queued' | 'conflict'

export interface UseAutoSaveDraftOptions {
  /** 当前接诊 ID，无则不启用 auto-save（首次进入工作台还没接诊上下文） */
  encounterId: string | null
  /** 病历类型（outpatient / admission_note 等），切换时 auto-save 基线重置 */
  recordType: string
  /** 当前编辑器内容（主控信号，本 hook 据此防抖触发） */
  recordContent: string
  /** 病历是否已签发——签发后只读，不再 auto-save */
  isFinal: boolean
}

export function useAutoSaveDraft({
  encounterId,
  recordType,
  recordContent,
  isFinal,
}: UseAutoSaveDraftOptions): {
  savedAt: number
  savingState: AutoSaveState
} {
  const [savedAt, setSavedAt] = useState(0)
  const [savingState, setSavingState] = useState<AutoSaveState>('idle')
  // 上次成功保存的内容快照——用于"内容没变就不重发"判断
  const lastSavedContentRef = useRef<string>('')
  // 上次保存返回的 updated_at——给乐观锁带回
  const lastUpdatedAtRef = useRef<string | null>(null)
  // 防抖计时器
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 切接诊时重置基线
  const lastEncounterRef = useRef<string | null>(null)

  // 接诊切换：上一份草稿不再相关，重置所有内部状态
  useEffect(() => {
    if (encounterId !== lastEncounterRef.current) {
      lastEncounterRef.current = encounterId
      lastSavedContentRef.current = ''
      lastUpdatedAtRef.current = null
      setSavedAt(0)
      setSavingState('idle')
      // 顺便尝试把上次会话堆积的失败队列发出去（网络刚恢复 / 重新登录场景）
      void flushDraftQueue(performSave)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [encounterId])

  // 实际保存逻辑（被防抖 + 失败队列 flush 共用）
  const performSave = async (payload: DraftPayload): Promise<boolean> => {
    setSavingState('saving')
    try {
      const res: any = await api.post('/medical-records/auto-save-draft', {
        encounter_id: payload.encounter_id,
        record_type: payload.record_type,
        content: payload.content,
        expected_updated_at: payload.expected_updated_at,
      })
      lastSavedContentRef.current = payload.content
      lastUpdatedAtRef.current = res?.updated_at ?? null
      const now = Date.now()
      setSavedAt(now)
      setSavingState('saved')
      // 同步到 recordStore，让 WorkbenchStatusBar / 其他组件能感知"已保存"状态
      useRecordStore.getState().setRecordSavedAt(now)
      return true
    } catch (err: any) {
      // 409：乐观锁冲突——其他设备/标签页已经写过更新版
      if (err?.response?.status === 409) {
        setSavingState('conflict')
        message.warning('病历已被其他设备修改，请刷新后重试')
        return false
      }
      // 其他错误（网络 / 5xx）→ 入失败队列，下次成功时补发
      try {
        await enqueueDraft(payload)
        setSavingState('queued')
      } catch {
        // IndexedDB 也挂了——只能记日志，下次防抖触发还是会试
        // eslint-disable-next-line no-console
        console.warn('autosave: enqueue failed', err)
      }
      return false
    }
  }

  // 主防抖循环
  useEffect(() => {
    if (!encounterId) return
    if (isFinal) return
    if (!recordContent) return
    if (recordContent === lastSavedContentRef.current) return

    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    debounceTimerRef.current = setTimeout(() => {
      void performSave({
        encounter_id: encounterId,
        record_type: recordType,
        content: recordContent,
        expected_updated_at: lastUpdatedAtRef.current,
      })
    }, DEBOUNCE_MS)

    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordContent, encounterId, recordType, isFinal])

  return { savedAt, savingState }
}
