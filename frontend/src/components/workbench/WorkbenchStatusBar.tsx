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
import { useWorkbenchStore } from '@/store/workbenchStore'


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
  const { currentEncounterId, currentPatient, inquirySavedAt, recordContent } = useWorkbenchStore()

  const busy = !!currentEncounterId && !!currentPatient
  const hasDraft = !!recordContent
  const savedLabel = inquirySavedAt ? formatSavedAt(inquirySavedAt) : hasDraft ? '草稿未保存' : '未开始'

  return (
    <StatusBar>
      <StatusBarItem
        dot={busy ? 'success' : 'info'}
        label={busy ? `${currentPatient?.name || '患者'} · 接诊中` : '待选择患者'}
      />
      <StatusBarItem
        dot={inquirySavedAt ? 'success' : hasDraft ? 'warning' : 'info'}
        label={savedLabel}
      />
    </StatusBar>
  )
}
