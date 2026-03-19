import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Table, Typography, Tag, Alert, Spin } from 'antd'
import { WalletOutlined, ApiOutlined, ArrowUpOutlined, ThunderboltOutlined } from '@ant-design/icons'
import api from '@/services/api'

const { Title, Text } = Typography

const TASK_TYPE_MAP: Record<string, string> = {
  generate: '病历生成',
  polish: '病历润色',
  qc: 'AI质控',
  inquiry: '追问建议',
  exam: '检查建议',
}

export default function TokenUsagePage() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/admin/stats/token-usage')
      .then((d: any) => setData(d))
      .catch(() => setError('数据加载失败'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>

  const balance = data?.balance
  const totalTokens = (data?.total_input_tokens ?? 0) + (data?.total_output_tokens ?? 0)
  const todayTokens = (data?.today_input_tokens ?? 0) + (data?.today_output_tokens ?? 0)

  const columns = [
    {
      title: '功能', dataIndex: 'task_type', key: 'task_type',
      render: (v: string) => TASK_TYPE_MAP[v] || v,
    },
    { title: '调用次数', dataIndex: 'calls', key: 'calls' },
    {
      title: '输入 Tokens', dataIndex: 'input_tokens', key: 'input_tokens',
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: '输出 Tokens', dataIndex: 'output_tokens', key: 'output_tokens',
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: '合计 Tokens', key: 'total',
      render: (_: any, row: any) => (row.input_tokens + row.output_tokens).toLocaleString(),
    },
  ]

  return (
    <div>
      <Title level={4} style={{ marginBottom: 8 }}>Token 用量 & 账户余额</Title>
      <Text type="secondary" style={{ fontSize: 12 }}>
        余额数据来自 DeepSeek 官方 API（实时），Token 统计来自本地调用记录
      </Text>

      {error && <Alert type="error" message={error} style={{ marginTop: 12 }} />}

      {/* 余额卡片 */}
      <Card
        title={<span><WalletOutlined style={{ marginRight: 6 }} />DeepSeek 账户余额</span>}
        style={{ marginTop: 16 }}
        extra={
          balance
            ? <Tag color="success">连接正常</Tag>
            : <Tag color="error">获取失败（网络或Key问题）</Tag>
        }
      >
        {balance ? (
          <Row gutter={24}>
            <Col>
              <Statistic
                title="可用余额"
                value={parseFloat(balance.total_balance ?? '0')}
                precision={2}
                prefix="¥"
                suffix="CNY"
                valueStyle={{ color: '#52c41a', fontSize: 32, fontWeight: 700 }}
              />
            </Col>
            <Col>
              <Statistic
                title="充值余额"
                value={parseFloat(balance.topped_up_balance ?? '0')}
                precision={2}
                prefix="¥"
                valueStyle={{ fontSize: 24 }}
              />
            </Col>
            <Col>
              <Statistic
                title="赠送余额"
                value={parseFloat(balance.granted_balance ?? '0')}
                precision={2}
                prefix="¥"
                valueStyle={{ fontSize: 24, color: '#1677ff' }}
              />
            </Col>
          </Row>
        ) : (
          <Text type="secondary">无法获取余额，请检查 DEEPSEEK_API_KEY 配置</Text>
        )}
      </Card>

      {/* Token 消耗统计 */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="累计调用次数"
              value={data?.total_calls ?? 0}
              prefix={<ApiOutlined />}
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="累计消耗 Tokens"
              value={totalTokens}
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="今日消耗 Tokens"
              value={todayTokens}
              prefix={<ArrowUpOutlined />}
              valueStyle={{ color: '#fa8c16' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="今日输出 Tokens"
              value={data?.today_output_tokens ?? 0}
              valueStyle={{ color: '#13c2c2' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 按功能分类 */}
      <Card title="各功能 Token 消耗明细" style={{ marginTop: 16 }}>
        <Table
          columns={columns}
          dataSource={data?.by_task_type ?? []}
          rowKey="task_type"
          pagination={false}
          locale={{ emptyText: '暂无调用记录' }}
          summary={(rows) => {
            const totalCalls = rows.reduce((s, r) => s + r.calls, 0)
            const totalIn = rows.reduce((s, r) => s + r.input_tokens, 0)
            const totalOut = rows.reduce((s, r) => s + r.output_tokens, 0)
            return (
              <Table.Summary.Row style={{ fontWeight: 600, background: '#fafafa' }}>
                <Table.Summary.Cell index={0}>合计</Table.Summary.Cell>
                <Table.Summary.Cell index={1}>{totalCalls}</Table.Summary.Cell>
                <Table.Summary.Cell index={2}>{totalIn.toLocaleString()}</Table.Summary.Cell>
                <Table.Summary.Cell index={3}>{totalOut.toLocaleString()}</Table.Summary.Cell>
                <Table.Summary.Cell index={4}>{(totalIn + totalOut).toLocaleString()}</Table.Summary.Cell>
              </Table.Summary.Row>
            )
          }}
        />
      </Card>
    </div>
  )
}
