/**
 * 工作台底部状态栏（components/workbench/WorkbenchStatusBar.tsx）
 *
 * 门诊/住院工作台底部显示：
 *   - 当前接诊状态（接诊中 / 待选择患者）
 *   - 最后保存时间（刚刚保存 / N 分钟前 / HH:MM）
 *
 * 只展示状态，不处理业务。
 */
import { useEffect, useState } from 'react'

import { StatusBar, StatusBarItem } from '@/components/shell/StatusBar'
import { useActiveEncounterStore, useCurrentPatient } from '@/store/activeEncounterStore'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordAutoSaveTrigger } from '@/store/recordAutoSaveTrigger'
import { useRecordStore } from '@/store/recordStore'

function formatSavedAt(ts: number | null | undefined): string {
  if (!ts) return '未保存'
  const diff = Date.now() - ts
  if (diff < 60_000) return '刚刚保存'
  const mins = Math.floor(diff / 60_000)
  if (mins < 60) return `${mins} 分钟前保存`
  const d = new Date(ts)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')} 保存`
}

export default function WorkbenchStatusBar() {
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const currentPatient = useCurrentPatient()
  const inquirySavedAt = useInquiryStore(s => s.inquirySavedAt)
  const recordContent = useRecordStore(s => s.recordContent)
  const recordSavedAt = useRecordStore(s => s.recordSavedAt)
  const autoSaveState = useRecordAutoSaveTrigger(s => s.autoSaveState)

  // 离线感知（2026-08-29 离线审计修复）：此前断网后状态条仍显示绿色
  // "N 分钟前保存"——那是断网前的旧时间戳，医生对"内容没在往服务器存"
  // 毫无感知。监听 online/offline 事件实时切换。
  const [online, setOnline] = useState(() =>
    typeof navigator === 'undefined' ? true : navigator.onLine
  )
  useEffect(() => {
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => {
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
    }
  }, [])

  const busy = !!currentEncounterId && !!currentPatient
  const hasDraft = !!recordContent

  // 状态优先级：离线/暂存/冲突（异常态优先，医生必须先看到）>
  // 病历草稿 auto-save 时间 > 问诊保存时间 > "草稿未保存" > "未开始"
  let savedLabel: string
  let dot: 'success' | 'warning' | 'info'
  if (!online) {
    savedLabel = '网络已断开，内容暂存本机，恢复后自动补传'
    dot = 'warning'
  } else if (autoSaveState === 'failed') {
    // 比 queued 更危险：连本机暂存队列都没写进去，内容仅存于浏览器 localStorage
    savedLabel = '保存失败！内容仅存于本机浏览器，请勿关闭页面并联系管理员'
    dot = 'warning'
  } else if (autoSaveState === 'queued') {
    savedLabel = '保存失败，已暂存本机稍后补传'
    dot = 'warning'
  } else if (autoSaveState === 'conflict') {
    savedLabel = '检测到其他设备修改，正在覆盖保存'
    dot = 'warning'
  } else if (recordSavedAt) {
    savedLabel = `病历 ${formatSavedAt(recordSavedAt)}`
    dot = 'success'
  } else if (inquirySavedAt) {
    savedLabel = formatSavedAt(inquirySavedAt)
    dot = 'success'
  } else if (hasDraft) {
    savedLabel = '草稿未保存'
    dot = 'warning'
  } else {
    savedLabel = '未开始'
    dot = 'info'
  }

  return (
    <StatusBar>
      <StatusBarItem
        dot={busy ? 'success' : 'info'}
        label={busy ? `${currentPatient?.name || '患者'} · 接诊中` : '待选择患者'}
      />
      <StatusBarItem dot={dot} label={savedLabel} />
    </StatusBar>
  )
}
