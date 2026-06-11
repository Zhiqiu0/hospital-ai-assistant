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
 *
 * 2026-06-11 Round 5.5 拆分（纯搬家不改逻辑，对外 props 不变）：
 *   - 左侧导航 + 用户/登出 → AppSider.tsx
 *   - 顶栏（色带/品牌/插槽）→ AppHeader.tsx
 *   - 本文件保留：Layout 组装 + Content + 底部状态栏
 */
import { ReactNode } from 'react'
import { Layout } from 'antd'
import { neutral, sizing } from '@/theme/tokens'
import type { SceneKey } from '@/theme/tokens'
import AppSider from './AppSider'
import AppHeader from './AppHeader'

const { Content, Footer } = Layout

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
  return (
    <Layout style={{ height: '100vh', background: neutral.bg }}>
      {/* 左侧迷你导航 */}
      {showNav && <AppSider scene={scene} />}

      {/* 主区域 */}
      <Layout>
        {/* 顶栏 */}
        <AppHeader
          scene={scene}
          sceneLabel={sceneLabel}
          centerSlot={centerSlot}
          actionSlot={actionSlot}
        />

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
