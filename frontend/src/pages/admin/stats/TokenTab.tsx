/**
 * Token 用量 Tab（admin/stats/TokenTab.tsx）
 *
 * 内容：
 *   - DeepSeek 账户余额（可用 / 充值 / 赠送）
 *   - 4 张 Token 用量统计卡（累计调用 / 累计 tokens / 今日 tokens / 今日输出）
 *   - 各功能 token 消耗明细 Table（含合计行）
 */
import { Row, Col, Card, Statistic, Table, Typography, Tag } from 'antd'
import {
  WalletOutlined,
  ApiOutlined,
  ArrowUpOutlined,
  ThunderboltOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import { Spin } from 'antd'

import { TASK_TYPE_MAP } from './constants'

const { Text } = Typography

interface TokenTabProps {
  tokenData: any
  loading: boolean
}

export default function TokenTab({ tokenData, loading }: TokenTabProps) {
  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin />
      </div>
    )
  }

  const totalTokens = (tokenData?.total_input_tokens ?? 0) + (tokenData?.total_output_tokens ?? 0)
  const todayTokens = (tokenData?.today_input_tokens ?? 0) + (tokenData?.today_output_tokens ?? 0)
  const balance = tokenData?.balance

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

  // KPI 卡片配置
  const kpiCards = [
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
  ]

  return (
    <>
      {/* 账户余额 */}
      <Card
        title={
          <span>
            <WalletOutlined style={{ marginRight: 6 }} />
            DeepSeek 账户余额
          </span>
        }
        style={{ marginBottom: 16 }}
        extra={balance ? <Tag color="success">连接正常</Tag> : <Tag color="error">获取失败</Tag>}
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

      {/* KPI 卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {kpiCards.map(c => (
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

      {/* Token 消耗明细 */}
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
                <Table.Summary.Cell index={4}>{(ti + to_).toLocaleString()}</Table.Summary.Cell>
              </Table.Summary.Row>
            )
          }}
        />
      </Card>
    </>
  )
}
