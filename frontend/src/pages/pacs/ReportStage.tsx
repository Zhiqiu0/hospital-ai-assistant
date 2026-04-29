/**
 * 报告审核阶段（pages/pacs/ReportStage.tsx）
 *
 * 内容：
 *   - 左：AI 分析原文（只读 Paragraph）
 *   - 右：最终报告（可编辑 TextArea + 重新选帧 / 确认发布按钮）
 */
import { Row, Col, Card, Space, Button, Typography, Input } from 'antd'
import { CheckCircleOutlined } from '@ant-design/icons'

const { Paragraph } = Typography
const { TextArea } = Input

interface ReportStageProps {
  aiResult: string
  finalReport: string
  setFinalReport: (s: string) => void
  publishing: boolean
  publishReport: () => void
  setStage: (s: 'select_frames') => void
}

export default function ReportStage({
  aiResult,
  finalReport,
  setFinalReport,
  publishing,
  publishReport,
  setStage,
}: ReportStageProps) {
  return (
    <Row gutter={16}>
      <Col span={12}>
        <Card title="AI 分析原文" style={{ height: 'calc(100vh - 140px)', overflow: 'auto' }}>
          <Paragraph style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 13 }}>
            {aiResult}
          </Paragraph>
        </Card>
      </Col>
      <Col span={12}>
        <Card
          title="最终报告（可编辑）"
          extra={
            <Space>
              <Button onClick={() => setStage('select_frames')}>重新选帧</Button>
              <Button
                type="primary"
                icon={<CheckCircleOutlined />}
                loading={publishing}
                onClick={publishReport}
              >
                确认发布
              </Button>
            </Space>
          }
          style={{ height: 'calc(100vh - 140px)' }}
          bodyStyle={{
            display: 'flex',
            flexDirection: 'column',
            height: 'calc(100% - 57px)',
            padding: 12,
          }}
        >
          <TextArea
            value={finalReport}
            onChange={e => setFinalReport(e.target.value)}
            style={{ flex: 1, fontFamily: 'monospace', fontSize: 13, resize: 'none' }}
          />
        </Card>
      </Col>
    </Row>
  )
}
