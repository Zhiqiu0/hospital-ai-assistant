import { Layout, Menu, Button, Space, Avatar } from 'antd'
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom'
import {
  UserOutlined, ApartmentOutlined, SafetyOutlined,
  RobotOutlined, BarChartOutlined, HomeOutlined, LogoutOutlined,
  MedicineBoxOutlined, FileTextOutlined, ThunderboltOutlined, TeamOutlined, AuditOutlined, AudioOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '@/store/authStore'
import { useWorkbenchStore } from '@/store/workbenchStore'
import OverviewPage from './OverviewPage'
import UsersPage from './UsersPage'
import DepartmentsPage from './DepartmentsPage'
import QCRulesPage from './QCRulesPage'
import PromptsPage from './PromptsPage'
import StatsPage from './StatsPage'
import RecordsPage from './RecordsPage'
import TokenUsagePage from './TokenUsagePage'
import PatientsPage from './PatientsPage'
import AuditLogsPage from './AuditLogsPage'
import ModelConfigsPage from './ModelConfigsPage'
import VoiceRecordsPage from './VoiceRecordsPage'

const { Sider, Content } = Layout
const ROLE_MAP: Record<string, string> = {
  super_admin: '超级管理员',
  hospital_admin: '医院管理员',
  dept_admin: '科室管理员',
  doctor: '医生',
  nurse: '护士',
}

export default function AdminLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, clearAuth } = useAuthStore()
  const resetWorkbench = useWorkbenchStore((s) => s.reset)

  const handleLogout = () => {
    resetWorkbench()
    clearAuth()
    navigate('/login')
  }

  const menuItems = [
    { key: '/admin', icon: <HomeOutlined />, label: '系统概览' },
    { key: '/admin/users', icon: <UserOutlined />, label: '用户管理' },
    { key: '/admin/departments', icon: <ApartmentOutlined />, label: '科室管理' },
    { key: '/admin/qc-rules', icon: <SafetyOutlined />, label: '质控规则' },
    { key: '/admin/prompts', icon: <RobotOutlined />, label: 'Prompt 管理' },
    { key: '/admin/model-configs', icon: <RobotOutlined />, label: '模型配置' },
    { key: '/admin/stats', icon: <BarChartOutlined />, label: '数据统计' },
    { key: '/admin/records', icon: <FileTextOutlined />, label: '病历管理' },
    { key: '/admin/patients', icon: <TeamOutlined />, label: '患者档案' },
    { key: '/admin/audit-logs', icon: <AuditOutlined />, label: '操作日志' },
    { key: '/admin/token-usage', icon: <ThunderboltOutlined />, label: 'Token 用量' },
    { key: '/admin/voice-records', icon: <AudioOutlined />, label: '语音记录' },
  ]

  const selectedKey = menuItems.slice().reverse().find(
    (item) => location.pathname === item.key || location.pathname.startsWith(item.key + '/')
  )?.key ?? '/admin'

  return (
    <Layout style={{ height: '100vh', background: 'var(--bg)' }}>
      <Sider
        theme="light"
        width={224}
        style={{
          borderRight: '1px solid var(--border)',
          boxShadow: '2px 0 12px rgba(0,0,0,0.05)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          background: '#fff',
          position: 'relative',
        }}
      >
        {/* Top accent stripe */}
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 3,
          background: 'linear-gradient(90deg, #1d4ed8, #3b82f6, #60a5fa)',
        }} />

        {/* Logo */}
        <div style={{
          padding: '20px 20px 16px',
          borderBottom: '1px solid var(--border-subtle)',
          marginTop: 3,
        }}>
          <Space size={10}>
            <div style={{
              width: 34, height: 34, borderRadius: 10,
              background: 'linear-gradient(135deg, #1d4ed8, #3b82f6)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
              boxShadow: '0 2px 8px rgba(37,99,235,0.3)',
            }}>
              <MedicineBoxOutlined style={{ color: '#fff', fontSize: 17 }} />
            </div>
            <div>
              <div style={{ fontWeight: 800, fontSize: 15, color: 'var(--text-1)', lineHeight: 1.2, letterSpacing: '-0.3px' }}>
                MediScribe
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-4)', marginTop: 2 }}>管理控制台</div>
            </div>
          </Space>
        </div>

        {/* Menu */}
        <div style={{ flex: 1, padding: '10px 8px', overflow: 'auto' }}>
          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
            style={{ border: 'none', fontSize: 13 }}
          />
        </div>

        {/* User info at bottom */}
        <div style={{
          padding: '12px 14px',
          borderTop: '1px solid var(--border-subtle)',
          background: 'var(--surface-2)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <Avatar
              size={34}
              style={{
                background: 'linear-gradient(135deg, #1d4ed8, #60a5fa)',
                fontSize: 13, flexShrink: 0,
                boxShadow: '0 1px 4px rgba(37,99,235,0.2)',
              }}
            >
              {user?.real_name?.[0]}
            </Avatar>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontSize: 13, fontWeight: 600, color: 'var(--text-1)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {user?.real_name}
              </div>
              <div style={{
                fontSize: 11, color: 'var(--text-4)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {ROLE_MAP[user?.role || ''] || user?.role}
              </div>
            </div>
          </div>
          <Button
            icon={<LogoutOutlined />}
            size="small"
            type="text"
            block
            onClick={handleLogout}
            style={{
              color: 'var(--text-3)', textAlign: 'left', fontSize: 12,
              borderRadius: 8, height: 30,
            }}
          >
            退出登录
          </Button>
        </div>
      </Sider>

      <Layout style={{ background: 'var(--bg)' }}>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/users" element={<UsersPage />} />
            <Route path="/departments" element={<DepartmentsPage />} />
            <Route path="/qc-rules" element={<QCRulesPage />} />
            <Route path="/prompts" element={<PromptsPage />} />
            <Route path="/model-configs" element={<ModelConfigsPage />} />
            <Route path="/stats" element={<StatsPage />} />
            <Route path="/records" element={<RecordsPage />} />
            <Route path="/patients" element={<PatientsPage />} />
            <Route path="/audit-logs" element={<AuditLogsPage />} />
            <Route path="/token-usage" element={<TokenUsagePage />} />
            <Route path="/voice-records" element={<VoiceRecordsPage />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}
