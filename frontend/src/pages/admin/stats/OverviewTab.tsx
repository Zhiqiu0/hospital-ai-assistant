/**
 * 运营概览 Tab（admin/stats/OverviewTab.tsx）
 *
 * 内容：
 *   - 4 张 KPI 卡片（今日接诊 / 累计接诊 / AI调用 / 质控问题总数）
 *   - AI 功能使用分布（Progress 条形图）
 *   - 质控问题分类（小型 Table）
 *   - 风险等级分布（高/中/低 三个突出卡片）
 *
 * data 来自父容器 StatsPage 调 /admin/stats/overview，
 * 子组件不再自己 fetch，避免重复网络请求。
 */
import { Row, Col, Card, Statistic, Table, Typography, Progress } from 'antd'
import {
  TeamOutlined,
  FileTextOutlined,
  RobotOutlined,
  SafetyOutlined,
  WarningOutlined,
} from '@ant-design/icons'

import { ISSUE_TYPE_LABEL, TASK_TYPE_MAP } from './constants'

const { Text } = Typography

/**
 * /admin/stats/overview 返回值——后端 stats_service.overview 输出。
 * 字段全部 optional：当样本量为 0 时后端可能不返回某些计数键。
 */
export interface OverviewData {
  today_encounters?: number
  total_encounters?: number
  total_ai_tasks?: number
  total_qc_issues?: number
  /** 全量分布（2026-08-29）：后端直接回传 group-by dict，键=原始类型标识。
   *  此前前后端各自硬编码 5/3 个键，rubric 质控类与新增 AI 功能整类不可见 */
  task_type_counts?: Record<string, number>
  issue_type_counts?: Record<string, number>
  high_risk_issues?: number
  medium_risk_issues?: number
  low_risk_issues?: number
}

interface OverviewTabProps {
  overview: OverviewData | null
  loading: boolean
}

export default function OverviewTab({ overview, loading }: OverviewTabProps) {
  // ── KPI 卡片数据 ─────────────────────────────────────────────────────
  const statCards = [
    {
      title: '今日接诊',
      value: overview?.today_encounters ?? 0,
      icon: <TeamOutlined />,
      color: '#2563eb',
      bg: '#eff6ff',
      border: '#bfdbfe',
    },
    {
      title: '累计接诊',
      value: overview?.total_encounters ?? 0,
      icon: <FileTextOutlined />,
      color: '#059669',
      bg: '#f0fdf4',
      border: '#bbf7d0',
    },
    {
      title: 'AI调用次数',
      value: overview?.total_ai_tasks ?? 0,
      icon: <RobotOutlined />,
      color: '#7c3aed',
      bg: '#f5f3ff',
      border: '#ddd6fe',
    },
    {
      title: '质控问题总数',
      value: overview?.total_qc_issues ?? 0,
      icon: <SafetyOutlined />,
      color: '#d97706',
      bg: '#fffbeb',
      border: '#fde68a',
    },
  ]

  // ── AI 功能分布数据（全量渲染后端 dict，按次数降序；未知类型兜底显示
  //    原始标识而不是整类消失）─────────────────────────────────────────
  const aiFeatureData = Object.entries(overview?.task_type_counts ?? {})
    .sort(([, a], [, b]) => b - a)
    .map(([type, count]) => ({ key: type, type: TASK_TYPE_MAP[type] || type, count }))
  const totalAIFeature = aiFeatureData.reduce((s, r) => s + r.count, 0)

  // ── 质控问题摘要 ────────────────────────────────────────────────────
  // 修复 2026-05-15：之前把"问题类型"和"风险等级"两个独立维度硬绑定
  //   (completeness↔high / format↔medium / logic↔low)，
  // 导致"分类总数"和底部"风险等级总数"对不上（前者只统计绑定那一格，后者全量）。
  // 现在拆开——分类表只按 issue_type 统计总数，风险等级走下方独立卡片。
  // 2026-08-29：改为全量渲染后端 group-by dict（此前硬编码三类，rubric
  // 规则类问题在看板整类不可见）。
  const qcSummaryData = Object.entries(overview?.issue_type_counts ?? {})
    .sort(([, a], [, b]) => b - a)
    .map(([issue_type, count]) => ({ key: issue_type, issue_type, count }))

  // ── 风险等级卡片 ────────────────────────────────────────────────────
  const riskCards = [
    {
      label: '高风险问题',
      value: overview?.high_risk_issues ?? 0,
      color: '#ef4444',
      bg: '#fef2f2',
      border: '#fecaca',
    },
    {
      label: '中风险问题',
      value: overview?.medium_risk_issues ?? 0,
      color: '#f59e0b',
      bg: '#fffbeb',
      border: '#fde68a',
    },
    {
      label: '低风险问题',
      value: overview?.low_risk_issues ?? 0,
      color: '#3b82f6',
      bg: '#eff6ff',
      border: '#bfdbfe',
    },
  ]

  return (
    <>
      {/* KPI 卡片 */}
      <Row gutter={[16, 16]}>
        {statCards.map(c => (
          <Col xs={24} sm={12} lg={6} key={c.title}>
            <Card
              loading={loading}
              style={{
                borderRadius: 10,
                border: `1px solid ${c.border}`,
                background: c.bg,
                boxShadow: 'none',
              }}
              styles={{ body: { padding: '18px 20px' } }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  justifyContent: 'space-between',
                }}
              >
                <Statistic
                  title={
                    <span style={{ fontSize: 12, color: 'var(--text-3)', fontWeight: 500 }}>
                      {c.title}
                    </span>
                  }
                  value={c.value}
                  valueStyle={{
                    color: c.color,
                    fontSize: 28,
                    fontWeight: 700,
                    lineHeight: 1.2,
                  }}
                />
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: 10,
                    background: c.color,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--surface)',
                    fontSize: 18,
                    flexShrink: 0,
                    opacity: 0.9,
                  }}
                >
                  {c.icon}
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {/* AI 功能分布 */}
        <Col xs={24} lg={12}>
          <Card
            title={
              <span style={{ fontSize: 14, fontWeight: 600 }}>
                <RobotOutlined style={{ marginRight: 6, color: '#7c3aed' }} />
                AI功能使用分布
              </span>
            }
            loading={loading}
            styles={{ body: { padding: '12px 20px' } }}
          >
            {aiFeatureData.length === 0 && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                暂无 AI 调用记录
              </Text>
            )}
            {aiFeatureData.map(item => (
              <div
                key={item.key}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  marginBottom: 10,
                }}
              >
                <Text style={{ width: 72, fontSize: 12, color: 'var(--text-2)', flexShrink: 0 }}>
                  {item.type}
                </Text>
                <Progress
                  percent={totalAIFeature ? Math.round((item.count / totalAIFeature) * 100) : 0}
                  size="small"
                  style={{ flex: 1 }}
                  strokeColor="#7c3aed"
                  format={() => <span style={{ fontSize: 12 }}>{item.count}</span>}
                />
              </div>
            ))}
          </Card>
        </Col>

        {/* 质控问题分类 */}
        <Col xs={24} lg={12}>
          <Card
            title={
              <span style={{ fontSize: 14, fontWeight: 600 }}>
                <WarningOutlined style={{ marginRight: 6, color: '#d97706' }} />
                质控问题分类
              </span>
            }
            loading={loading}
            styles={{ body: { padding: '4px 8px' } }}
          >
            <Table
              size="small"
              pagination={false}
              dataSource={qcSummaryData}
              columns={[
                {
                  title: '问题类型',
                  dataIndex: 'issue_type',
                  render: (v: string) => ISSUE_TYPE_LABEL[v] || v,
                },
                { title: '总数', dataIndex: 'count' },
              ]}
            />
          </Card>
        </Col>
      </Row>

      {/* 风险等级分布 */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {riskCards.map(c => (
          <Col xs={24} sm={8} key={c.label}>
            <Card
              loading={loading}
              style={{
                borderRadius: 10,
                border: `1px solid ${c.border}`,
                background: c.bg,
                boxShadow: 'none',
                textAlign: 'center',
              }}
              styles={{ body: { padding: '16px' } }}
            >
              <div style={{ fontSize: 32, fontWeight: 700, color: c.color }}>{c.value}</div>
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4 }}>{c.label}</div>
            </Card>
          </Col>
        ))}
      </Row>
    </>
  )
}
