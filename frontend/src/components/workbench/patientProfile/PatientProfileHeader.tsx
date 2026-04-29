/**
 * 患者档案卡标题栏（components/workbench/patientProfile/PatientProfileHeader.tsx）
 *
 * 折叠态：左侧档案标题 + 跟随患者标签 + 未保存红标，右侧"已填：xxx"摘要 / "未录入"提示。
 * 展开态：右侧显示"最近更新于 yyyy-MM-dd"。
 *
 * 从 PatientProfileCard.tsx 拆出（Audit Round 4 M6）。
 */
import { Space, Tag } from 'antd'
import { DownOutlined, RightOutlined, UserOutlined } from '@ant-design/icons'

interface PatientProfileHeaderProps {
  collapsed: boolean
  onToggle: () => void
  isDirty: boolean
  filledLabels: string[]
  updatedAt: string | null
}

export default function PatientProfileHeader(props: PatientProfileHeaderProps) {
  const { collapsed, onToggle, isDirty, filledLabels, updatedAt } = props

  return (
    <div
      onClick={onToggle}
      style={{
        padding: '8px 12px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        cursor: 'pointer',
        userSelect: 'none',
      }}
    >
      <Space size={6}>
        {collapsed ? (
          <RightOutlined style={{ fontSize: 11, color: '#854d0e' }} />
        ) : (
          <DownOutlined style={{ fontSize: 11, color: '#854d0e' }} />
        )}
        <UserOutlined style={{ color: '#854d0e' }} />
        <span style={{ fontSize: 13, fontWeight: 700, color: '#713f12' }}>患者档案</span>
        <Tag
          color="orange"
          style={{ margin: 0, fontSize: 10, padding: '0 6px', height: 18, lineHeight: '16px' }}
        >
          跟随患者
        </Tag>
        {isDirty && (
          <Tag
            color="red"
            style={{ margin: 0, fontSize: 10, padding: '0 6px', height: 18, lineHeight: '16px' }}
          >
            未保存
          </Tag>
        )}
      </Space>
      <Space size={6}>
        {collapsed && filledLabels.length > 0 && (
          <span style={{ fontSize: 11, color: '#854d0e' }}>已填：{filledLabels.join('、')}</span>
        )}
        {collapsed && filledLabels.length === 0 && (
          <span style={{ fontSize: 11, color: '#a16207' }}>未录入档案</span>
        )}
        {updatedAt && !collapsed && (
          <span style={{ fontSize: 11, color: '#a16207' }}>
            最近更新于 {new Date(updatedAt).toLocaleDateString('zh-CN')}
          </span>
        )}
      </Space>
    </div>
  )
}
