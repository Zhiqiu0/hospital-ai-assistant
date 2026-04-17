/**
 * 检查建议标签页（components/workbench/ExamSuggestionTab.tsx）
 *
 * AISuggestionPanel 中的「检查建议」标签内容。
 *
 * 数据来源：
 *   调用 POST /ai/suggest-exam，传入当前问诊内容，获取 ExamSuggestion[] 并渲染。
 *
 * ExamSuggestion 结构：
 *   { exam_name, reason, category: 'basic'|'differential'|'high_risk', isOrdered? }
 *
 * 已开单功能：
 *   每条检查建议有「已开单」切换按钮，状态存于 ExamSuggestion.isOrdered。
 *   由于 examSuggestions 持久化到 localStorage，刷新后开单状态不丢失。
 *   再次点击取消已开单状态。
 *
 * 注意：「已开单」是纯前端标记，不触发任何后端医嘱接口。
 */
import { useCallback } from 'react'
import { Button, List, Tag, Typography, Empty, Spin, message } from 'antd'
import { ExperimentOutlined, CheckOutlined } from '@ant-design/icons'
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
  const { inquiry, examSuggestions, isExamLoading, setExamSuggestions, setExamLoading } =
    useWorkbenchStore()

  // 切换接诊时清空逻辑已移至 workbenchStore.setCurrentEncounter，
  // 在 store 层判断 encounterId 是否真正变化，避免 React StrictMode 双次 effect 误清空。

  /** 调用 AI 获取检查建议列表 */
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

  /**
   * 切换已开单状态：点击标记为已开单，再次点击取消。
   * 直接更新 store 中对应条目的 isOrdered 字段，随 persist 持久化。
   */
  const handleToggleOrdered = (examName: string) => {
    setExamSuggestions(
      examSuggestions.map((s: ExamSuggestion) =>
        s.exam_name === examName ? { ...s, isOrdered: !s.isOrdered } : s
      )
    )
  }

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
              <Text
                strong
                style={{
                  fontSize: 13,
                  flex: 1,
                  // 已开单时文字变灰，视觉上区分
                  color: item.isOrdered ? '#94a3b8' : '#0f172a',
                  textDecoration: item.isOrdered ? 'line-through' : 'none',
                }}
              >
                {item.exam_name}
              </Text>
              {/* 已开单切换按钮：绿色=已开单，默认=未开单，再次点击取消 */}
              <Button
                size="small"
                type={item.isOrdered ? 'primary' : 'default'}
                icon={item.isOrdered ? <CheckOutlined /> : undefined}
                onClick={() => handleToggleOrdered(item.exam_name)}
                style={{
                  fontSize: 11,
                  height: 22,
                  borderRadius: 12,
                  flexShrink: 0,
                  ...(item.isOrdered
                    ? { background: '#22c55e', borderColor: '#22c55e' }
                    : { borderColor: '#e2e8f0', color: '#64748b' }),
                }}
              >
                {item.isOrdered ? '已开单' : '开单'}
              </Button>
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
