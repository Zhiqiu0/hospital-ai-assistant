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
 * ── 2026-05-03 重构 ───────────────────────────────────────────────────────
 * 跟 AI 诊断/追问建议模式对齐：每条建议带「写入/已写入」切换按钮（替代旧"开单"
 * 文案）；写入时同时做两件事：
 *   1. 把当前所有 isOrdered=true 的 exam_name 用「、」拼接后写入病历【辅助检查】
 *      章节（章节级 replace，不会破坏后续【诊断】等章节）
 *   2. 同步 inquiry.auxiliary_exam DB 字段（保持单一数据源），保存接诊时持久化
 * 撤销时（再点已写入）反向：从拼接列表移除该 exam_name → 重写章节 + 同步字段。
 *
 * 配套迁移：
 *   - 左侧问诊面板 InquiryPhysicalExam / 住院端 PhysicalExamSection 的 auxiliary_exam
 *     textarea 已删除，避免一字段多源冲突。
 *   - 化验单 OCR、影像分析当前过渡期"只展示不写入病历"，下次迭代独立章节。
 */
import { useCallback } from 'react'
import { Button, List, Tag, Typography, Empty, Spin, message } from 'antd'
import { ExperimentOutlined, CheckOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { useAISuggestionStore } from '@/store/aiSuggestionStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { ExamSuggestion } from '@/store/types'
import { writeSectionToRecord } from './qcFieldMaps'
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
  const inquiry = useInquiryStore(s => s.inquiry)
  const setInquiry = useInquiryStore(s => s.setInquiry)
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const { recordContent, setRecordContent } = useRecordStore()
  const { examSuggestions, isExamLoading, setExamSuggestions, setExamLoading } =
    useAISuggestionStore()

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
        encounter_id: currentEncounterId || undefined,
      })
      setExamSuggestions(data.suggestions || [])
    } catch {
      setExamSuggestions([])
    } finally {
      setExamLoading(false)
    }
  }, [inquiry.chief_complaint, inquiry.history_present_illness, inquiry.initial_impression])

  /**
   * 切换"写入/已写入"状态：
   *   - 切换 examSuggestions[].isOrdered 标记（store persist 保活刷新页面也在）
   *   - 用所有 isOrdered=true 的 exam_name 重写 inquiry.auxiliary_exam（结构化字段）
   *   - 用 writeSectionToRecord 重写病历【辅助检查】章节（章节级 replace，
   *     不会破坏后续【诊断】等章节，区别于 InquirySuggestion 的"marker 后全删"）
   * 撤销时（再点已写入）反向：移除该 exam_name 后同步两处。
   */
  const handleToggleOrdered = (examName: string) => {
    const updated = examSuggestions.map((s: ExamSuggestion) =>
      s.exam_name === examName ? { ...s, isOrdered: !s.isOrdered } : s
    )
    setExamSuggestions(updated)
    // 拼接当前所有 isOrdered=true 的检查项；保持 examSuggestions 列表顺序与医生
    // 点击顺序无关，符合"基础必查→鉴别→高风险"原始 AI 输出顺序，便于阅读
    const orderedNames = updated.filter(s => s.isOrdered).map(s => s.exam_name)
    const joined = orderedNames.join('、')
    // 1) 同步病历章节（即时，跟 AI 诊断"写入"一致的视觉反馈）
    setRecordContent(writeSectionToRecord(recordContent, 'auxiliary_exam', joined))
    // 2) 同步 inquiry.auxiliary_exam（保存接诊时随 inquiry PUT 上去持久化）
    const newInquiry = { ...inquiry, auxiliary_exam: joined }
    setInquiry(newInquiry)
    if (currentEncounterId) {
      // 静默 PUT，跟 LabReportTab 之前模式一致；失败不阻塞 UI（下次保存按钮还会再试）
      api.put(`/encounters/${currentEncounterId}/inquiry`, newInquiry).catch(() => {})
    }
  }

  if (isExamLoading) {
    return (
      <div style={{ textAlign: 'center', padding: '40px 0' }}>
        <Spin size="small" />
        <div style={{ marginTop: 8, color: 'var(--text-4)', fontSize: 12 }}>AI 分析中...</div>
      </div>
    )
  }

  if (examSuggestions.length === 0) {
    return (
      <div style={{ textAlign: 'center', marginTop: 40 }}>
        <Empty
          description={
            <span style={{ fontSize: 13, color: 'var(--text-4)' }}>
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
        <List.Item
          key={idx}
          style={{ padding: '10px 0', borderBlockEnd: '1px solid var(--border-subtle)' }}
        >
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
                  color: item.isOrdered ? 'var(--text-4)' : 'var(--text-1)',
                  textDecoration: item.isOrdered ? 'line-through' : 'none',
                }}
              >
                {item.exam_name}
              </Text>
              {/* 写入/已写入切换：跟 DiagnosisSuggestion 模式对齐（图标 + 绿色态） */}
              <Button
                size="small"
                type={item.isOrdered ? 'primary' : 'default'}
                icon={item.isOrdered ? <CheckOutlined /> : <ArrowRightOutlined />}
                onClick={() => handleToggleOrdered(item.exam_name)}
                style={{
                  fontSize: 11,
                  height: 22,
                  borderRadius: 12,
                  flexShrink: 0,
                  ...(item.isOrdered
                    ? { background: '#22c55e', borderColor: '#22c55e' }
                    : { borderColor: 'var(--border)', color: 'var(--text-3)' }),
                }}
              >
                {item.isOrdered ? '已写入' : '写入'}
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
