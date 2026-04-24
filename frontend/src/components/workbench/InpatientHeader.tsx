/**
 * 住院工作台顶栏（components/workbench/InpatientHeader.tsx）
 * 从 InpatientWorkbenchPage 提取，避免页面文件过长。
 */
import { Button, Space, Tag, Typography, Avatar, Divider } from 'antd'
import { Layout } from 'antd'
import { LogoutOutlined, CameraOutlined, MedicineBoxOutlined } from '@ant-design/icons'

const { Header } = Layout
const { Text } = Typography

interface Props {
  currentPatient: any
  currentEncounterId: string | null
  user: any
  onOpenHistory: () => void
  onOpenImaging: () => void
  onLogout: () => void
}

export default function InpatientHeader({
  currentPatient,
  currentEncounterId,
  user,
  onOpenHistory,
  onOpenImaging,
  onLogout,
}: Props) {
  return (
    <Header
      style={{
        height: 58,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: 'var(--surface)',
        borderBottom: '1px solid var(--border)',
        padding: '0 20px',
        boxShadow: '0 1px 8px rgba(0,0,0,0.06)',
        zIndex: 100,
        flexShrink: 0,
        position: 'relative',
      }}
    >
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: 'linear-gradient(90deg, #065f46, #059669, #34d399)', borderRadius: '0 0 2px 2px' }} />

      <Space size={10}>
        <div style={{ width: 32, height: 32, borderRadius: 9, background: 'linear-gradient(135deg, #065f46, #059669)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 2px 8px rgba(5,150,105,0.35)' }}>
          <MedicineBoxOutlined style={{ color: 'var(--surface)', fontSize: 16 }} />
        </div>
        <Text strong style={{ fontSize: 16, color: 'var(--text-1)', letterSpacing: '-0.4px' }}>MediScribe</Text>
        <Tag color="green" style={{ margin: 0, borderRadius: 20 }}>住院部</Tag>
      </Space>

      <div style={{ position: 'absolute', left: '50%', transform: 'translateX(-50%)', display: 'flex', alignItems: 'center', gap: 10 }}>
        {currentPatient ? (
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)', border: '1px solid #bbf7d0', borderRadius: 8, padding: '4px 12px', lineHeight: 1 }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#22c55e', boxShadow: '0 0 0 2px rgba(34,197,94,0.25)', flexShrink: 0 }} />
            <Text style={{ fontSize: 13, fontWeight: 700, color: '#065f46' }}>{currentPatient.name}</Text>
            {currentPatient.gender && currentPatient.gender !== 'unknown' && (
              <Text style={{ fontSize: 12, color: '#059669' }}>{currentPatient.gender === 'male' ? '男' : '女'}</Text>
            )}
            {currentPatient.age != null && currentPatient.age > 0 && (
              <Text style={{ fontSize: 12, color: '#059669' }}>{currentPatient.age}岁</Text>
            )}
            <Text style={{ fontSize: 11, color: 'var(--text-4)', fontFamily: 'monospace', marginLeft: 4 }}>
              住院 #{currentEncounterId?.slice(-6).toUpperCase()}
            </Text>
          </div>
        ) : (
          <Text style={{ fontSize: 13, color: 'var(--text-4)' }}>从左侧病区选择患者</Text>
        )}
      </div>

      <Space size={4}>
        <Button size="small" type="text" onClick={onOpenHistory} style={{ color: '#059669', fontSize: 12, borderRadius: 8 }}>患者档案</Button>
        <Button icon={<CameraOutlined />} size="small" type="text" onClick={onOpenImaging} style={{ color: '#7c3aed', fontSize: 12, borderRadius: 8 }}>影像分析</Button>
        <Divider type="vertical" style={{ margin: '0 4px', borderColor: 'var(--border)' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px', borderRadius: 8, background: 'var(--surface-2)' }}>
          <Avatar size={26} style={{ background: 'linear-gradient(135deg, #065f46, #34d399)', fontSize: 11, flexShrink: 0 }}>
            {user?.real_name?.[0]}
          </Avatar>
          <div style={{ lineHeight: 1.3 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-2)' }}>{user?.real_name}</div>
            {user?.department_name && <div style={{ fontSize: 11, color: 'var(--text-4)' }}>{user.department_name}</div>}
          </div>
        </div>
        <Button icon={<LogoutOutlined />} size="small" type="text" onClick={onLogout} style={{ color: 'var(--text-3)', borderRadius: 8 }} />
      </Space>
    </Header>
  )
}
