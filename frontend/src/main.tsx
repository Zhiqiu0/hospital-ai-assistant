/**
 * 应用入口（main.tsx）
 *
 * 挂载 React 应用到 #root 节点，配置全局：
 *   - Ant Design ConfigProvider（中文语言包 + 主题 token）
 *   - ErrorBoundary（捕获组件级错误，防止白屏）
 *
 * 主题采用 design tokens 单一来源（theme/tokens.ts），禁止在此处硬编码颜色。
 */

import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import { scenes, neutral, radius, typography, shadow } from './theme/tokens'
import './index.css'

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
          Card: {
            paddingLG: 20,
            headerHeight: 52,
          },
          Button: {
            fontWeight: 500,
            primaryShadow: `0 2px 6px rgba(${outpatient.shadowRgba},0.25)`,
          },
          Input: {
            paddingBlock: 6,
            paddingInline: 10,
            activeShadow: `0 0 0 3px rgba(${outpatient.shadowRgba},0.12)`,
          },
          Select: {
            selectorBg: neutral.surface,
          },
          Modal: {
            borderRadiusLG: 14,
          },
          Tabs: {
            horizontalItemGutter: 20,
            inkBarColor: outpatient.primary,
            itemActiveColor: outpatient.primary,
            itemSelectedColor: outpatient.primary,
          },
          Form: {
            labelColor: neutral.text2,
            labelFontSize: typography.fontSize.sm,
          },
          Divider: {
            colorSplit: neutral.borderSubtle,
          },
          Badge: {
            colorBgContainer: neutral.surface,
          },
          Tag: {
            defaultBg: neutral.surface3,
            defaultColor: neutral.text3,
          },
          Alert: {
            borderRadiusLG: 10,
          },
          Drawer: {
            paddingLG: 20,
          },
        },
      }}
    >
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </ConfigProvider>
  </React.StrictMode>
)
