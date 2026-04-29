/**
 * 科室使用 Tab（admin/stats/UsageTab.tsx）
 *
 * 内容：
 *   - 各科室接诊量 Table（按 encounter_count 倒序，Progress 条形图标记前三）
 *   - 近 7 日接诊趋势（按日期 Progress 条形图）
 */
import { Row, Col, Card, Table, Typography, Spin, Progress } from 'antd'
import { ApartmentOutlined } from '@ant-design/icons'

const { Text } = Typography

interface UsageTabProps {
  usageData: any
  loading: boolean
}

export default function UsageTab({ usageData, loading }: UsageTabProps) {
  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin />
      </div>
    )
  }

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
            strokeColor={i === 0 ? '#2563eb' : i === 1 ? '#059669' : 'var(--text-4)'}
          />
          <Text strong style={{ fontSize: 13 }}>
            {v}
          </Text>
        </div>
      ),
    },
  ]

  const dailyTrend = usageData?.daily_trend ?? []
  const maxDailyCount = Math.max(...dailyTrend.map((x: any) => x.count), 1)

  return (
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
          {dailyTrend.length === 0 ? (
            <Text type="secondary" style={{ fontSize: 13 }}>
              暂无近7日数据
            </Text>
          ) : (
            <div>
              {dailyTrend.map((d: any) => (
                <div
                  key={d.date}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    marginBottom: 8,
                  }}
                >
                  <Text style={{ width: 80, fontSize: 12, color: 'var(--text-3)', flexShrink: 0 }}>
                    {d.date}
                  </Text>
                  <Progress
                    percent={Math.round((d.count / maxDailyCount) * 100)}
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
  )
}
