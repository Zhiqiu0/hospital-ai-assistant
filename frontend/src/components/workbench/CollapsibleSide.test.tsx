/**
 * 窄屏侧栏折叠回归（2026-09-10 平板适配）
 *
 * 背景数据：全前端此前零响应式断点，住院工作台在 iPad 横屏 1024px 下病历
 * 编辑器只剩 124px、竖屏 768px 下只剩 32px——"能看不能写"。本组件是修复的
 * 核心：宽屏零行为变化，窄屏侧栏收成竖条把宽度让给编辑器。
 *
 * 最要紧的断言是宽屏那条：诊室 1440+ 显示器是主力场景，包装层在宽屏下
 * 必须完全透明，不能因为平板适配把诊室体验改坏。
 */
import { render, screen, cleanup, fireEvent, act } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

// matchMedia 可控桩：按用例切换宽/窄屏
let isCompact = false
const listeners: Array<(e: { matches: boolean }) => void> = []
vi.stubGlobal('matchMedia', (query: string) => ({
  matches: isCompact,
  media: query,
  addEventListener: (_: string, cb: (e: { matches: boolean }) => void) => listeners.push(cb),
  removeEventListener: (_: string, cb: (e: { matches: boolean }) => void) => {
    const i = listeners.indexOf(cb)
    if (i >= 0) listeners.splice(i, 1)
  },
}))

import { CollapsibleSide } from './CollapsibleSide'

afterEach(() => {
  cleanup()
  listeners.length = 0
})

describe('CollapsibleSide', () => {
  it('宽屏下是完全透明的包装，内容原样渲染且没有折叠交互', () => {
    isCompact = false
    render(
      <CollapsibleSide title="问诊录入" expandedStyle={{ width: 320 }}>
        <div>问诊表单内容</div>
      </CollapsibleSide>
    )
    expect(screen.getByText('问诊表单内容')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /展开|收起/ })).toBeNull()
  })

  it('窄屏下默认收起为竖条，内容不渲染、宽度让给编辑器', () => {
    isCompact = true
    render(
      <CollapsibleSide title="问诊录入" expandedStyle={{ width: 320 }}>
        <div>问诊表单内容</div>
      </CollapsibleSide>
    )
    expect(screen.queryByText('问诊表单内容')).toBeNull()
    expect(screen.getByRole('button', { name: '展开问诊录入' })).toBeTruthy()
  })

  it('窄屏点竖条展开、点收起按钮收回', () => {
    isCompact = true
    render(
      <CollapsibleSide title="AI 建议" expandedStyle={{ width: 320 }}>
        <div>建议列表</div>
      </CollapsibleSide>
    )
    fireEvent.click(screen.getByRole('button', { name: '展开AI 建议' }))
    expect(screen.getByText('建议列表')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '收起AI 建议' }))
    expect(screen.queryByText('建议列表')).toBeNull()
  })

  it('视口从宽变窄时自动进入收起态（medQuery change 事件）', () => {
    isCompact = false
    render(
      <CollapsibleSide title="问诊录入" expandedStyle={{ width: 320 }}>
        <div>问诊表单内容</div>
      </CollapsibleSide>
    )
    expect(screen.getByText('问诊表单内容')).toBeTruthy()
    // 模拟旋转平板 / 拖窄窗口（React 状态更新须在 act 内 flush）
    act(() => listeners.forEach(cb => cb({ matches: true })))
    expect(screen.queryByText('问诊表单内容')).toBeNull()
    expect(screen.getByRole('button', { name: '展开问诊录入' })).toBeTruthy()
  })
})
