/**
 * 门诊新建/复诊弹窗：已选中患者卡片（newEncounter/SelectedPatientCard.tsx）
 *
 * 与住院 newInpatient/SelectedPatientCard 视觉一致，绿色突出"复诊"。
 */
import { Avatar, Space, Tag } from 'antd'

interface Props {
  patient: any
}

export default function SelectedPatientCard({ patient }: Props) {
  return (
    <div
      style={{
        background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
        border: '1px solid #bbf7d0',
        borderRadius: 8,
        padding: '12px 14px',
        marginBottom: 16,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
      }}
    >
      <Avatar size={36} style={{ background: '#16a34a', flexShrink: 0 }}>
        {patient.name?.[0]}
      </Avatar>
      <div style={{ flex: 1 }}>
        <Space size={6}>
          <span style={{ fontWeight: 700, fontSize: 15, color: '#065f46' }}>{patient.name}</span>
          {patient.gender !== 'unknown' && (
            <span style={{ fontSize: 12, color: '#059669' }}>
              {patient.gender === 'male' ? '男' : '女'}
            </span>
          )}
          {patient.age && <span style={{ fontSize: 12, color: '#059669' }}>{patient.age}岁</span>}
        </Space>
        {patient.phone && (
          <div style={{ fontSize: 12, color: '#059669', marginTop: 2 }}>{patient.phone}</div>
        )}
      </div>
      <Tag color="green">复诊</Tag>
    </div>
  )
}
