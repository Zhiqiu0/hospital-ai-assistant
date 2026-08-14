/**
 * 错误边界组件（components/ErrorBoundary.tsx）
 *
 * React class component，捕获子树中的未处理 JS 运行时错误，
 * 防止整个应用崩溃白屏：
 *   - 捕获到错误时展示 Ant Design Result「页面出错了」
 *   - 提供「重新加载」按钮调用 window.location.reload()
 *   - 上报 Sentry（见 componentDidCatch 里的说明）
 *
 * 使用位置：
 *   main.tsx 根部包裹整个 App（兜底，避免白屏）。
 *   另外用 compact 模式包裹工作台里彼此独立的外围面板（AI 建议、影像、化验），
 *   让某个面板崩掉时医生正在写的病历编辑器不受牵连。
 */
import React from 'react'
import { Button, Result } from 'antd'
import * as Sentry from '@sentry/react'

interface Props extends React.PropsWithChildren {
  /**
   * 出错区域的名字（如「AI 建议面板」），同时用于 Sentry 标签与界面文案。
   * 不传表示根边界。
   */
  label?: string
  /**
   * 紧凑模式：只占据所在容器的一块，而不是整屏。
   * 局部面板必须用它，否则一个侧边面板出错会铺满整个视口。
   */
  compact?: boolean
}

interface State {
  hasError: boolean
  error?: Error
}

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
    // ── 上报 Sentry（2026-08-14 第七轮审计 #35）──────────────────────────────
    //
    // 这里原先只有一行 console.error。项目是接了 Sentry 的，但 Sentry 的全局
    // handler 只能收到**没人捕获**的异常——而错误边界的职责恰恰是把渲染期异常
    // 捕获下来，于是「让医生白屏的那一类错误」一条都传不到 Sentry。
    // 结果是监控面板一片干净，看着像没出过事，实际上医生那边已经打不开页面了，
    // 只能靠他打电话过来，我们还拿不到堆栈。
    Sentry.withScope(scope => {
      scope.setTag('boundary', this.props.label || 'root')
      scope.setContext('react', { componentStack: info.componentStack })
      Sentry.captureException(error)
    })
  }

  handleReset = () => {
    this.setState({ hasError: false, error: undefined })
  }

  render() {
    if (!this.state.hasError) return this.props.children

    const { label, compact } = this.props
    const title = label ? `${label}出错了` : '页面发生错误'
    const subTitle = this.state.error?.message || '未知错误，请尝试刷新页面'

    // 紧凑模式：只在自己那块区域里显示，且优先给「重试」——
    // 局部面板崩了通常重挂一次就好，不该逼医生刷新整页丢掉在写的病历。
    if (compact) {
      return (
        <div style={{ padding: 16 }}>
          <Result
            status="warning"
            title={<span style={{ fontSize: 14 }}>{title}</span>}
            subTitle={<span style={{ fontSize: 12 }}>{subTitle}</span>}
            extra={
              <Button size="small" onClick={this.handleReset}>
                重试
              </Button>
            }
          />
        </div>
      )
    }

    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
        }}
      >
        <Result
          status="error"
          title={title}
          subTitle={subTitle}
          extra={[
            <Button type="primary" key="reload" onClick={() => window.location.reload()}>
              刷新页面
            </Button>,
            <Button key="reset" onClick={this.handleReset}>
              尝试恢复
            </Button>,
          ]}
        />
      </div>
    )
  }
}
