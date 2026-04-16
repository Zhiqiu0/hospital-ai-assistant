import { useCallback, useEffect } from 'react'
import { Button, List, Tag, Typography, Empty, Spin, message } from 'antd'
import { ExperimentOutlined } from '@ant-design/icons'
import { useWorkbenchStore, ExamSuggestion } from '@/store/workbenchStore'
import api from '@/services/api'

const { Text } = Typography

const EXAM_CATEGORY_LABEL: Record<string, string> = {
  basic: '基础必查',
  differential: '鉴别诊断',
  high_risk: '高风险',
}
const EXAM_CATEGORY_COLOR: Record<string, string> = {
  basic: 'blue',
  differential: 'orange',
  high_risk: 'red',
}

export default function ExamSuggestionTab() {
  const {
    inquiry,
    examSuggestions,
    isExamLoading,
    setExamSuggestions,
    setExamLoading,
    currentEncounterId,
  } = useWorkbenchStore()

  // 切换接诊时清空检查建议（避免上一个患者的建议残留）
  useEffect(() => {
    setExamSuggestions([])
  }, [currentEncounterId])

  const handleLoad = useCallback(async () => {
    if (!inquiry.chief_complaint.trim()) {
      message.warning('请先填写主诉')
      return
    }
    setExamLoading(true)
    try {
      const data: any = await api.post('/ai/exam-suggestions', {
        chief_complaint: inquiry.chief_complaint,
        history_present_illness: inquiry.history_present_illness,
        initial_impression: inquiry.initial_impression,
      })
      setExamSuggestions(data.suggestions || [])
    } catch {
      setExamSuggestions([])
    } finally {
      setExamLoading(false)
    }
  }, [inquiry.chief_complaint, inquiry.history_present_illness, inquiry.initial_impression])

  if (isExamLoading) {
    return (
      <div style={{ textAlign: 'center', padding: '40px 0' }}>
        <Spin size="small" />
        <div style={{ marginTop: 8, color: '#94a3b8', fontSize: 12 }}>AI 分析中...</div>
      </div>
    )
  }

  if (examSuggestions.length === 0) {
    return (
      <div style={{ textAlign: 'center', marginTop: 40 }}>
        <Empty
          description={
            <span style={{ fontSize: 13, color: '#94a3b8' }}>
              保存问诊信息后，点击下方按钮获取检查建议
            </span>
          }
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
        <Button
          type="primary"
          icon={<ExperimentOutlined />}
          onClick={handleLoad}
          disabled={!inquiry.chief_complaint.trim()}
          style={{ marginTop: 12, borderRadius: 8 }}
        >
          生成检查建议
        </Button>
      </div>
    )
  }

  return (
    <List
      dataSource={examSuggestions}
      renderItem={(item: ExamSuggestion, idx) => (
        <List.Item key={idx} style={{ padding: '10px 0', borderBlockEnd: '1px solid #f1f5f9' }}>
          <div style={{ width: '100%' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <Tag
                color={EXAM_CATEGORY_COLOR[item.category] || 'default'}
                style={{ margin: 0, fontSize: 11 }}
              >
                {EXAM_CATEGORY_LABEL[item.category] || item.category}
              </Tag>
              <Text strong style={{ fontSize: 13 }}>
                {item.exam_name}
              </Text>
            </div>
            <Text type="secondary" style={{ fontSize: 12, lineHeight: 1.5 }}>
              {item.reason}
            </Text>
          </div>
        </List.Item>
      )}
    />
  )
}
