/**
 * 历史病历抽屉（components/workbench/HistoryDrawer.tsx）
 *
 * 展示当前登录医生历史已签发病历列表，从右侧滑出：
 *   - 调用 GET /medical-records/my 加载数据（useWorkbenchBase.loadHistory）
 *   - 列表显示：患者姓名、就诊类型、病历类型、签发时间
 *   - 点击「查看」弹出 RecordViewModal 显示完整内容
 *
 * 权限边界：
 *   仅返回当前医生自己的病历（后端按 created_by 过滤）。
 *   管理员查看全量病历需使用 /admin/records 页面。
 *
 * 状态颜色：
 *   submitted → 绿色「已签发」  draft → 橙色「草稿」
 */
import { Drawer, List, Button, Space, Tag, Badge, Empty, Typography } from 'antd'
import { HistoryOutlined, FileTextOutlined, EyeOutlined } from '@ant-design/icons'

const { Text } = Typography

interface HistoryDrawerProps {
  open: boolean
  onClose: () => void
  records: any[]
  loading: boolean
  onView: (record: any) => void
  accentColor: string
  tagColor: string
  recordTypeLabel: (type: string) => string
}

export default function HistoryDrawer({
  open,
  onClose,
  records,
  loading,
  onView,
  accentColor,
  tagColor,
  recordTypeLabel,
}: HistoryDrawerProps) {
  return (
    <Drawer
      title={
        <Space>
          <HistoryOutlined style={{ color: accentColor }} />
          <span>历史签发病历</span>
          <Badge count={records.length} style={{ background: accentColor }} />
        </Space>
      }
      open={open}
      onClose={onClose}
      width={480}
      styles={{ body: { padding: '8px 0' } }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: '48px 0', color: 'var(--text-4)' }}>加载中...</div>
      ) : records.length === 0 ? (
        <Empty
          description="暂无签发病历"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ marginTop: 60 }}
        />
      ) : (
        <List
          dataSource={records}
          renderItem={(record: any) => (
            <List.Item
              style={{ padding: '12px 20px', cursor: 'pointer' }}
              onClick={() => onView(record)}
              extra={
                <Button
                  size="small"
                  type="text"
                  icon={<EyeOutlined />}
                  style={{ color: accentColor }}
                  onClick={e => {
                    e.stopPropagation()
                    onView(record)
                  }}
                >
                  查看
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
                      background: 'linear-gradient(135deg, #eff6ff, #dbeafe)',
                      border: '1px solid #bfdbfe',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <FileTextOutlined style={{ color: accentColor, fontSize: 16 }} />
                  </div>
                }
                title={
                  <Space size={6}>
                    <Text strong style={{ fontSize: 14 }}>
                      {record.patient_name}
                    </Text>
                    {/* 初诊/复诊N 标识：只对门诊/急诊显示。visit_sequence=1 初诊；>=2 显示复诊 N（N=seq-1） */}
                    {record.visit_type !== 'inpatient' && typeof record.visit_sequence === 'number' && (
                      <Tag
                        color={record.visit_sequence === 1 ? 'blue' : 'green'}
                        style={{ fontSize: 11, margin: 0 }}
                      >
                        {record.visit_sequence === 1 ? '初诊' : `复诊 ${record.visit_sequence - 1}`}
                      </Tag>
                    )}
                    <Tag color={tagColor} style={{ fontSize: 11, margin: 0 }}>
                      {recordTypeLabel(record.record_type)}
                    </Tag>
                  </Space>
                }
                description={
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {record.submitted_at
                        ? new Date(record.submitted_at).toLocaleString('zh-CN')
                        : '-'}
                    </Text>
                    <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2, lineHeight: 1.4 }}>
                      {record.content_preview || '（无内容预览）'}
                    </div>
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
