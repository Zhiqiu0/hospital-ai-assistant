/**
 * 患者历史抽屉：选中患者后的病历列表（patientHistory/RecordList.tsx）
 *
 * 每条记录显示场景 Tag + 病历类型 + 签发时间 + 内容预览 + 查看按钮。
 */
import { List, Button, Space, Tag, Typography } from 'antd'
import { EyeOutlined } from '@ant-design/icons'
import { getSceneTag } from './sceneTag'

const { Text } = Typography

interface RecordListProps {
  records: any[]
  onView: (record: any) => void
  recordTypeLabel: (t: string) => string
}

export default function RecordList({ records, onView, recordTypeLabel }: RecordListProps) {
  return (
    <List
      style={{ padding: '8px 16px' }}
      dataSource={records}
      renderItem={(record: any) => {
        const scene = getSceneTag(record.visit_type, record.visit_sequence)
        return (
          <List.Item
            style={{
              padding: '12px 14px',
              marginBottom: 8,
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 10,
              transition: 'all 0.18s',
              cursor: 'pointer',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = '#86efac'
              e.currentTarget.style.boxShadow = '0 2px 8px rgba(5,150,105,0.1)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = 'var(--border)'
              e.currentTarget.style.boxShadow = 'none'
            }}
            actions={[
              <Button
                key="view"
                type="text"
                size="small"
                icon={<EyeOutlined />}
                onClick={() => onView(record)}
                style={{ color: '#059669' }}
              >
                查看
              </Button>,
            ]}
          >
            <List.Item.Meta
              title={
                <Space size={6}>
                  <Tag color={scene.color} style={{ fontSize: 11, margin: 0, fontWeight: 600 }}>
                    {scene.text}
                  </Tag>
                  <Text style={{ fontSize: 13, color: 'var(--text-2)' }}>
                    {recordTypeLabel(record.record_type)}
                  </Text>
                </Space>
              }
              description={
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {record.submitted_at
                      ? new Date(record.submitted_at).toLocaleString('zh-CN')
                      : '-'}
                  </Text>
                  <div
                    style={{
                      fontSize: 12,
                      color: 'var(--text-3)',
                      marginTop: 4,
                      lineHeight: 1.5,
                    }}
                  >
                    {record.content_preview || '（无内容预览）'}
                  </div>
                </div>
              }
            />
          </List.Item>
        )
      }}
    />
  )
}
