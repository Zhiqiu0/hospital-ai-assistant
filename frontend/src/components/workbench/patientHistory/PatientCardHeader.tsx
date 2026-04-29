/**
 * 患者历史抽屉：患者身份卡（patientHistory/PatientCardHeader.tsx）
 *
 * 顶部绿色渐变背景，显示头像 + 姓名 + 三态住院 Tag + 性别/年龄/ID 后6位 +
 * 已签发病历总数。搜索模式下额外显示"换患者"按钮。
 */
import { Avatar, Button, Space, Tag, Typography } from 'antd'
import { IdcardOutlined } from '@ant-design/icons'

const { Text } = Typography

interface SelectedPatient {
  id: string
  name: string
  gender?: string
  age?: number | null
  hasActiveInpatient?: boolean
  hasAnyInpatientHistory?: boolean
}

interface Props {
  selected: SelectedPatient
  total: number
  searchable: boolean
  onChangePatient: () => void
}

export default function PatientCardHeader({ selected, total, searchable, onChangePatient }: Props) {
  return (
    <div
      style={{
        padding: '14px 20px',
        borderBottom: '1px solid var(--border-subtle)',
        background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}
    >
      <Avatar
        size={44}
        style={{
          background: 'linear-gradient(135deg, #065f46, #34d399)',
          fontSize: 18,
          flexShrink: 0,
        }}
      >
        {selected.name?.[0]}
      </Avatar>
      <div style={{ flex: 1, minWidth: 0, lineHeight: 1.4 }}>
        <Space size={6} align="center">
          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-1)' }}>
            {selected.name}
          </span>
          {/* 三态住院 Tag：
              active=true                  → 在院中（绿）
              active=false + history=true  → 已出院（灰）
              history=false                → 不打 Tag（纯门诊或新患者） */}
          {selected.hasActiveInpatient === true ? (
            <Tag
              color="green"
              style={{
                margin: 0,
                fontSize: 10,
                padding: '0 6px',
                height: 18,
                lineHeight: '16px',
              }}
            >
              在院中
            </Tag>
          ) : selected.hasAnyInpatientHistory === true ? (
            <Tag
              style={{
                margin: 0,
                fontSize: 10,
                padding: '0 6px',
                height: 18,
                lineHeight: '16px',
                background: '#f3f4f6',
                color: '#6b7280',
                border: '1px solid #e5e7eb',
              }}
            >
              已出院
            </Tag>
          ) : null}
        </Space>
        <Space size={6} style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>
          {selected.gender && selected.gender !== 'unknown' && (
            <span>{selected.gender === 'male' ? '男' : '女'}</span>
          )}
          {selected.age != null && <span>{selected.age} 岁</span>}
          <span style={{ fontFamily: 'monospace', color: 'var(--text-4)' }}>
            <IdcardOutlined style={{ marginRight: 2 }} />
            {selected.id.slice(-6).toUpperCase()}
          </span>
        </Space>
        <div style={{ fontSize: 11, color: 'var(--text-4)', marginTop: 4 }}>
          共{' '}
          <Text strong style={{ color: '#059669' }}>
            {total}
          </Text>{' '}
          份已签发病历
        </div>
      </div>
      {searchable && (
        <Button size="small" type="text" onClick={onChangePatient} style={{ color: '#059669' }}>
          换患者
        </Button>
      )}
    </div>
  )
}
