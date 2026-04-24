/**
 * 急诊流转提示栏（EmergencyDispositionBar.tsx）
 * 患者去向为「收入住院」或「留院观察」时显示对应操作按钮。
 */
import { Button } from 'antd'

interface Props {
  savedDisposition: string | null
  onAdmitToInpatient: () => void
  onAddObservationNote: () => void
}

export default function EmergencyDispositionBar({
  savedDisposition,
  onAdmitToInpatient,
  onAddObservationNote,
}: Props) {
  if (savedDisposition === '收入住院') {
    return (
      <div
        style={{
          padding: '10px 16px',
          borderTop: '1px solid #fee2e2',
          background: '#fff7f7',
          flexShrink: 0,
        }}
      >
        <div style={{ fontSize: 12, color: '#dc2626', marginBottom: 6, fontWeight: 600 }}>
          患者去向：收入住院
        </div>
        <Button
          block
          size="small"
          style={{
            borderRadius: 8,
            background: '#dc2626',
            borderColor: '#dc2626',
            color: 'var(--surface)',
            fontWeight: 600,
          }}
          onClick={onAdmitToInpatient}
        >
          一键转入住院接诊 →
        </Button>
      </div>
    )
  }

  if (savedDisposition === '留院观察') {
    return (
      <div
        style={{
          padding: '8px 16px',
          borderTop: '1px solid #fef3c7',
          background: '#fffbeb',
          flexShrink: 0,
        }}
      >
        <Button
          block
          size="small"
          style={{ borderRadius: 8, borderColor: '#d97706', color: '#d97706', fontWeight: 600 }}
          onClick={onAddObservationNote}
        >
          + 追记留观记录
        </Button>
      </div>
    )
  }

  return null
}
