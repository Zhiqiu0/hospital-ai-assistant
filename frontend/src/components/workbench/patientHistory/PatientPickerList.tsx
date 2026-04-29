/**
 * 患者历史抽屉：搜索模式下的患者列表（patientHistory/PatientPickerList.tsx）
 *
 * 空 keyword 显示前 50 个（按建档时间倒序，最近建档的医生更可能想点）；
 * 有 keyword 走防抖过滤。
 *
 * 三态住院 Tag 与抽屉头部、复诊搜索保持一致。
 */
import { Avatar, Empty, Space, Spin, Tag } from 'antd'

interface PatientPickerListProps {
  patientList: any[]
  searching: boolean
  searchKeyword: string
  onPick: (p: any) => void
}

export default function PatientPickerList({
  patientList,
  searching,
  searchKeyword,
  onPick,
}: PatientPickerListProps) {
  if (searching && patientList.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 32 }}>
        <Spin size="small" />
      </div>
    )
  }
  if (patientList.length === 0) {
    return (
      <Empty
        description={searchKeyword ? '未找到匹配患者' : '暂无患者'}
        style={{ padding: '40px 0' }}
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    )
  }
  return (
    <>
      {patientList.map((p: any) => (
        <div
          key={p.id}
          onClick={() => onPick(p)}
          style={{
            padding: '10px 12px',
            marginBottom: 6,
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            transition: 'all 0.15s',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background = 'var(--surface-2)'
            e.currentTarget.style.borderColor = '#86efac'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = 'var(--surface)'
            e.currentTarget.style.borderColor = 'var(--border)'
          }}
        >
          <Avatar size={32} style={{ background: '#0891B2', flexShrink: 0 }}>
            {p.name?.[0]}
          </Avatar>
          <div style={{ flex: 1, minWidth: 0, lineHeight: 1.4 }}>
            <Space size={6} align="center">
              <span style={{ fontSize: 13, fontWeight: 600 }}>{p.name}</span>
              {p.has_active_inpatient ? (
                <Tag
                  color="green"
                  style={{
                    margin: 0,
                    fontSize: 10,
                    padding: '0 6px',
                    height: 16,
                    lineHeight: '14px',
                  }}
                >
                  在院中
                </Tag>
              ) : p.has_any_inpatient_history ? (
                <Tag
                  style={{
                    margin: 0,
                    fontSize: 10,
                    padding: '0 6px',
                    height: 16,
                    lineHeight: '14px',
                    background: '#f3f4f6',
                    color: '#6b7280',
                    border: '1px solid #e5e7eb',
                  }}
                >
                  已出院
                </Tag>
              ) : null}
            </Space>
            <div style={{ fontSize: 11, color: 'var(--text-4)' }}>
              {p.gender === 'male' ? '男' : p.gender === 'female' ? '女' : ''}
              {p.age != null ? ` · ${p.age}岁` : ''}
              {p.patient_no ? ` · ${p.patient_no}` : ''}
            </div>
          </div>
        </div>
      ))}
    </>
  )
}
