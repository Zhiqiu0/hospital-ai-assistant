/**
 * 通用可折叠区块（components/common/CollapsibleSection.tsx）
 *
 * 用于问诊面板等长表单的章节折叠，比 antd Collapse 更轻量：
 *   - 支持受控（open + onOpenChange）或非受控（defaultOpen）
 *   - 折叠状态由调用方自行持久化（通常放 store）
 *   - 标题区可插入图标、右侧摘要（已填字段数 / 状态标签）
 */
import { ReactNode, useState, CSSProperties } from 'react'
import { DownOutlined, RightOutlined } from '@ant-design/icons'

interface Props {
  /** 标题文字 */
  title: ReactNode
  /** 标题左侧图标（可选） */
  icon?: ReactNode
  /** 标题右侧摘要（已填写3项 / 未填）— 折叠时更有意义 */
  summary?: ReactNode
  /** 受控展开状态 */
  open?: boolean
  /** 默认展开状态（非受控） */
  defaultOpen?: boolean
  /** 受控变更回调 */
  onOpenChange?: (open: boolean) => void
  /** 标题自定义样式 */
  headerStyle?: CSSProperties
  /** 主题色（图标颜色） */
  accent?: string
  children: ReactNode
}

export default function CollapsibleSection({
  title,
  icon,
  summary,
  open,
  defaultOpen = true,
  onOpenChange,
  headerStyle,
  accent = '#0284c7',
  children,
}: Props) {
  const [internal, setInternal] = useState(defaultOpen)
  const isOpen = open !== undefined ? open : internal

  const toggle = () => {
    const next = !isOpen
    if (open === undefined) setInternal(next)
    onOpenChange?.(next)
  }

  return (
    <div style={{ marginBottom: 8 }}>
      <div
        onClick={toggle}
        role="button"
        tabIndex={0}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle() } }}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 0 4px',
          fontSize: 11,
          fontWeight: 700,
          color: 'var(--text-3)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          cursor: 'pointer',
          userSelect: 'none',
          ...headerStyle,
        }}
      >
        {isOpen
          ? <DownOutlined style={{ fontSize: 10, color: 'var(--text-4)' }} />
          : <RightOutlined style={{ fontSize: 10, color: 'var(--text-4)' }} />
        }
        {icon && <span style={{ color: accent }}>{icon}</span>}
        <span>{title}</span>
        {summary && (
          <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-4)', fontWeight: 400, textTransform: 'none' }}>
            {summary}
          </span>
        )}
      </div>
      {isOpen && <div>{children}</div>}
    </div>
  )
}
