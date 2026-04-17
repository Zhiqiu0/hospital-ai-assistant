/**
 * 错误边界组件（components/ErrorBoundary.tsx）
 *
 * React class component，捕获子树中的未处理 JS 运行时错误，
 * 防止整个应用崩溃白屏：
 *   - 捕获到错误时展示 Ant Design Result「页面出错了」
 *   - 提供「重新加载」按钮调用 window.location.reload()
 *   - 错误信息通过 console.error 输出（便于开发调试）
 *
 * 使用位置：
 *   App.tsx 根路由外层，包裹所有页面级组件。
 *   不应用于局部组件（粒度太细会丢失 UI 上下文）。
 */
import React from 'react'
import { Button, Result } from 'antd'

interface State {
  hasError: boolean
  error?: Error
}

export class ErrorBoundary extends React.Component<React.PropsWithChildren, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: undefined })
  }

  render() {
    if (this.state.hasError) {
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
            title="页面发生错误"
            subTitle={this.state.error?.message || '未知错误，请尝试刷新页面'}
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
    return this.props.children
  }
}
