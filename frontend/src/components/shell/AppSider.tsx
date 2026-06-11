/**
 * 左侧迷你导航栏（components/shell/AppSider.tsx）
 *
 * 从 AppShell.tsx 拆出（2026-06-11 Round 5.5 拆分），逻辑一字未改：
 *   - Logo + 导航项（角色感知：门诊/急诊/住院/PACS/管理）
 *   - 底部用户头像 + 登出按钮（含登出请求 + 工作台重置 + 跳转登录页）
 */
import { ReactNode } from 'react'
import { Layout, Button, Tooltip, Avatar } from 'antd'
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
import { resetAllWorkbench } from '@/store/activeEncounterStore'
import api from '@/services/api'
import { scenes, neutral, radius, shadow, sizing, motion } from '@/theme/tokens'
import type { SceneKey } from '@/theme/tokens'

const { Sider } = Layout

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

interface AppSiderProps {
  /** 场景主题 key：控制 Logo 渐变与激活态配色 */
  scene: SceneKey
}

export default function AppSider({ scene }: AppSiderProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, clearAuth } = useAuthStore()
  const resetWorkbench = resetAllWorkbench
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
  )
}
