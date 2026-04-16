import { Drawer, List, Button, Space, Tag, Badge, Empty, Typography } from 'antd'
import { ReloadOutlined, ManOutlined, WomanOutlined } from '@ant-design/icons'

const { Text } = Typography

interface ResumeItem {
  encounter_id: string
  patient?: { name?: string; gender?: string; age?: number }
  visit_type?: string
  visited_at?: string
  chief_complaint_brief?: string
}

interface ResumeDrawerProps {
  open: boolean
  onClose: () => void
  list: ResumeItem[]
  loading: boolean
  onResume: (item: ResumeItem) => void
  accentColor: string
  title?: string
  emptyText?: string
  /** When false, shows the visit type tag (outpatient/inpatient/emergency). When true, always shows a fixed tag. */
  fixedTag?: { color: string; label: string }
}

export default function ResumeDrawer({
  open,
  onClose,
  list,
  loading,
  onResume,
  accentColor,
  title = '进行中接诊',
  emptyText = '暂无进行中接诊',
  fixedTag,
}: ResumeDrawerProps) {
  const visitTypeLabel: Record<string, string> = {
    outpatient: '门诊',
    inpatient: '住院',
    emergency: '急诊',
  }

  return (
    <Drawer
      title={
        <Space>
          <ReloadOutlined style={{ color: accentColor }} />
          <span>{title}</span>
          <Badge count={list.length} style={{ background: accentColor }} />
        </Space>
      }
      open={open}
      onClose={onClose}
      width={420}
      styles={{ body: { padding: '8px 0' } }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: '48px 0', color: '#94a3b8' }}>加载中...</div>
      ) : list.length === 0 ? (
        <Empty
          description={emptyText}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ marginTop: 60 }}
        />
      ) : (
        <List
          dataSource={list}
          renderItem={(item: ResumeItem) => (
            <List.Item
              style={{ padding: '12px 20px', cursor: 'pointer' }}
              extra={
                <Button
                  size="small"
                  onClick={() => onResume(item)}
                  style={{
                    borderRadius: 8,
                    background: accentColor,
                    borderColor: accentColor,
                    color: '#fff',
                  }}
                >
                  恢复
                </Button>
              }
            >
              <List.Item.Meta
                avatar={
                  <div
                    style={{
                      width: 38,
                      height: 38,
                      borderRadius: 10,
                      background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
                      border: '1px solid #bbf7d0',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    {item.patient?.gender === 'female' ? (
                      <WomanOutlined style={{ color: '#ec4899', fontSize: 16 }} />
                    ) : (
                      <ManOutlined style={{ color: accentColor, fontSize: 16 }} />
                    )}
                  </div>
                }
                title={
                  <Space size={6}>
                    <Text strong style={{ fontSize: 14 }}>
                      {item.patient?.name}
                    </Text>
                    {item.patient?.age && (
                      <Text style={{ fontSize: 12, color: '#64748b' }}>{item.patient.age}岁</Text>
                    )}
                    {fixedTag ? (
                      <Tag color={fixedTag.color} style={{ fontSize: 11, margin: 0 }}>
                        {fixedTag.label}
                      </Tag>
                    ) : (
                      <Tag color="blue" style={{ fontSize: 11, margin: 0 }}>
                        {visitTypeLabel[item.visit_type || ''] || item.visit_type}
                      </Tag>
                    )}
                  </Space>
                }
                description={
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {item.visited_at ? new Date(item.visited_at).toLocaleString('zh-CN') : '-'}
                    </Text>
                    {item.chief_complaint_brief && (
                      <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                        {item.chief_complaint_brief}
                      </div>
                    )}
                  </div>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Drawer>
  )
}
