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
import { Row, Col, Card, Statistic, Table, Typography, Tag, Progress } from 'antd'
import {
  TeamOutlined,
  FileTextOutlined,
  RobotOutlined,
  SafetyOutlined,
  WarningOutlined,
} from '@ant-design/icons'

import { RISK_COLOR, RISK_LABEL, ISSUE_TYPE_LABEL } from './constants'

const { Text } = Typography

interface OverviewTabProps {
  overview: any
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

  // ── AI 功能分布数据（饼图替代为条形图） ───────────────────────────
  const aiFeatureData = [
    { key: '1', type: '病历生成', count: overview?.generate_count ?? 0 },
    { key: '2', type: '病历润色', count: overview?.polish_count ?? 0 },
    { key: '3', type: 'AI质控', count: overview?.qc_count ?? 0 },
    { key: '4', type: '追问建议', count: overview?.inquiry_count ?? 0 },
    { key: '5', type: '检查建议', count: overview?.exam_count ?? 0 },
  ]
  const totalAIFeature = aiFeatureData.reduce((s, r) => s + r.count, 0)

  // ── 质控问题摘要 ────────────────────────────────────────────────────
  const qcSummaryData = [
    {
      key: '1',
      issue_type: 'completeness',
      risk_level: 'high',
      count: overview?.completeness_issues ?? 0,
    },
    { key: '2', issue_type: 'format', risk_level: 'medium', count: overview?.format_issues ?? 0 },
    { key: '3', issue_type: 'logic', risk_level: 'low', count: overview?.logic_issues ?? 0 },
  ]

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
                {
                  title: '风险',
                  dataIndex: 'risk_level',
                  render: (v: string) => (
                    <Tag color={RISK_COLOR[v]} style={{ borderRadius: 20 }}>
                      {RISK_LABEL[v]}
                    </Tag>
                  ),
                },
                { title: '数量', dataIndex: 'count' },
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
