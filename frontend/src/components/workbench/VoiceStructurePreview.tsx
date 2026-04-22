/**
 * 语音结构化结果预览区（VoiceStructurePreview.tsx）
 * 追记模式下 AI 整理完成后展示 patch 内容，医生确认后点「插入病历」写入。
 */
import { Button, Typography } from 'antd'
import { MedicineBoxOutlined } from '@ant-design/icons'
import { InquiryData } from '@/store/workbenchStore'
import { FIELD_NAME_LABEL, FIELD_TO_SECTION } from './qcFieldMaps'

const { Text } = Typography

interface Props {
  pendingPatch: Partial<InquiryData>
  onApply: () => void
  onCancel: () => void
}

export default function VoiceStructurePreview({ pendingPatch, onApply, onCancel }: Props) {
  const entries = Object.entries(pendingPatch).filter(
    ([k, v]) => v && FIELD_TO_SECTION[k] !== undefined && FIELD_TO_SECTION[k] !== ''
  )
  if (!entries.length) return null

  return (
    <div
      style={{
        marginTop: 10,
        background: '#f0fdf4',
        border: '1px solid #86efac',
        borderRadius: 8,
        padding: '10px 12px',
      }}
    >
      <Text strong style={{ fontSize: 12, color: '#166534', display: 'block', marginBottom: 6 }}>
        AI 整理结果（确认后插入病历）：
      </Text>
      {entries.map(([k, v]) => (
        <div key={k} style={{ fontSize: 12, marginBottom: 4, lineHeight: 1.5 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {FIELD_NAME_LABEL[k] || k}（{FIELD_TO_SECTION[k]}）：
          </Text>
          <Text style={{ fontSize: 12 }}>{String(v)}</Text>
        </div>
      ))}
      <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
        <Button
          type="primary"
          size="small"
          icon={<MedicineBoxOutlined />}
          onClick={onApply}
          style={{ borderRadius: 6, background: '#16a34a', borderColor: '#16a34a' }}
        >
          插入病历
        </Button>
        <Button size="small" onClick={onCancel} style={{ borderRadius: 6 }}>
          取消
        </Button>
      </div>
    </div>
  )
}
