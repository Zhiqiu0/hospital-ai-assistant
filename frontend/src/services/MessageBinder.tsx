/**
 * AntApp 内部组件：把 App.useApp() 返回的 message instance 桥接到全局 messageBridge。
 *
 * 单独成文件而非定义在 main.tsx：
 *   Vite + React Fast Refresh 只能 HMR 默认导出组件的文件。main.tsx 同时导出
 *   非组件副作用代码（initSentry, ReactDOM.createRoot 等）+ 组件会触发
 *   `react-refresh/only-export-components` ESLint 警告，拆出后 main.tsx 保持
 *   纯入口，本文件只 export 组件。
 */
import { useEffect } from 'react'
import { App as AntApp } from 'antd'

import { bindMessageApi } from './messageBridge'

export function MessageBinder({ children }: { children: React.ReactNode }) {
  const { message } = AntApp.useApp()
  useEffect(() => {
    bindMessageApi(message)
  }, [message])
  return <>{children}</>
}
