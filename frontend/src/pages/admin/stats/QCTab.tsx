/**
 * 质控分析 Tab（admin/stats/QCTab.tsx）
 *
 * 内容：
 *   - 质控问题分布（按 issue_type + risk_level 分组的 Table）
 *   - 高频问题字段 Top 10（field_name 排行）
 */
import { Row, Col, Card, Table, Tag, Spin } from 'antd'
import { SafetyOutlined } from '@ant-design/icons'

import { RISK_COLOR, RISK_LABEL, ISSUE_TYPE_LABEL } from './constants'

interface QCTabProps {
  qcData: any
  loading: boolean
}

export default function QCTab({ qcData, loading }: QCTabProps) {
  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin />
      </div>
    )
  }

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

  return (
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
          title={<span style={{ fontSize: 14, fontWeight: 600 }}>高频问题字段 Top 10</span>}
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
  )
}
