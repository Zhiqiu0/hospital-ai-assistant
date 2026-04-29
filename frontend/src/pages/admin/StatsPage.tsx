/**
 * 统计报表页（pages/admin/StatsPage.tsx）
 *
 * 系统使用数据的多维度统计分析。本文件作为容器：
 *   - 并发拉取 4 个 endpoint（overview / token / usage / qc-issues）
 *   - 把数据交给对应 Tab 组件渲染（拆到 admin/stats/ 子目录）
 *
 * 拆分理由：原文件 680 行远超页面 ≤ 400 行规范，4 个 Tab 视图相互独立，
 * 各自抽成独立组件后维护更清晰。
 */
import { useEffect, useState } from 'react'
import { Tabs, Typography } from 'antd'

import api from '@/services/api'
import OverviewTab from './stats/OverviewTab'
import UsageTab from './stats/UsageTab'
import QCTab from './stats/QCTab'
import TokenTab from './stats/TokenTab'

const { Title } = Typography

export default function StatsPage() {
  const [overview, setOverview] = useState<any>(null)
  const [tokenData, setTokenData] = useState<any>(null)
  const [usageData, setUsageData] = useState<any>(null)
  const [qcData, setQcData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [tokenLoading, setTokenLoading] = useState(true)
  const [usageLoading, setUsageLoading] = useState(true)
  const [qcLoading, setQcLoading] = useState(true)

  // 并发拉 4 个统计接口；任一失败不影响其他 Tab 正常渲染
  useEffect(() => {
    api
      .get('/admin/stats/overview')
      .then((d: any) => setOverview(d))
      .finally(() => setLoading(false))
    api
      .get('/admin/stats/token-usage')
      .then((d: any) => setTokenData(d))
      .finally(() => setTokenLoading(false))
    api
      .get('/admin/stats/usage')
      .then((d: any) => setUsageData(d))
      .finally(() => setUsageLoading(false))
    api
      .get('/admin/stats/qc-issues')
      .then((d: any) => setQcData(d))
      .finally(() => setQcLoading(false))
  }, [])

  return (
    <div>
      <Title level={4} style={{ marginBottom: 24 }}>
        数据统计
      </Title>
      <Tabs
        items={[
          {
            key: 'overview',
            label: '运营概览',
            children: <OverviewTab overview={overview} loading={loading} />,
          },
          {
            key: 'usage',
            label: '科室使用',
            children: <UsageTab usageData={usageData} loading={usageLoading} />,
          },
          {
            key: 'qc',
            label: '质控分析',
            children: <QCTab qcData={qcData} loading={qcLoading} />,
          },
          {
            key: 'token',
            label: 'Token 用量',
            children: <TokenTab tokenData={tokenData} loading={tokenLoading} />,
          },
        ]}
      />
    </div>
  )
}
