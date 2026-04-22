/**
 * 统一空状态组件（components/common/EmptyState.tsx）
 *
 * 替代零散的 <Empty> 使用，保证全站空状态风格一致。
 */
import { ReactNode } from 'react'
import { Empty } from 'antd'
import { neutral, spacing } from '@/theme/tokens'

export interface EmptyStateProps {
  /** 标题 */
  title?: ReactNode
  /** 描述 */
  description?: ReactNode
  /** 操作按钮区（推荐放 <Button>） */
  actions?: ReactNode
  /** 自定义图标（默认 antd 简单图标） */
  image?: ReactNode
  /** 垂直居中（用于占满父容器的场景） */
  fullHeight?: boolean
}

export default function EmptyState({
  title,
  description,
  actions,
  image,
  fullHeight = false,
}: EmptyStateProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: spacing.lg,
        padding: spacing['3xl'],
        minHeight: fullHeight ? '100%' : undefined,
      }}
    >
      <Empty
        image={image ?? Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          title || description ? (
            <div style={{ textAlign: 'center' }}>
              {title && (
                <div
                  style={{ fontSize: 14, fontWeight: 600, color: neutral.text2, marginBottom: 4 }}
                >
                  {title}
                </div>
              )}
              {description && (
                <div style={{ fontSize: 13, color: neutral.text3 }}>{description}</div>
              )}
            </div>
          ) : null
        }
      />
      {actions && <div style={{ display: 'flex', gap: spacing.sm }}>{actions}</div>}
    </div>
  )
}
