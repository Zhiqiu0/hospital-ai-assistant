/**
 * 对话角色分析卡片（SpeakerDialogueCard.tsx）
 * 展示 AI 识别的医生/患者对话分段列表。
 */
import { Card, List, Space, Tag, Typography } from 'antd'

const { Text } = Typography

const SPEAKER_META: Record<string, { color: string; label: string }> = {
  doctor: { color: 'blue', label: '医生' },
  patient: { color: 'green', label: '患者' },
  uncertain: { color: 'orange', label: '待确认' },
}

interface DialogueItem {
  speaker: 'doctor' | 'patient' | 'uncertain'
  text: string
}

interface Props {
  items: DialogueItem[]
}

export default function SpeakerDialogueCard({ items }: Props) {
  if (!items.length) return null
  return (
    <Card
      size="small"
      style={{ marginBottom: 8, borderRadius: 8, background: '#fff' }}
      bodyStyle={{ padding: 10 }}
    >
      <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
        <Tag color="cyan" style={{ marginRight: 0 }}>
          角色分析
        </Tag>
        <Text style={{ fontSize: 12, color: '#64748b' }}>
          AI 会尽量区分医生与患者；不确定内容会单独标记
        </Text>
      </div>
      <List
        size="small"
        dataSource={items}
        renderItem={item => (
          <List.Item style={{ padding: '6px 0', borderBlockEnd: '1px solid #f1f5f9' }}>
            <Space align="start">
              <Tag
                color={SPEAKER_META[item.speaker]?.color || 'default'}
                style={{ marginRight: 0 }}
              >
                {SPEAKER_META[item.speaker]?.label || '待确认'}
              </Tag>
              <Text style={{ fontSize: 12 }}>{item.text}</Text>
            </Space>
          </List.Item>
        )}
      />
    </Card>
  )
}
