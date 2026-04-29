/**
 * 工作台底部状态栏（components/workbench/WorkbenchStatusBar.tsx）
 *
 * 门诊/住院工作台底部显示：
 *   - 当前接诊状态（接诊中 / 待选择患者）
 *   - 最后保存时间（刚刚保存 / N 分钟前 / HH:MM）
 *
 * 只展示状态，不处理业务。
 */
import { StatusBar, StatusBarItem } from '@/components/shell/StatusBar'
import { useActiveEncounterStore, useCurrentPatient } from '@/store/activeEncounterStore'
import { useInquiryStore } from '@/store/inquiryStore'
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

  const busy = !!currentEncounterId && !!currentPatient
  const hasDraft = !!recordContent

  // 状态优先级：病历草稿 auto-save 时间 > 问诊保存时间 > "草稿未保存" > "未开始"
  // 因为医生主要工作面是病历编辑器，auto-save 已保存比问诊保存更能反映"工作进度"
  let savedLabel: string
  let dot: 'success' | 'warning' | 'info'
  if (recordSavedAt) {
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
