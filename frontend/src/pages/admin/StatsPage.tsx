/**
 * 统计报表页（pages/admin/StatsPage.tsx）
 *
 * 系统使用数据的多维度统计分析，调用 GET /admin/stats：
 *   - 时间维度 Tab：今日 / 近7天 / 近30天 / 自定义范围
 *   - 接诊量趋势：折线图（按天统计门诊/急诊/住院）
 *   - 科室排名：按签发病历数降序的 Progress 条形图
 *   - AI 功能使用率：各 task_type 调用次数饼图
 *   - 质控通过率：按时间段的通过/不通过比例
 *
 * 数据来源于后端聚合查询，不在前端做计算。
 */
import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Table, Typography, Tag, Tabs, Spin, Progress } from 'antd'
import {
  TeamOutlined,
  FileTextOutlined,
  RobotOutlined,
  SafetyOutlined,
  WalletOutlined,
  ApiOutlined,
  ArrowUpOutlined,
  ThunderboltOutlined,
  ApartmentOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import api from '@/services/api'

const { Title, Text } = Typography

const TASK_TYPE_MAP: Record<string, string> = {
  generate: '病历生成',
  polish: '病历润色',
  qc: 'AI质控',
  inquiry: '追问建议',
  exam: '检查建议',
}

const RISK_COLOR: Record<string, string> = { high: 'red', medium: 'orange', low: 'blue' }
const RISK_LABEL: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险' }
const ISSUE_TYPE_LABEL: Record<string, string> = {
  completeness: '完整性缺失',
  format: '格式不规范',
  logic: '逻辑问题',
  insurance: '医保风险',
  normality: '规范性',
  consistency: '一致性',
}

export default function StatsPage() {
  const [overview, setOverview] = useState<any>(null)
  const [tokenData, setTokenData] = useState<any>(null)
  const [usageData, setUsageData] = useState<any>(null)
  const [qcData, setQcData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [tokenLoading, setTokenLoading] = useState(true)
  const [usageLoading, setUsageLoading] = useState(true)
  const [qcLoading, setQcLoading] = useState(true)

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

  const aiFeatureData = [
    { key: '1', type: '病历生成', count: overview?.generate_count ?? 0 },
    { key: '2', type: '病历润色', count: overview?.polish_count ?? 0 },
    { key: '3', type: 'AI质控', count: overview?.qc_count ?? 0 },
    { key: '4', type: '追问建议', count: overview?.inquiry_count ?? 0 },
    { key: '5', type: '检查建议', count: overview?.exam_count ?? 0 },
  ]
  const totalAIFeature = aiFeatureData.reduce((s, r) => s + r.count, 0)

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

  const totalTokens = (tokenData?.total_input_tokens ?? 0) + (tokenData?.total_output_tokens ?? 0)
  const todayTokens = (tokenData?.today_input_tokens ?? 0) + (tokenData?.today_output_tokens ?? 0)
  const balance = tokenData?.balance

  const deptColumns = [
    { title: '科室', dataIndex: 'department_name', key: 'name' },
    {
      title: '接诊次数',
      dataIndex: 'encounter_count',
      key: 'count',
      render: (v: number, _: any, i: number) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Progress
            percent={Math.round(
              (v /
                Math.max(
                  ...(usageData?.by_department ?? []).map((d: any) => d.encounter_count),
                  1
                )) *
                100
            )}
            showInfo={false}
            size="small"
            style={{ flex: 1, maxWidth: 100 }}
            strokeColor={i === 0 ? '#2563eb' : i === 1 ? '#059669' : '#94a3b8'}
          />
          <Text strong style={{ fontSize: 13 }}>
            {v}
          </Text>
        </div>
      ),
    },
  ]

  const qcTypeColumns = [
    {
      title: '问题类型',
      dataIndex: 'issue_type',
      key: 'issue_type',
      render: (v: string) => ISSUE_TYPE_LABEL[v] || v,
    },
    {
      title: '风险等级',
      dataIndex: 'risk_level',
      key: 'risk_level',
      render: (v: string) => (
        <Tag color={RISK_COLOR[v] || 'default'} style={{ borderRadius: 20 }}>
          {RISK_LABEL[v] || v}
        </Tag>
      ),
    },
    { title: '数量', dataIndex: 'count', key: 'count' },
  ]

  const qcFieldColumns = [
    { title: '字段', dataIndex: 'field_name', key: 'field_name' },
    { title: '问题次数', dataIndex: 'count', key: 'count' },
  ]

  const tokenColumns = [
    {
      title: '功能',
      dataIndex: 'task_type',
      key: 'task_type',
      render: (v: string) => TASK_TYPE_MAP[v] || v,
    },
    { title: '调用次数', dataIndex: 'calls', key: 'calls' },
    {
      title: '输入 Tokens',
      dataIndex: 'input_tokens',
      key: 'input_tokens',
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: '输出 Tokens',
      dataIndex: 'output_tokens',
      key: 'output_tokens',
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: '合计',
      key: 'total',
      render: (_: any, row: any) => (row.input_tokens + row.output_tokens).toLocaleString(),
    },
  ]

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
            children: (
              <>
                {/* KPI cards */}
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
                              <span style={{ fontSize: 12, color: '#64748b', fontWeight: 500 }}>
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
                              color: '#fff',
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
                  {/* AI feature breakdown */}
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
                          <Text
                            style={{ width: 72, fontSize: 12, color: '#475569', flexShrink: 0 }}
                          >
                            {item.type}
                          </Text>
                          <Progress
                            percent={
                              totalAIFeature ? Math.round((item.count / totalAIFeature) * 100) : 0
                            }
                            size="small"
                            style={{ flex: 1 }}
                            strokeColor="#7c3aed"
                            format={() => <span style={{ fontSize: 12 }}>{item.count}</span>}
                          />
                        </div>
                      ))}
                    </Card>
                  </Col>

                  {/* QC issue summary */}
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

                {/* Risk level breakdown */}
                <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
                  {[
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
                  ].map(c => (
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
                        <div style={{ fontSize: 32, fontWeight: 700, color: c.color }}>
                          {c.value}
                        </div>
                        <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                          {c.label}
                        </div>
                      </Card>
                    </Col>
                  ))}
                </Row>
              </>
            ),
          },
          {
            key: 'usage',
            label: '科室使用',
            children: usageLoading ? (
              <div style={{ textAlign: 'center', padding: 60 }}>
                <Spin />
              </div>
            ) : (
              <Row gutter={[16, 16]}>
                <Col xs={24} lg={14}>
                  <Card
                    title={
                      <span style={{ fontSize: 14, fontWeight: 600 }}>
                        <ApartmentOutlined style={{ marginRight: 6, color: '#2563eb' }} />
                        各科室接诊量
                      </span>
                    }
                    styles={{ body: { padding: '4px 8px' } }}
                  >
                    <Table
                      dataSource={usageData?.by_department ?? []}
                      columns={deptColumns}
                      rowKey="department_id"
                      pagination={false}
                      size="small"
                      locale={{ emptyText: '暂无数据' }}
                    />
                  </Card>
                </Col>
                <Col xs={24} lg={10}>
                  <Card
                    title={<span style={{ fontSize: 14, fontWeight: 600 }}>近7日接诊趋势</span>}
                    styles={{ body: { padding: '12px 20px' } }}
                  >
                    {(usageData?.daily_trend ?? []).length === 0 ? (
                      <Text type="secondary" style={{ fontSize: 13 }}>
                        暂无近7日数据
                      </Text>
                    ) : (
                      <div>
                        {(usageData?.daily_trend ?? []).map((d: any) => (
                          <div
                            key={d.date}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: 8,
                              marginBottom: 8,
                            }}
                          >
                            <Text
                              style={{ width: 80, fontSize: 12, color: '#64748b', flexShrink: 0 }}
                            >
                              {d.date}
                            </Text>
                            <Progress
                              percent={Math.round(
                                (d.count /
                                  Math.max(
                                    ...(usageData?.daily_trend ?? []).map((x: any) => x.count),
                                    1
                                  )) *
                                  100
                              )}
                              size="small"
                              style={{ flex: 1 }}
                              strokeColor="#2563eb"
                              format={() => <span style={{ fontSize: 12 }}>{d.count}</span>}
                            />
                          </div>
                        ))}
                      </div>
                    )}
                  </Card>
                </Col>
              </Row>
            ),
          },
          {
            key: 'qc',
            label: '质控分析',
            children: qcLoading ? (
              <div style={{ textAlign: 'center', padding: 60 }}>
                <Spin />
              </div>
            ) : (
              <Row gutter={[16, 16]}>
                <Col xs={24} lg={14}>
                  <Card
                    title={
                      <span style={{ fontSize: 14, fontWeight: 600 }}>
                        <SafetyOutlined style={{ marginRight: 6, color: '#d97706' }} />
                        质控问题分布
                      </span>
                    }
                    styles={{ body: { padding: '4px 8px' } }}
                  >
                    <Table
                      dataSource={qcData?.by_type ?? []}
                      columns={qcTypeColumns}
                      rowKey={(r: any) => `${r.issue_type}-${r.risk_level}`}
                      pagination={false}
                      size="small"
                      locale={{ emptyText: '暂无质控数据' }}
                    />
                  </Card>
                </Col>
                <Col xs={24} lg={10}>
                  <Card
                    title={
                      <span style={{ fontSize: 14, fontWeight: 600 }}>高频问题字段 Top 10</span>
                    }
                    styles={{ body: { padding: '4px 8px' } }}
                  >
                    <Table
                      dataSource={qcData?.top_fields ?? []}
                      columns={qcFieldColumns}
                      rowKey="field_name"
                      pagination={false}
                      size="small"
                      locale={{ emptyText: '暂无数据' }}
                    />
                  </Card>
                </Col>
              </Row>
            ),
          },
          {
            key: 'token',
            label: 'Token 用量',
            children: tokenLoading ? (
              <div style={{ textAlign: 'center', padding: 60 }}>
                <Spin />
              </div>
            ) : (
              <>
                <Card
                  title={
                    <span>
                      <WalletOutlined style={{ marginRight: 6 }} />
                      DeepSeek 账户余额
                    </span>
                  }
                  style={{ marginBottom: 16 }}
                  extra={
                    balance ? (
                      <Tag color="success">连接正常</Tag>
                    ) : (
                      <Tag color="error">获取失败</Tag>
                    )
                  }
                >
                  {balance ? (
                    <Row gutter={32}>
                      <Col>
                        <Statistic
                          title="可用余额"
                          value={parseFloat(balance.total_balance ?? '0')}
                          precision={2}
                          prefix="¥"
                          suffix="CNY"
                          valueStyle={{ color: '#52c41a', fontSize: 28, fontWeight: 700 }}
                        />
                      </Col>
                      <Col>
                        <Statistic
                          title="充值余额"
                          value={parseFloat(balance.topped_up_balance ?? '0')}
                          precision={2}
                          prefix="¥"
                          valueStyle={{ fontSize: 22 }}
                        />
                      </Col>
                      <Col>
                        <Statistic
                          title="赠送余额"
                          value={parseFloat(balance.granted_balance ?? '0')}
                          precision={2}
                          prefix="¥"
                          valueStyle={{ fontSize: 22, color: '#1677ff' }}
                        />
                      </Col>
                    </Row>
                  ) : (
                    <Text type="secondary">无法获取余额，请检查 DEEPSEEK_API_KEY 配置</Text>
                  )}
                </Card>

                <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                  {[
                    {
                      title: '累计调用次数',
                      value: tokenData?.total_calls ?? 0,
                      icon: <ApiOutlined />,
                      color: '#1677ff',
                    },
                    {
                      title: '累计消耗 Tokens',
                      value: totalTokens,
                      icon: <ThunderboltOutlined />,
                      color: '#722ed1',
                    },
                    {
                      title: '今日消耗 Tokens',
                      value: todayTokens,
                      icon: <ArrowUpOutlined />,
                      color: '#fa8c16',
                    },
                    {
                      title: '今日输出 Tokens',
                      value: tokenData?.today_output_tokens ?? 0,
                      icon: <RobotOutlined />,
                      color: '#13c2c2',
                    },
                  ].map(c => (
                    <Col xs={24} sm={12} lg={6} key={c.title}>
                      <Card>
                        <Statistic
                          title={c.title}
                          value={c.value}
                          prefix={c.icon}
                          valueStyle={{ color: c.color }}
                        />
                      </Card>
                    </Col>
                  ))}
                </Row>

                <Card title="各功能 Token 消耗明细">
                  <Table
                    columns={tokenColumns}
                    dataSource={tokenData?.by_task_type ?? []}
                    rowKey="task_type"
                    pagination={false}
                    locale={{ emptyText: '暂无调用记录' }}
                    summary={rows => {
                      const tc = rows.reduce((s, r) => s + r.calls, 0)
                      const ti = rows.reduce((s, r) => s + r.input_tokens, 0)
                      const to_ = rows.reduce((s, r) => s + r.output_tokens, 0)
                      return (
                        <Table.Summary.Row style={{ fontWeight: 600 }}>
                          <Table.Summary.Cell index={0}>合计</Table.Summary.Cell>
                          <Table.Summary.Cell index={1}>{tc}</Table.Summary.Cell>
                          <Table.Summary.Cell index={2}>{ti.toLocaleString()}</Table.Summary.Cell>
                          <Table.Summary.Cell index={3}>{to_.toLocaleString()}</Table.Summary.Cell>
                          <Table.Summary.Cell index={4}>
                            {(ti + to_).toLocaleString()}
                          </Table.Summary.Cell>
                        </Table.Summary.Row>
                      )
                    }}
                  />
                </Card>
              </>
            ),
          },
        ]}
      />
    </div>
  )
}
