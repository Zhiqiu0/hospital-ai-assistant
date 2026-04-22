/**
 * EmptyState.test.tsx
 * 验证 EmptyState 基础渲染 + actions 插槽
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Button } from 'antd'
import EmptyState from './EmptyState'

describe('<EmptyState />', () => {
  it('渲染 title 和 description', () => {
    render(<EmptyState title="暂无数据" description="请先添加患者" />)
    expect(screen.getByText('暂无数据')).toBeInTheDocument()
    expect(screen.getByText('请先添加患者')).toBeInTheDocument()
  })

  it('actions 插槽正确渲染', () => {
    render(<EmptyState description="请先登录" actions={<Button>去登录</Button>} />)
    expect(screen.getByRole('button', { name: '去登录' })).toBeInTheDocument()
  })
})
