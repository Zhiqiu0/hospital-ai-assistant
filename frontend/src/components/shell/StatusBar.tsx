/**
 * 底部状态栏（components/shell/StatusBar.tsx）
 *
 * 工作台底部固定状态展示条，子项通过 <StatusBarItem> 组合。
 * 用法：
 *   <StatusBar>
 *     <StatusBarItem dot="success" label="已保存 14:32" />
 *     <StatusBarItem label="AI 质控：待运行" />
 *     <StatusBarItem label="Ctrl+S 保存" muted />
 *   </StatusBar>
 */
import { ReactNode } from 'react'
import { neutral, semantic } from '@/theme/tokens'

type DotKind = 'success' | 'warning' | 'error' | 'info'

const dotColor: Record<DotKind, string> = {
  success: semantic.success,
  warning: semantic.warning,
  error: semantic.error,
  info: semantic.info,
}

export function StatusBar({ children }: { children: ReactNode }) {
  return <div style={{ display: 'flex', alignItems: 'center', gap: 16, flex: 1 }}>{children}</div>
}

export interface StatusBarItemProps {
  /** 状态点颜色（可选） */
  dot?: DotKind
  /** 显示文字 */
  label: ReactNode
  /** 弱化样式（用于右侧快捷键提示等辅助信息） */
  muted?: boolean
  /** 靠右显示 */
  alignRight?: boolean
}

export function StatusBarItem({ dot, label, muted, alignRight }: StatusBarItemProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        color: muted ? neutral.text4 : neutral.text3,
        marginLeft: alignRight ? 'auto' : undefined,
      }}
    >
      {dot && (
        <span
          aria-hidden
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: dotColor[dot],
            flexShrink: 0,
          }}
        />
      )}
      <span>{label}</span>
    </div>
  )
}
