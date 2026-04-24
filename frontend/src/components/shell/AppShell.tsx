/**
 * 统一应用外壳（components/shell/AppShell.tsx）
 *
 * 所有工作台和管理后台页面的外层 Shell，提供一致的：
 *   - 顶栏（Logo + 系统标签 + 中央插槽 + 右侧操作）
 *   - 左侧迷你导航（角色感知：门诊/急诊/住院/PACS/管理）
 *   - 内容区域（children）
 *   - 底部状态栏（可选，StatusBar 组件）
 *
 * 使用：
 *   <AppShell scene="outpatient" centerSlot={<PatientBar />} actionSlot={<HistoryBtn />}>
 *     <ThreeColumnLayout />
 *   </AppShell>
 */
import { ReactNode } from 'react'
import { Layout, Button, Tag, Tooltip, Avatar, Space, Typography } from 'antd'
import {
  MedicineBoxOutlined,
  LogoutOutlined,
  UserOutlined,
  AppstoreOutlined,
  AlertOutlined,
  HomeOutlined,
  ScanOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { useWorkbenchStore } from '@/store/workbenchStore'
import api from '@/services/api'
import { scenes, neutral, radius, shadow, sizing, motion } from '@/theme/tokens'
import type { SceneKey } from '@/theme/tokens'

const { Header, Sider, Content, Footer } = Layout
const { Text } = Typography

interface NavItem {
  key: string
  path: string
  icon: ReactNode
  label: string
  visibleForRoles?: string[]
}

const NAV_ITEMS: NavItem[] = [
  { key: 'outpatient', path: '/workbench', icon: <AppstoreOutlined />, label: '门诊' },
  { key: 'emergency', path: '/emergency', icon: <AlertOutlined />, label: '急诊' },
  { key: 'inpatient', path: '/inpatient', icon: <HomeOutlined />, label: '住院' },
  { key: 'pacs', path: '/pacs', icon: <ScanOutlined />, label: '影像' },
  {
    key: 'admin',
    path: '/admin',
    icon: <SettingOutlined />,
    label: '管理',
    visibleForRoles: ['super_admin', 'hospital_admin', 'dept_admin'],
  },
]

export interface AppShellProps {
  /** 场景主题：控制 Logo 渐变、右侧色带 */
  scene: SceneKey
  /** 场景标签文字，如 "门诊部" "急诊部" "住院部" "影像科" "管理后台" */
  sceneLabel: string
  /** 顶栏中央插槽：工作台放患者卡 + 接诊按钮；管理后台留空 */
  centerSlot?: ReactNode
  /** 顶栏右侧功能按钮：历史病历 / 影像 / 用户菜单等 */
  actionSlot?: ReactNode
  /** 底部状态栏（可选） */
  statusBar?: ReactNode
  /** 是否显示左侧导航，默认 true；登录页等独立页面传 false */
  showNav?: boolean
  children: ReactNode
}

export default function AppShell({
  scene,
  sceneLabel,
  centerSlot,
  actionSlot,
  statusBar,
  showNav = true,
  children,
}: AppShellProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, clearAuth } = useAuthStore()
  const resetWorkbench = useWorkbenchStore(s => s.reset)
  const theme = scenes[scene]

  const handleLogout = async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      /* ignore */
    }
    resetWorkbench()
    clearAuth()
    navigate('/login')
  }

  const visibleNav = NAV_ITEMS.filter(item => {
    if (!item.visibleForRoles) return true
    return user?.role && item.visibleForRoles.includes(user.role)
  })

  const activeNavKey = visibleNav.find(item => location.pathname.startsWith(item.path))?.key

  return (
    <Layout style={{ height: '100vh', background: neutral.bg }}>
      {/* 左侧迷你导航 */}
      {showNav && (
        <Sider
          width={sizing.sidebarWidth}
          style={{
            background: neutral.surface,
            borderRight: `1px solid ${neutral.border}`,
            boxShadow: shadow.xs,
            zIndex: 20,
          }}
        >
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              padding: '12px 0',
              gap: 4,
            }}
          >
            {/* Logo */}
            <Tooltip title="MediScribe" placement="right">
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: radius.lg,
                  background: `linear-gradient(135deg, ${theme.primary}, ${theme.accentLight})`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  boxShadow: `0 2px 8px rgba(${theme.shadowRgba},0.35)`,
                  marginBottom: 8,
                }}
              >
                <MedicineBoxOutlined style={{ color: 'var(--surface)', fontSize: 20 }} />
              </div>
            </Tooltip>

            {/* 导航项 */}
            {visibleNav.map(item => {
              const isActive = item.key === activeNavKey
              return (
                <Tooltip key={item.key} title={item.label} placement="right">
                  <button
                    onClick={() => navigate(item.path)}
                    aria-label={item.label}
                    aria-current={isActive ? 'page' : undefined}
                    style={{
                      width: 44,
                      height: 44,
                      border: 'none',
                      borderRadius: radius.md,
                      background: isActive ? theme.primaryLight : 'transparent',
                      color: isActive ? theme.primary : neutral.text3,
                      cursor: 'pointer',
                      fontSize: 18,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: `all ${motion.base} ${motion.ease}`,
                      position: 'relative',
                    }}
                    onMouseEnter={e => {
                      if (!isActive) e.currentTarget.style.background = neutral.surface2
                    }}
                    onMouseLeave={e => {
                      if (!isActive) e.currentTarget.style.background = 'transparent'
                    }}
                  >
                    {item.icon}
                    {isActive && (
                      <span
                        style={{
                          position: 'absolute',
                          left: 0,
                          top: 8,
                          bottom: 8,
                          width: 3,
                          background: theme.primary,
                          borderRadius: '0 2px 2px 0',
                        }}
                      />
                    )}
                  </button>
                </Tooltip>
              )
            })}
          </div>

          {/* 底部用户 + 登出 */}
          <div
            style={{
              position: 'absolute',
              bottom: 12,
              left: 0,
              right: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <Tooltip
              title={
                user?.real_name
                  ? `${user.real_name}${user.department_name ? ' · ' + user.department_name : ''}`
                  : '用户'
              }
              placement="right"
            >
              <Avatar
                size={34}
                style={{ background: neutral.surface3, color: neutral.text2 }}
                icon={<UserOutlined />}
              >
                {user?.real_name?.[0]}
              </Avatar>
            </Tooltip>
            <Tooltip title="登出" placement="right">
              <Button
                type="text"
                size="small"
                icon={<LogoutOutlined />}
                onClick={handleLogout}
                aria-label="登出"
                style={{ color: neutral.text3 }}
              />
            </Tooltip>
          </div>
        </Sider>
      )}

      {/* 主区域 */}
      <Layout>
        {/* 顶栏 */}
        <Header
          style={{
            height: sizing.headerHeight,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: neutral.surface,
            borderBottom: `1px solid ${neutral.border}`,
            padding: '0 20px',
            boxShadow: shadow.xs,
            zIndex: 10,
            flexShrink: 0,
            position: 'relative',
          }}
        >
          {/* 顶部色带 */}
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              height: 3,
              background: `linear-gradient(90deg, ${theme.primary}, ${theme.accentLight}, ${theme.accentLighter})`,
            }}
          />

          {/* 左：品牌 + 场景标签 */}
          <Space size={10}>
            <Text strong style={{ fontSize: 16, color: neutral.text1, letterSpacing: '-0.4px' }}>
              MediScribe
            </Text>
            <Tag
              color={scene === 'emergency' ? 'red' : scene === 'inpatient' ? 'green' : 'cyan'}
              style={{ margin: 0, borderRadius: radius.pill }}
            >
              {sceneLabel}
            </Tag>
          </Space>

          {/* 中：自定义插槽（患者卡 / 接诊按钮等） */}
          {centerSlot && (
            <div
              style={{
                position: 'absolute',
                left: '50%',
                transform: 'translateX(-50%)',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
              }}
            >
              {centerSlot}
            </div>
          )}

          {/* 右：操作区 */}
          {actionSlot && (
            <Space size={4} style={{ flexShrink: 0 }}>
              {actionSlot}
            </Space>
          )}
        </Header>

        {/* 内容 */}
        <Content style={{ flex: 1, overflow: 'hidden', minHeight: 0 }}>{children}</Content>

        {/* 底部状态栏（可选） */}
        {statusBar && (
          <Footer
            style={{
              height: sizing.statusBarHeight,
              minHeight: sizing.statusBarHeight,
              padding: '0 16px',
              background: neutral.surface2,
              borderTop: `1px solid ${neutral.borderSubtle}`,
              fontSize: 12,
              color: neutral.text3,
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              flexShrink: 0,
              lineHeight: 1,
            }}
          >
            {statusBar}
          </Footer>
        )}
      </Layout>
    </Layout>
  )
}
