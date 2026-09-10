/**
 * 窄屏可收起的工作台侧栏（components/workbench/CollapsibleSide.tsx）
 *
 * 2026-09-10 平板适配实测的产物：全前端此前没有任何响应式断点，工作台是
 * 固定宽度多栏（门诊 320+编辑器+320；住院 210+300+编辑器+右侧）。诊室
 * 1440+ 显示器没问题，但住院查房的典型设备是平板——实测 iPad 横屏 1024px
 * 下病历编辑器只剩 124px、竖屏 768px 下只剩 32px，"能看不能写"。
 *
 * 方案取最小可预期的交互：
 *   - 宽屏（>1180px）：完全透明包装，原样渲染，零行为变化；
 *   - 窄屏：侧栏默认收起为 40px 竖条（竖排标题），点击在**原位**展开回
 *     原宽度——编辑器随之被挤窄是医生主动查看面板的结果，看完再点收回。
 *     不用浮层/抽屉：覆盖式面板会挡住正在写的正文，且多一层遮罩交互。
 *
 * 断点 1180：住院页固定列合计约 510px（病区 210 + 问诊 300），加右侧面板
 * 约 320 与最小可写编辑器约 350，恰在 1180 附近；取整数断点便于记忆与测试。
 */
import { useState } from 'react'
import type { CSSProperties, PropsWithChildren, ReactNode } from 'react'
import { useCompactLayout } from './useCompactLayout'

interface Props extends PropsWithChildren {
  /** 收起时竖条上显示的名字（如「问诊」「AI 建议」），也是无障碍标签 */
  title: string
  /** 展开态的外层样式——把原来写在侧栏容器 div 上的样式原样传进来 */
  expandedStyle: CSSProperties
  /** 收起竖条上的小图标（可选） */
  icon?: ReactNode
  /** 窄屏下的初始展开态；默认收起（编辑器优先） */
  defaultOpenWhenCompact?: boolean
}

export function CollapsibleSide({
  title,
  expandedStyle,
  icon,
  defaultOpenWhenCompact = false,
  children,
}: Props) {
  const compact = useCompactLayout()
  const [open, setOpen] = useState(defaultOpenWhenCompact)

  // 宽屏：零包装成本，行为与引入本组件之前逐字节一致
  if (!compact) return <div style={expandedStyle}>{children}</div>

  if (!open) {
    return (
      <div
        role="button"
        aria-label={`展开${title}`}
        onClick={() => setOpen(true)}
        style={{
          width: 40,
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 8,
          padding: '12px 0',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 12,
          cursor: 'pointer',
          boxShadow: 'var(--shadow-sm)',
          userSelect: 'none',
        }}
      >
        {icon}
        <span
          style={{
            writingMode: 'vertical-rl',
            fontSize: 12,
            color: 'var(--text-3)',
            letterSpacing: 2,
          }}
        >
          {title}
        </span>
      </div>
    )
  }

  return (
    <div style={{ ...expandedStyle, position: 'relative' }}>
      <div
        role="button"
        aria-label={`收起${title}`}
        onClick={() => setOpen(false)}
        style={{
          position: 'absolute',
          top: 6,
          right: 6,
          zIndex: 5,
          width: 22,
          height: 22,
          lineHeight: '20px',
          textAlign: 'center',
          fontSize: 12,
          color: 'var(--text-3)',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 6,
          cursor: 'pointer',
          userSelect: 'none',
        }}
      >
        ‹
      </div>
      {children}
    </div>
  )
}
