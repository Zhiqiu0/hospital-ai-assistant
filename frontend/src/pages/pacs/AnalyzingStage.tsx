/**
 * AI 分析中阶段（pages/pacs/AnalyzingStage.tsx）
 *
 * 圆形进度 + 提示文案；通常 15-30 秒结束。
 */
import { Card, Progress, Spin, Typography, Tag } from 'antd'

const { Title, Text } = Typography

interface AnalyzingStageProps {
  selectedFramesCount: number
}

export default function AnalyzingStage({ selectedFramesCount }: AnalyzingStageProps) {
  return (
    <Card style={{ textAlign: 'center', padding: '48px 24px' }}>
      <Progress
        type="circle"
        percent={99}
        status="active"
        format={() => <Spin size="large" />}
        size={120}
        strokeColor={{ '0%': '#0891B2', '100%': '#06b6d4' }}
      />
      <Title level={4} style={{ marginTop: 24, marginBottom: 8 }}>
        AI 正在分析影像
      </Title>
      <Text type="secondary" style={{ fontSize: 13 }}>
        共 {selectedFramesCount} 张关键帧发送给通义千问视觉模型，通常需要 15-30 秒
      </Text>
      <div style={{ marginTop: 16 }}>
        <Tag color="processing">模型推理中</Tag>
        <Tag color="default">无需等待，可切到其他页面</Tag>
      </div>
    </Card>
  )
}
