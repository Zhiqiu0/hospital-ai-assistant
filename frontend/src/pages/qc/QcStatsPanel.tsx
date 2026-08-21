/**
 * 质控指标统计面板（pages/qc/QcStatsPanel.tsx，2026-08-21 阶段5）
 *
 * 医务科《病案首页质量通报》的数据界面：科室评分/甲级率、高频扣分条款 Top、
 * 复核统计、归档时效（代理口径，界面明示）。CSV 导出直接作通报素材。
 */
import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Select, Space, Statistic, Table, Typography } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { message } from '@/services/messageBridge'
import api from '@/services/api'
import { useAuthStore } from '@/store/authStore'

interface DeptStat {
  department: string
  count: number
  avg_score: number
  grade_a_rate: number
  pass_rate: number
}
interface RuleStat {
  rule_code: string
  count: number
  description: string
}
interface Summary {
  days: number
  dept_stats: DeptStat[]
  top_rules: RuleStat[]
  reviews: { passed: number; returned: number }
  archive_proxy: { total: number; ok: number; rate: number | null; caliber: string }
}

export default function QcStatsPanel() {
  const [days, setDays] = useState(30)
  const [data, setData] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(false)
  const token = useAuthStore(s => s.token)

  const load = useCallback(async (d: number) => {
    setLoading(true)
    try {
      setData((await api.get(`/qc/stats/summary?days=${d}`)) as unknown as Summary)
    } catch {
      message.error('加载统计失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(days)
  }, [days, load])

  const exportCsv = async () => {
    // CSV 下载要带鉴权头，走 fetch + blob（api 拦截器是 JSON 语义）
    try {
      const res = await fetch(`/api/v1/qc/stats/export?days=${days}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error()
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `质控指标_近${days}天.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      message.error('导出失败')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Space>
        <Select
          value={days}
          onChange={setDays}
          options={[
            { value: 7, label: '近 7 天' },
            { value: 30, label: '近 30 天' },
            { value: 90, label: '近 90 天' },
          ]}
          style={{ width: 110 }}
        />
        <Button icon={<DownloadOutlined />} onClick={exportCsv}>
          导出 CSV（通报素材）
        </Button>
      </Space>

      <Space size="large" wrap>
        <Card size="small">
          <Statistic title="复核通过" value={data?.reviews.passed ?? '—'} />
        </Card>
        <Card size="small">
          <Statistic
            title="退回整改"
            value={data?.reviews.returned ?? '—'}
            valueStyle={{ color: data?.reviews.returned ? '#d97706' : undefined }}
          />
        </Card>
        <Card size="small">
          <Statistic
            title="归档时效达标率"
            value={data?.archive_proxy.rate ?? '无样本'}
            suffix={data?.archive_proxy.rate != null ? '%' : ''}
          />
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            口径：{data?.archive_proxy.caliber || ''}
          </Typography.Text>
        </Card>
      </Space>

      <Card size="small" title="科室质控评分（按最新一次质控口径）">
        <Table<DeptStat>
          rowKey="department"
          size="small"
          loading={loading}
          dataSource={data?.dept_stats || []}
          pagination={false}
          columns={[
            { title: '科室', dataIndex: 'department' },
            { title: '评分文书数', dataIndex: 'count', width: 110 },
            { title: '平均分', dataIndex: 'avg_score', width: 90 },
            { title: '甲级率', dataIndex: 'grade_a_rate', width: 90, render: v => `${v}%` },
            { title: '合格率', dataIndex: 'pass_rate', width: 90, render: v => `${v}%` },
          ]}
        />
      </Card>

      <Card size="small" title="高频扣分条款 Top 10（典型缺陷通报素材）">
        <Table<RuleStat>
          rowKey="rule_code"
          size="small"
          loading={loading}
          dataSource={data?.top_rules || []}
          pagination={false}
          columns={[
            { title: '条款代码', dataIndex: 'rule_code', width: 200 },
            { title: '次数', dataIndex: 'count', width: 80 },
            { title: '条款内容', dataIndex: 'description' },
          ]}
        />
      </Card>
    </div>
  )
}
