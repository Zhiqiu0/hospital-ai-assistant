/**
 * 顶栏（components/shell/AppHeader.tsx）
 *
 * 从 AppShell.tsx 拆出（2026-06-11 Round 5.5 拆分），逻辑一字未改：
 *   - 顶部场景色带
 *   - 左：品牌 + 场景标签
 *   - 中：自定义插槽（患者卡 / 接诊按钮等）
 *   - 右：操作区插槽
 */
import { ReactNode } from 'react'
import { Layout, Tag, Space, Typography } from 'antd'
import { scenes, neutral, radius, shadow, sizing } from '@/theme/tokens'
import type { SceneKey } from '@/theme/tokens'

const { Header } = Layout
const { Text } = Typography

interface AppHeaderProps {
  /** 场景主题 key：控制色带渐变与场景标签颜色 */
  scene: SceneKey
  /** 场景标签文字，如 "门诊部" "急诊部" "住院部" "影像科" "管理后台" */
  sceneLabel: string
  /** 顶栏中央插槽：工作台放患者卡 + 接诊按钮；管理后台留空 */
  centerSlot?: ReactNode
  /** 顶栏右侧功能按钮：历史病历 / 影像 / 用户菜单等 */
  actionSlot?: ReactNode
}

export default function AppHeader({ scene, sceneLabel, centerSlot, actionSlot }: AppHeaderProps) {
  const theme = scenes[scene]

  return (
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
  )
}
