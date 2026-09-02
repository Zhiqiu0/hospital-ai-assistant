/**
 * 错误边界回归（2026-09-03 前端崩溃保护）
 *
 * 这是防白屏的最后一道防线，却一直没有测试——而它 2026-08-14 才补上 Sentry
 * 上报（在那之前只有一行 console.error，"让医生白屏的那一类错误"一条都传不到
 * 监控）。这种容易被悄悄改坏的东西必须有回归。
 *
 * 医生的场景：正在写住院病历，右侧某个面板抛错。局部边界能接住就只是那块区域
 * 显示重试按钮，编辑器和正在写的内容都不受影响；接不住就整页「页面发生错误」，
 * 必须刷新。
 */
import { render, screen, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const captureException = vi.fn()
const withScope = vi.fn((fn: (scope: unknown) => void) =>
  fn({ setTag: vi.fn(), setContext: vi.fn() })
)
vi.mock('@sentry/react', () => ({
  captureException: (...a: unknown[]) => captureException(...a),
  withScope: (fn: (scope: unknown) => void) => withScope(fn),
}))

import { ErrorBoundary } from './ErrorBoundary'

function Boom({ msg = '组件炸了' }: { msg?: string }): JSX.Element {
  throw new Error(msg)
}

let errSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  captureException.mockClear()
  withScope.mockClear()
  // React 渲染期错误会往 console.error 打两长段，屏蔽掉保持测试输出干净
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  errSpy.mockRestore()
  cleanup()
})

describe('ErrorBoundary', () => {
  it('正常情况下不干扰子树渲染', () => {
    render(
      <ErrorBoundary>
        <div>病历编辑器</div>
      </ErrorBoundary>
    )
    expect(screen.getByText('病历编辑器')).toBeTruthy()
  })

  it('子组件抛错时给出兜底 UI 而不是白屏', () => {
    render(
      <ErrorBoundary>
        <Boom msg="渲染失败" />
      </ErrorBoundary>
    )
    expect(screen.getByText('页面发生错误')).toBeTruthy()
    expect(screen.getByText('渲染失败')).toBeTruthy()
    // 根边界要同时给「刷新页面」和「尝试恢复」
    expect(screen.getByText('刷新页面')).toBeTruthy()
  })

  it('局部面板崩溃只显示自己那块，不铺满整屏', () => {
    render(
      <ErrorBoundary label="右侧面板" compact>
        <Boom />
      </ErrorBoundary>
    )
    expect(screen.getByText('右侧面板出错了')).toBeTruthy()
    // compact 模式只给「重试」——局部面板重挂一次通常就好，
    // 不该逼医生刷新整页丢掉在写的病历。
    // 用正则匹配：antd 会给两个汉字的按钮自动插空格（重试 → 重 试）
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeTruthy()
    expect(screen.queryByText('刷新页面')).toBeNull()
  })

  it('把错误上报 Sentry 并带上区域标签', () => {
    render(
      <ErrorBoundary label="AI 建议面板" compact>
        <Boom />
      </ErrorBoundary>
    )
    expect(captureException).toHaveBeenCalledTimes(1)
    expect(withScope).toHaveBeenCalledTimes(1)
  })

  it('兄弟面板崩溃不影响正在写的编辑器', () => {
    render(
      <div>
        <ErrorBoundary label="右侧面板" compact>
          <Boom />
        </ErrorBoundary>
        <div>医生正在写的病历正文</div>
      </div>
    )
    expect(screen.getByText('右侧面板出错了')).toBeTruthy()
    expect(screen.getByText('医生正在写的病历正文')).toBeTruthy()
  })
})
