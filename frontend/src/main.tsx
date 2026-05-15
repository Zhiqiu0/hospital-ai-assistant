/**
 * 应用入口（main.tsx）
 *
 * 挂载 React 应用到 #root 节点，配置全局：
 *   - Ant Design ConfigProvider（中文语言包 + 主题 token）
 *   - ErrorBoundary（捕获组件级错误，防止白屏）
 *
 * 主题采用 design tokens 单一来源（theme/tokens.ts），禁止在此处硬编码颜色。
 * 仅维护浅色一套设计，不做深浅切换。
 */

import React from 'react'
import ReactDOM from 'react-dom/client'
// AntApp 是 antd v5 的全局上下文容器，提供 message/notification/Modal 真正能渲染
// 的 React 上下文（v5.4+ 静态 `import { message } from 'antd'` 不再消费上下文，
// 一定要走 App.useApp()）。MessageBinder 把 App.useApp() 返回的 message instance
// 注入到 services/messageBridge，业务代码继续用 `import { message } from
// '@/services/messageBridge'` 不变。
import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import { MessageBinder } from './services/MessageBinder'
import { initSentry } from './sentry'
import { scenes, neutral, radius, typography, shadow } from './theme/tokens'
import './index.css'

// Sentry 初始化必须早于 React 渲染，否则错过早期 unhandled error / rejection
// DSN 未配置时内部直接 return，本地开发零侵入
initSentry()

const outpatient = scenes.outpatient

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: outpatient.primary,
          colorBgContainer: neutral.surface,
          colorBgLayout: neutral.bg,
          colorBorder: neutral.border,
          colorBorderSecondary: neutral.borderSubtle,
          colorTextBase: neutral.text1,
          colorTextSecondary: neutral.text3,
          colorTextTertiary: neutral.text4,
          borderRadius: radius.md,
          borderRadiusLG: radius.lg,
          borderRadiusSM: radius.sm,
          fontFamily: typography.fontBody,
          fontSize: typography.fontSize.base,
          fontSizeSM: typography.fontSize.sm,
          boxShadow: shadow.sm,
          boxShadowSecondary: shadow.md,
          controlHeight: 34,
          controlHeightSM: 28,
          controlHeightLG: 40,
          motionDurationMid: '0.18s',
          lineWidth: 1,
        },
        components: {
          Menu: {
            itemBorderRadius: radius.md,
            itemHeight: 40,
            itemMarginInline: 6,
            subMenuItemBg: 'transparent',
            itemActiveBg: outpatient.primaryLight,
            itemSelectedBg: outpatient.primaryLight,
            itemSelectedColor: outpatient.primary,
          },
          Table: {
            headerBg: neutral.surface2,
            headerSplitColor: 'transparent',
            rowHoverBg: neutral.surface2,
            borderColor: neutral.borderSubtle,
          },
          Card: { paddingLG: 20, headerHeight: 52 },
          Button: {
            fontWeight: 500,
            primaryShadow: `0 2px 6px rgba(${outpatient.shadowRgba},0.25)`,
          },
          Input: {
            paddingBlock: 6,
            paddingInline: 10,
            activeShadow: `0 0 0 3px rgba(${outpatient.shadowRgba},0.12)`,
          },
          Select: { selectorBg: neutral.surface },
          Modal: { borderRadiusLG: 14 },
          Tabs: {
            horizontalItemGutter: 20,
            inkBarColor: outpatient.primary,
            itemActiveColor: outpatient.primary,
            itemSelectedColor: outpatient.primary,
          },
          Form: { labelColor: neutral.text2, labelFontSize: typography.fontSize.sm },
          Divider: { colorSplit: neutral.borderSubtle },
          Badge: { colorBgContainer: neutral.surface },
          Tag: { defaultBg: neutral.surface3, defaultColor: neutral.text3 },
          Alert: { borderRadiusLG: 10 },
          Drawer: { paddingLG: 20 },
        },
      }}
    >
      {/* AntApp 必须套在 ConfigProvider 之内、业务组件之上。
          MessageBinder 在 AntApp 内部用 useApp() 拿 message 实例并桥接到全局 bridge。 */}
      <AntApp>
        <MessageBinder>
          <ErrorBoundary>
            <App />
          </ErrorBoundary>
        </MessageBinder>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>
)
