import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#2563eb',
          colorBgContainer: '#ffffff',
          colorBgLayout: '#eef2f7',
          colorBorder: '#e2e8f0',
          colorBorderSecondary: '#f1f5f9',
          colorTextBase: '#0f172a',
          colorTextSecondary: '#64748b',
          colorTextTertiary: '#94a3b8',
          borderRadius: 8,
          borderRadiusLG: 12,
          borderRadiusSM: 6,
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
          fontSize: 14,
          fontSizeSM: 12,
          boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
          boxShadowSecondary: '0 4px 12px rgba(0,0,0,0.08)',
          controlHeight: 34,
          controlHeightSM: 28,
          controlHeightLG: 40,
          motionDurationMid: '0.18s',
          lineWidth: 1,
        },
        components: {
          Menu: {
            itemBorderRadius: 8,
            itemHeight: 40,
            itemMarginInline: 6,
            subMenuItemBg: 'transparent',
            itemActiveBg: '#eff6ff',
            itemSelectedBg: '#eff6ff',
            itemSelectedColor: '#2563eb',
          },
          Table: {
            headerBg: '#f8fafc',
            headerSplitColor: 'transparent',
            rowHoverBg: '#f8fafc',
            borderColor: '#f1f5f9',
          },
          Card: {
            paddingLG: 20,
            headerHeight: 52,
          },
          Button: {
            fontWeight: 500,
            primaryShadow: '0 2px 6px rgba(37,99,235,0.25)',
          },
          Input: {
            paddingBlock: 6,
            paddingInline: 10,
            activeShadow: '0 0 0 3px rgba(37,99,235,0.12)',
          },
          Select: {
            selectorBg: '#ffffff',
          },
          Modal: {
            borderRadiusLG: 14,
          },
          Tabs: {
            horizontalItemGutter: 20,
            inkBarColor: '#2563eb',
            itemActiveColor: '#2563eb',
            itemSelectedColor: '#2563eb',
          },
          Form: {
            labelColor: '#475569',
            labelFontSize: 12,
          },
          Divider: {
            colorSplit: '#f1f5f9',
          },
          Badge: {
            colorBgContainer: '#ffffff',
          },
          Tag: {
            defaultBg: '#f1f5f9',
            defaultColor: '#64748b',
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
      <App />
    </ConfigProvider>
  </React.StrictMode>
)
