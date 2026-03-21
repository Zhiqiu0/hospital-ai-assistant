import { useEffect, useState, useCallback } from 'react'
import { Tabs, Button, Typography, Empty, Badge, Spin, Alert, List, Tag, message, Divider, Tooltip, Input } from 'antd'
import {
  QuestionCircleOutlined, ExperimentOutlined, SafetyOutlined,
  PlusOutlined, CheckOutlined, BulbOutlined, ArrowRightOutlined, EditOutlined, FileTextOutlined,
} from '@ant-design/icons'
import LabReportTab from './LabReportTab'
import { useWorkbenchStore, QCIssue, ExamSuggestion, GradeScore } from '@/store/workbenchStore'
import api from '@/services/api'

const { Text } = Typography

interface Suggestion {
  id: string
  text: string
  priority: 'high' | 'medium' | 'low'
  is_red_flag: boolean
  category: string
  options: string[]
  selectedOptions: string[]
}

interface DiagnosisItem {
  name: string
  confidence: 'high' | 'medium' | 'low'
  reasoning: string
  next_steps: string
}

const EXAM_CATEGORY_LABEL: Record<string, string> = { basic: '基础必查', differential: '鉴别诊断', high_risk: '高风险' }
const EXAM_CATEGORY_COLOR: Record<string, string> = { basic: 'blue', differential: 'orange', high_risk: 'red' }
const QC_RISK_COLOR: Record<string, string> = { high: 'red', medium: 'orange', low: 'default' }
const QC_RISK_LABEL: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险' }
const QC_TYPE_COLOR: Record<string, string> = {
  completeness: 'blue', insurance: 'purple', format: 'cyan', logic: 'gold', normality: 'geekblue',
}
const QC_TYPE_LABEL: Record<string, string> = {
  completeness: '完整性', insurance: '医保风险', format: '格式', logic: '逻辑', normality: '规范性',
}
const CONFIDENCE_CONFIG: Record<string, { color: string; label: string; bg: string }> = {
  high: { color: '#059669', label: '高度符合', bg: '#f0fdf4' },
  medium: { color: '#d97706', label: '可能符合', bg: '#fffbeb' },
  low: { color: '#64748b', label: '待排除', bg: '#f8fafc' },
}

// ── 甲级评分展示组件 ──────────────────────────────────────
const GRADE_CONFIG: Record<string, { color: string; bg: string; border: string; label: string; icon: string }> = {
  '甲级': { color: '#065f46', bg: 'linear-gradient(135deg, #f0fdf4, #dcfce7)', border: '#86efac', label: '甲级病历', icon: '🏆' },
  '乙级': { color: '#92400e', bg: 'linear-gradient(135deg, #fffbeb, #fef3c7)', border: '#fcd34d', label: '乙级病历', icon: '⚡' },
  '丙级': { color: '#991b1b', bg: 'linear-gradient(135deg, #fff1f2, #ffe4e6)', border: '#fca5a5', label: '丙级病历', icon: '⚠️' },
}

function GradeScoreCard({ gradeScore }: { gradeScore: GradeScore }) {
  const cfg = GRADE_CONFIG[gradeScore.grade_level] || GRADE_CONFIG['乙级']
  const score = gradeScore.grade_score
  // 环形进度指示
  const radius = 26
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (score / 100) * circumference

  return (
    <div style={{
      background: cfg.bg,
      border: `1px solid ${cfg.border}`,
      borderRadius: 12,
      padding: '12px 14px',
      marginBottom: 10,
      display: 'flex',
      alignItems: 'center',
      gap: 14,
    }}>
      {/* 环形分数 */}
      <div style={{ position: 'relative', width: 64, height: 64, flexShrink: 0 }}>
        <svg width={64} height={64} viewBox="0 0 64 64">
          <circle cx={32} cy={32} r={radius} fill="none" stroke="#e2e8f0" strokeWidth={6} />
          <circle
            cx={32} cy={32} r={radius}
            fill="none"
            stroke={score >= 90 ? '#22c55e' : score >= 75 ? '#f59e0b' : '#ef4444'}
            strokeWidth={6}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            transform="rotate(-90 32 32)"
            style={{ transition: 'stroke-dashoffset 0.6s ease' }}
          />
        </svg>
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        }}>
          <Text strong style={{ fontSize: 16, lineHeight: 1, color: cfg.color }}>{score}</Text>
          <Text style={{ fontSize: 9, color: cfg.color, opacity: 0.8 }}>分</Text>
        </div>
      </div>

      {/* 等级信息 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <Text style={{ fontSize: 11 }}>{cfg.icon}</Text>
          <Text strong style={{ fontSize: 14, color: cfg.color }}>{cfg.label}</Text>
          <Text style={{ fontSize: 11, color: '#94a3b8' }}>
            {score >= 90 ? '（达到甲级标准）' : score >= 75 ? `（距甲级还差 ${90 - score} 分）` : `（距乙级还差 ${75 - score} 分）`}
          </Text>
        </div>
        {gradeScore.strengths && gradeScore.strengths.length > 0 && (
          <div style={{ fontSize: 11, color: '#374151', lineHeight: 1.5 }}>
            {gradeScore.strengths.slice(0, 2).map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 4 }}>
                <Text style={{ color: '#22c55e', flexShrink: 0 }}>✓</Text>
                <Text style={{ fontSize: 11, color: '#374151' }}>{s}</Text>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}


async function fetchInquirySuggestions(chiefComplaint: string, history: string, initialImpression: string): Promise<Suggestion[]> {
  const data: any = await api.post('/ai/inquiry-suggestions', {
    chief_complaint: chiefComplaint,
    history_present_illness: history,
    initial_impression: initialImpression,
  })
  return (data.suggestions || []).map((s: any, idx: number) => ({
    ...s,
    id: `${Date.now()}-${idx}`,
    options: s.options || [],
    selectedOptions: [],
  }))
}

// Map field_name to Chinese section header in the record
// Supports both English keys (from AI suggestions) and Chinese keys (from QC API)
const FIELD_TO_SECTION: Record<string, string> = {
  chief_complaint: '【主诉】',
  history_present_illness: '【现病史】',
  past_history: '【既往史】',
  allergy_history: '【过敏史】',
  personal_history: '【个人史】',
  physical_exam: '【体格检查】',
  initial_diagnosis: '【初步诊断】',
  initial_impression: '【初步诊断】',
  auxiliary_exam: '【辅助检查】',
  marital_history: '【婚育史】',
  family_history: '【家族史】',
  // Chinese keys returned by QC API
  '主诉': '【主诉】',
  '现病史': '【现病史】',
  '既往史': '【既往史】',
  '过敏史': '【过敏史】',
  '个人史': '【个人史】',
  '个人史/婚育史/月经史/家族史': '【个人史】',
  '婚育史': '【婚育史】',
  '月经史': '【月经史】',
  '家族史': '【家族史】',
  '体格检查': '【体格检查】',
  '初步诊断': '【初步诊断】',
  '入院诊断': '【入院诊断】',
  '诊断': '【入院诊断】',
  '辅助检查': '【辅助检查（入院前）】',
  '辅助检查（入院前）': '【辅助检查（入院前）】',
  '专项评估': '【专项评估】',
}

// Replace a section in the record content, or append if not found
function writeSectionToRecord(content: string, fieldName: string, fixText: string): string {
  const header = FIELD_TO_SECTION[fieldName]
  if (!header || !content) return content ? content + '\n\n' + fixText : fixText

  // Find all section headers (【...】) positions to know section boundaries
  const sectionPattern = /【[^】]+】/g
  const matches: Array<{ index: number; header: string }> = []
  let m: RegExpExecArray | null
  while ((m = sectionPattern.exec(content)) !== null) {
    matches.push({ index: m.index, header: m[0] })
  }

  const targetIdx = matches.findIndex(s => s.header === header)
  if (targetIdx === -1) {
    // Section not found — append
    return content + '\n\n' + header + '\n' + fixText
  }

  const start = matches[targetIdx].index
  const end = targetIdx + 1 < matches.length ? matches[targetIdx + 1].index : content.length
  const newSection = header + '\n' + fixText
  return content.slice(0, start) + newSection + '\n' + content.slice(end).trimStart()
}

export default function AISuggestionPanel() {
  const {
    inquiry, inquirySavedAt,
    qcIssues, qcSummary, qcPass, gradeScore,
    examSuggestions, isExamLoading,
    setExamSuggestions, setExamLoading,
    appendInquiryNote, setInitialImpression,
    recordContent, setRecordContent,
  } = useWorkbenchStore()

  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)

  // Diagnosis state
  const [diagnoses, setDiagnoses] = useState<DiagnosisItem[]>([])
  const [diagnosisLoading, setDiagnosisLoading] = useState(false)
  const [appliedDiagnosis, setAppliedDiagnosis] = useState<string | null>(null)

  // QC fix state
  const [fixTexts, setFixTexts] = useState<Record<number, string>>({})
  const [fixLoading, setFixLoading] = useState<Record<number, boolean>>({})

  // Init fixTexts when qcIssues changes
  useEffect(() => {
    const init: Record<number, string> = {}
    qcIssues.forEach((issue, idx) => { init[idx] = issue.suggestion || '' })
    setFixTexts(init)
  }, [qcIssues])

  // Fetch inquiry suggestions whenever inquiry is saved (inquirySavedAt changes)
  useEffect(() => {
    if (!inquirySavedAt) return
    if (!inquiry.chief_complaint.trim()) { setSuggestions([]); return }
    let cancelled = false
    setLoading(true)
    fetchInquirySuggestions(
      inquiry.chief_complaint,
      inquiry.history_present_illness,
      inquiry.initial_impression,
    ).then((items) => {
      if (!cancelled) setSuggestions(items)
    }).catch(() => {
      if (!cancelled) setSuggestions([])
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [inquirySavedAt])

  // Reset diagnoses when chief_complaint changes
  useEffect(() => {
    setDiagnoses([])
    setAppliedDiagnosis(null)
  }, [inquiry.chief_complaint])

  const handleLoadMore = useCallback(async () => {
    if (!inquiry.chief_complaint.trim()) return
    setLoadingMore(true)
    try {
      const items = await fetchInquirySuggestions(inquiry.chief_complaint, inquiry.history_present_illness, inquiry.initial_impression)
      setSuggestions((prev) => {
        const existingTexts = new Set(prev.map((s) => s.text))
        const newItems = items.filter((s) => !existingTexts.has(s.text))
        if (newItems.length === 0) { message.info('暂无更多新问题'); return prev }
        return [...prev, ...newItems]
      })
    } catch {
      message.error('获取失败，请重试')
    } finally { setLoadingMore(false) }
  }, [inquiry.chief_complaint, inquiry.history_present_illness])

  const handleSelectOption = (suggestionId: string, option: string, questionText: string) => {
    setSuggestions((prev) =>
      prev.map((s) => {
        if (s.id !== suggestionId) return s
        const already = s.selectedOptions.includes(option)
        const newSelected = already
          ? s.selectedOptions.filter((o) => o !== option)
          : [...s.selectedOptions, option]
        if (!already) {
          appendInquiryNote(`${questionText}：${option}`)
          message.success({ content: '已记录到现病史', duration: 1.2 })
        }
        return { ...s, selectedOptions: newSelected }
      })
    )
  }

  // Fetch AI diagnosis suggestions
  const handleGetDiagnosis = async () => {
    if (!inquiry.chief_complaint.trim()) { message.warning('请先填写主诉'); return }
    setDiagnosisLoading(true)
    try {
      const answeredItems = suggestions
        .filter((s) => s.selectedOptions.length > 0)
        .map((s) => ({ question: s.text, answer: s.selectedOptions.join('、') }))

      const data: any = await api.post('/ai/diagnosis-suggestion', {
        chief_complaint: inquiry.chief_complaint,
        history_present_illness: inquiry.history_present_illness,
        inquiry_answers: answeredItems,
        initial_impression: inquiry.initial_impression || '',
      })
      setDiagnoses(data.diagnoses || [])
      if (!data.diagnoses?.length) message.info('暂无诊断建议，请补充更多问诊信息')
    } catch {
      message.error('获取诊断建议失败')
    } finally { setDiagnosisLoading(false) }
  }

  const handleApplyDiagnosis = (name: string) => {
    const existing = inquiry.initial_impression?.trim()
    const newVal = existing ? `${existing}\n${name}` : name
    setInitialImpression(newVal)
    setAppliedDiagnosis(name)
    message.success({ content: `已写入初步印象：${name}`, duration: 2 })
  }

  // Fetch exam suggestions whenever inquiry is saved
  useEffect(() => {
    if (!inquirySavedAt) return
    if (!inquiry.chief_complaint.trim()) { setExamSuggestions([]); return }
    let cancelled = false
    setExamLoading(true)
    api.post('/ai/exam-suggestions', {
      chief_complaint: inquiry.chief_complaint,
      history_present_illness: inquiry.history_present_illness,
      initial_impression: inquiry.initial_impression,
    }).then((data: any) => {
      if (!cancelled) setExamSuggestions(data.suggestions || [])
    }).catch(() => {
      if (!cancelled) setExamSuggestions([])
    }).finally(() => {
      if (!cancelled) setExamLoading(false)
    })
    return () => { cancelled = true }
  }, [inquirySavedAt])

  // QC AI fix handler
  const handleAIFix = async (item: QCIssue, idx: number) => {
    setFixLoading((prev) => ({ ...prev, [idx]: true }))
    try {
      const result: any = await api.post('/ai/qc-fix', {
        field_name: item.field_name,
        issue_description: item.issue_description,
        suggestion: item.suggestion,
        current_record: recordContent,
        chief_complaint: inquiry.chief_complaint,
        history_present_illness: inquiry.history_present_illness,
      })
      setFixTexts((prev) => ({ ...prev, [idx]: result.fix_text }))
    } catch {
      message.error('AI 生成修复失败，请重试')
    } finally {
      setFixLoading((prev) => ({ ...prev, [idx]: false }))
    }
  }

  const unansweredCount = suggestions.filter((s) => s.selectedOptions.length === 0).length
  const highRiskQcCount = qcIssues.filter((i) => i.risk_level === 'high').length
  const answeredCount = suggestions.filter((s) => s.selectedOptions.length > 0).length

  return (
    <Tabs
      defaultActiveKey="inquiry"
      style={{ height: '100%' }}
      tabBarStyle={{ padding: '0 12px', marginBottom: 0 }}
      size="small"
      items={[
        {
          key: 'inquiry',
          label: (
            <Badge count={unansweredCount} size="small" offset={[4, -2]}>
              <span><QuestionCircleOutlined style={{ marginRight: 4 }} />追问建议</span>
            </Badge>
          ),
          children: (
            <div style={{ padding: '0 12px 16px', overflowY: 'auto', height: 'calc(100vh - 130px)' }}>
              {loading ? (
                <div style={{ textAlign: 'center', padding: '40px 0' }}>
                  <Spin size="small" />
                  <div style={{ marginTop: 8, color: '#94a3b8', fontSize: 12 }}>AI 分析中...</div>
                </div>
              ) : suggestions.length === 0 ? (
                <Empty
                  description={<span style={{ fontSize: 13, color: '#94a3b8' }}>{inquiry.chief_complaint.trim() ? '暂无追问建议' : '输入主诉后自动生成追问建议'}</span>}
                  style={{ marginTop: 40 }}
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              ) : (
                <>
                  {suggestions.map((item, idx) => (
                    <div key={item.id} style={{
                      borderBottom: idx < suggestions.length - 1 ? '1px solid #f1f5f9' : 'none',
                      padding: '12px 0',
                    }}>
                      {/* Question header */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6 }}>
                        <Text style={{ fontSize: 11, color: '#94a3b8', fontWeight: 600 }}>Q{idx + 1}</Text>
                        {item.is_red_flag && <Tag color="red" style={{ margin: 0, fontSize: 11, padding: '0 6px' }}>危险信号</Tag>}
                        {!item.is_red_flag && item.priority === 'high' && <Tag color="orange" style={{ margin: 0, fontSize: 11, padding: '0 6px' }}>高优先</Tag>}
                        {item.priority === 'medium' && <Tag color="blue" style={{ margin: 0, fontSize: 11, padding: '0 6px' }}>建议问</Tag>}
                        <Text type="secondary" style={{ fontSize: 11 }}>{item.category}</Text>
                        {item.selectedOptions.length > 1 && (
                          <Tag color="green" style={{ margin: '0 0 0 auto', fontSize: 11, padding: '0 6px' }}>已选{item.selectedOptions.length}项</Tag>
                        )}
                        {item.selectedOptions.length === 1 && <CheckOutlined style={{ color: '#22c55e', marginLeft: 'auto', fontSize: 13 }} />}
                      </div>

                      {/* Question text */}
                      <Text style={{ fontSize: 13, display: 'block', marginBottom: 8, color: '#1e293b', lineHeight: 1.5 }}>
                        {item.text}
                      </Text>

                      {/* Answer options - 支持多选 */}
                      {item.options.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                          {item.options.map((opt) => {
                            const isSelected = item.selectedOptions.includes(opt)
                            return (
                              <Button
                                key={opt}
                                size="small"
                                type={isSelected ? 'primary' : 'default'}
                                onClick={() => handleSelectOption(item.id, opt, item.text)}
                                style={{
                                  fontSize: 12, height: 'auto',
                                  padding: '4px 10px',
                                  borderRadius: 16,
                                  whiteSpace: 'normal',
                                  lineHeight: 1.4,
                                  ...(isSelected ? {
                                    background: '#2563eb',
                                    borderColor: '#2563eb',
                                  } : {
                                    borderColor: '#e2e8f0',
                                    color: '#374151',
                                  }),
                                }}
                              >
                                {isSelected && <CheckOutlined style={{ marginRight: 3, fontSize: 11 }} />}
                                {opt}
                              </Button>
                            )
                          })}
                        </div>
                      )}

                      {/* Recorded answers */}
                      {item.selectedOptions.length > 0 && (
                        <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                          <Text style={{ fontSize: 11, color: '#22c55e' }}>
                            ✓ 已记录：{item.selectedOptions.join('、')}
                          </Text>
                          <Button
                            type="link" size="small"
                            style={{ fontSize: 11, padding: 0, height: 'auto', color: '#94a3b8' }}
                            onClick={() => setSuggestions((prev) =>
                              prev.map((s) => s.id === item.id ? { ...s, selectedOptions: [] } : s)
                            )}
                          >
                            清除
                          </Button>
                        </div>
                      )}
                    </div>
                  ))}

                  {/* Load more */}
                  <div style={{ textAlign: 'center', paddingTop: 8, paddingBottom: 4 }}>
                    <Button icon={<PlusOutlined />} size="small" loading={loadingMore} onClick={handleLoadMore}
                      style={{ fontSize: 12, borderRadius: 16, color: '#64748b' }}>
                      获取更多追问
                    </Button>
                  </div>

                  {/* ── Diagnosis section ── */}
                  <Divider style={{ margin: '16px 0 12px', borderColor: '#e2e8f0' }}>
                    <span style={{ fontSize: 12, color: '#94a3b8', display: 'flex', alignItems: 'center', gap: 4 }}>
                      <BulbOutlined />
                      诊断建议
                    </span>
                  </Divider>

                  {answeredCount > 0 && (
                    <div style={{
                      fontSize: 12, color: '#64748b',
                      background: '#f8fafc', borderRadius: 8, padding: '8px 12px',
                      marginBottom: 10,
                    }}>
                      已回答 <Text strong style={{ color: '#2563eb' }}>{answeredCount}</Text> 个问题，点击下方获取 AI 诊断建议
                    </div>
                  )}

                  <Button
                    block
                    icon={<BulbOutlined />}
                    loading={diagnosisLoading}
                    onClick={handleGetDiagnosis}
                    style={{
                      borderRadius: 8, height: 36, fontSize: 13,
                      background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
                      borderColor: '#86efac', color: '#166534', fontWeight: 500,
                    }}
                  >
                    {diagnosisLoading ? 'AI 分析中...' : 'AI 生成诊断建议'}
                  </Button>

                  {diagnoses.length > 0 && (
                    <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {diagnoses.map((d, idx) => {
                        const conf = CONFIDENCE_CONFIG[d.confidence] || CONFIDENCE_CONFIG.medium
                        const isApplied = appliedDiagnosis === d.name
                        return (
                          <div key={idx} style={{
                            background: isApplied ? '#f0fdf4' : conf.bg,
                            border: `1px solid ${isApplied ? '#86efac' : '#e2e8f0'}`,
                            borderRadius: 10, padding: '12px 14px',
                            transition: 'all 0.2s',
                          }}>
                            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}>
                                <Tag
                                  color={d.confidence === 'high' ? 'success' : d.confidence === 'medium' ? 'warning' : 'default'}
                                  style={{ fontSize: 11, margin: 0, flexShrink: 0 }}
                                >
                                  {conf.label}
                                </Tag>
                                <Text strong style={{ fontSize: 13, color: '#0f172a', lineHeight: 1.3 }}>
                                  {d.name}
                                </Text>
                              </div>
                              <Tooltip title={isApplied ? '已写入初步印象' : '写入初步印象'}>
                                <Button
                                  size="small"
                                  type={isApplied ? 'primary' : 'default'}
                                  icon={isApplied ? <CheckOutlined /> : <ArrowRightOutlined />}
                                  onClick={() => !isApplied && handleApplyDiagnosis(d.name)}
                                  style={{
                                    borderRadius: 16, fontSize: 11, height: 24, flexShrink: 0,
                                    ...(isApplied ? { background: '#22c55e', borderColor: '#22c55e' } : {}),
                                  }}
                                >
                                  {isApplied ? '已写入' : '写入'}
                                </Button>
                              </Tooltip>
                            </div>
                            <Text type="secondary" style={{ fontSize: 12, lineHeight: 1.5, display: 'block' }}>
                              {d.reasoning}
                            </Text>
                            {d.next_steps && (
                              <div style={{ marginTop: 6, padding: '5px 8px', background: 'rgba(37,99,235,0.06)', borderRadius: 6 }}>
                                <Text style={{ fontSize: 11, color: '#2563eb' }}>
                                  建议：{d.next_steps}
                                </Text>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </>
              )}
            </div>
          ),
        },
        {
          key: 'exam',
          label: <span><ExperimentOutlined style={{ marginRight: 4 }} />检查建议</span>,
          children: (
            <div style={{ padding: '8px 12px' }}>
              {isExamLoading ? (
                <div style={{ textAlign: 'center', padding: '40px 0' }}>
                  <Spin size="small" />
                  <div style={{ marginTop: 8, color: '#94a3b8', fontSize: 12 }}>AI 分析中...</div>
                </div>
              ) : examSuggestions.length === 0 ? (
                <Empty
                  description={<span style={{ fontSize: 13, color: '#94a3b8' }}>{inquiry.chief_complaint.trim() ? '暂无检查建议' : '输入问诊信息后自动获取'}</span>}
                  style={{ marginTop: 40 }}
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              ) : (
                <List
                  dataSource={examSuggestions}
                  renderItem={(item: ExamSuggestion, idx) => (
                    <List.Item key={idx} style={{ padding: '10px 0', borderBlockEnd: '1px solid #f1f5f9' }}>
                      <div style={{ width: '100%' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                          <Tag color={EXAM_CATEGORY_COLOR[item.category] || 'default'} style={{ margin: 0, fontSize: 11 }}>
                            {EXAM_CATEGORY_LABEL[item.category] || item.category}
                          </Tag>
                          <Text strong style={{ fontSize: 13 }}>{item.exam_name}</Text>
                        </div>
                        <Text type="secondary" style={{ fontSize: 12, lineHeight: 1.5 }}>{item.reason}</Text>
                      </div>
                    </List.Item>
                  )}
                />
              )}
            </div>
          ),
        },
        {
          key: 'qc',
          label: (
            <Badge count={highRiskQcCount} size="small" offset={[4, -2]}>
              <span><SafetyOutlined style={{ marginRight: 4 }} />质控提示</span>
            </Badge>
          ),
          children: (
            <div style={{ padding: '8px 12px', overflowY: 'auto', height: 'calc(100vh - 130px)' }}>
              {/* 甲级评分展示卡片 */}
              {gradeScore != null && (
                <GradeScoreCard gradeScore={gradeScore} />
              )}
              {qcIssues.length === 0 && qcPass === null ? (
                <Empty
                  description={<span style={{ fontSize: 13, color: '#94a3b8' }}>点击「AI质控」进行病历质量检查</span>}
                  style={{ marginTop: gradeScore ? 16 : 40 }}
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              ) : qcPass === true && qcIssues.length === 0 ? (
                <Alert message="质控通过" description={qcSummary || '病历内容符合规范要求'} type="success" showIcon style={{ marginTop: 8, borderRadius: 8 }} />
              ) : (
                <>
                  {qcSummary && (
                    <Alert
                      message={qcPass ? '质控通过' : '质控发现问题'}
                      description={qcSummary}
                      type={qcPass ? 'success' : 'warning'}
                      showIcon
                      style={{ marginBottom: 12, borderRadius: 8 }}
                    />
                  )}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    {qcIssues.map((item: QCIssue, idx) => (
                      <div key={idx} style={{
                        background: '#fff',
                        border: '1px solid #e2e8f0',
                        borderRadius: 10,
                        padding: '12px 14px',
                        boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                      }}>
                        {/* Risk tag + issue type + field name */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
                          <Tag color={QC_RISK_COLOR[item.risk_level]} style={{ margin: 0, fontSize: 11 }}>
                            {QC_RISK_LABEL[item.risk_level] || item.risk_level}
                          </Tag>
                          {item.issue_type && (
                            <Tag color={QC_TYPE_COLOR[item.issue_type] || 'default'} style={{ margin: 0, fontSize: 11 }}>
                              {QC_TYPE_LABEL[item.issue_type] || item.issue_type}
                            </Tag>
                          )}
                          {item.field_name && (
                            <Text type="secondary" style={{ fontSize: 11 }}>{item.field_name}</Text>
                          )}
                          {item.score_impact && (
                            <Text style={{ fontSize: 10, color: '#ef4444', marginLeft: 'auto' }}>{item.score_impact}</Text>
                          )}
                        </div>

                        {/* Issue description */}
                        <Text style={{ fontSize: 13, lineHeight: 1.5, display: 'block', marginBottom: 8, color: '#1e293b' }}>
                          {item.issue_description}
                        </Text>

                        {/* Editable fix textarea */}
                        <Input.TextArea
                          value={fixTexts[idx] ?? ''}
                          onChange={(e) => setFixTexts((prev) => ({ ...prev, [idx]: e.target.value }))}
                          rows={3}
                          style={{ fontSize: 13, borderRadius: 6, marginBottom: 8, resize: 'vertical' }}
                          placeholder="修复建议（可编辑）..."
                        />

                        {/* Action buttons */}
                        <div style={{ display: 'flex', gap: 8 }}>
                          <Button
                            size="small"
                            icon={<BulbOutlined />}
                            loading={fixLoading[idx] || false}
                            onClick={() => handleAIFix(item, idx)}
                            style={{ fontSize: 12, borderRadius: 6 }}
                          >
                            AI 生成修复
                          </Button>
                          <Button
                            size="small"
                            type="primary"
                            icon={<EditOutlined />}
                            onClick={() => {
                              const fix = fixTexts[idx] || ''
                              setRecordContent(writeSectionToRecord(recordContent, item.field_name, fix))
                              message.success('已写入病历')
                            }}
                            style={{ fontSize: 12, borderRadius: 6 }}
                          >
                            写入病历
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          ),
        },
        {
          key: 'lab',
          label: <span><FileTextOutlined style={{ marginRight: 4 }} />检验报告</span>,
          children: <LabReportTab />,
        },
      ]}
    />
  )
}
