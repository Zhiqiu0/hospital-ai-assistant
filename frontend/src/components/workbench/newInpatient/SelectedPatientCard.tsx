/**
 * 已选中患者展示卡片（newInpatient/SelectedPatientCard.tsx）
 *
 * 与门诊 NewEncounterModal 风格一致，绿色突出"住院复用"。
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
      <Tag color="green">住院复用</Tag>
    </div>
  )
}
