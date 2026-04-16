import { useState, useCallback, useEffect } from 'react'
import { Button, Typography, Empty, Spin, Tag, message, Divider, Tooltip } from 'antd'
import {
  QuestionCircleOutlined,
  PlusOutlined,
  CheckOutlined,
  BulbOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons'
import { useWorkbenchStore, InquirySuggestion as Suggestion } from '@/store/workbenchStore'
import api from '@/services/api'

const { Text } = Typography

interface DiagnosisItem {
  name: string
  confidence: 'high' | 'medium' | 'low'
  reasoning: string
  next_steps: string
}

const CONFIDENCE_CONFIG: Record<string, { color: string; label: string; bg: string }> = {
  high: { color: '#059669', label: '高度符合', bg: '#f0fdf4' },
  medium: { color: '#d97706', label: '可能符合', bg: '#fffbeb' },
  low: { color: '#64748b', label: '待排除', bg: '#f8fafc' },
}

async function fetchInquirySuggestions(
  chiefComplaint: string,
  history: string,
  initialImpression: string
): Promise<Suggestion[]> {
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

function buildSupplementSection(items: Suggestion[]): string {
  const lines = items
    .filter(s => s.selectedOptions.length > 0)
    .map(s => `${s.text.replace(/[？?]$/, '')}：${s.selectedOptions.join('、')}`)
  if (lines.length === 0) return ''
  return '【追问补充】\n' + lines.join('\n')
}

function updateRecordWithSupplement(content: string, newSection: string): string {
  const marker = '【追问补充】'
  const idx = content.indexOf(marker)
  if (newSection === '') {
    if (idx === -1) return content
    return content.slice(0, idx).trimEnd()
  }
  if (idx === -1) {
    return content ? content.trimEnd() + '\n\n' + newSection : newSection
  }
  return content.slice(0, idx).trimEnd() + '\n\n' + newSection
}

export default function InquirySuggestionTab() {
  const {
    inquiry,
    setInitialImpression,
    recordContent,
    setRecordContent,
    inquirySuggestions,
    setInquirySuggestions,
  } = useWorkbenchStore()

  const suggestions = inquirySuggestions
  const setSuggestions = (v: Suggestion[] | ((prev: Suggestion[]) => Suggestion[])) =>
    setInquirySuggestions(typeof v === 'function' ? v(inquirySuggestions) : v)

  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [diagnoses, setDiagnoses] = useState<DiagnosisItem[]>([])
  const [diagnosisLoading, setDiagnosisLoading] = useState(false)
  const [appliedDiagnosis, setAppliedDiagnosis] = useState<string | null>(null)

  useEffect(() => {
    setDiagnoses([])
    setAppliedDiagnosis(null)
  }, [inquiry.chief_complaint])

  const handleLoadSuggestions = useCallback(async () => {
    if (!inquiry.chief_complaint.trim()) {
      message.warning('请先填写主诉')
      return
    }
    setLoading(true)
    try {
      const items = await fetchInquirySuggestions(
        inquiry.chief_complaint,
        inquiry.history_present_illness,
        inquiry.initial_impression
      )
      setSuggestions(items)
    } catch {
      setSuggestions([])
    } finally {
      setLoading(false)
    }
  }, [inquiry.chief_complaint, inquiry.history_present_illness, inquiry.initial_impression])

  const handleLoadMore = useCallback(async () => {
    if (!inquiry.chief_complaint.trim()) return
    setLoadingMore(true)
    try {
      const items = await fetchInquirySuggestions(
        inquiry.chief_complaint,
        inquiry.history_present_illness,
        inquiry.initial_impression
      )
      setSuggestions(prev => {
        const existing = new Set(prev.map(s => s.text))
        const newItems = items.filter(s => !existing.has(s.text))
        if (!newItems.length) {
          message.info('暂无更多新问题')
          return prev
        }
        return [...prev, ...newItems]
      })
    } catch {
      message.error('获取失败，请重试')
    } finally {
      setLoadingMore(false)
    }
  }, [inquiry.chief_complaint, inquiry.history_present_illness])

  const handleSelectOption = (suggestionId: string, option: string) => {
    const s = suggestions.find(s => s.id === suggestionId)
    if (!s) return
    const already = s.selectedOptions.includes(option)
    const newSelected = already
      ? s.selectedOptions.filter(o => o !== option)
      : [...s.selectedOptions, option]
    const updated = suggestions.map(item =>
      item.id === suggestionId ? { ...item, selectedOptions: newSelected } : item
    )
    setSuggestions(updated)
    setRecordContent(updateRecordWithSupplement(recordContent, buildSupplementSection(updated)))
  }

  const handleGetDiagnosis = async () => {
    if (!inquiry.chief_complaint.trim()) {
      message.warning('请先填写主诉')
      return
    }
    setDiagnosisLoading(true)
    try {
      const answeredItems = suggestions
        .filter(s => s.selectedOptions.length > 0)
        .map(s => ({ question: s.text, answer: s.selectedOptions.join('、') }))
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
    } finally {
      setDiagnosisLoading(false)
    }
  }

  const handleApplyDiagnosis = (name: string) => {
    if (appliedDiagnosis === name) {
      setInitialImpression('')
      setAppliedDiagnosis(null)
    } else {
      setInitialImpression(name)
      setAppliedDiagnosis(name)
      message.success({ content: `已写入初步诊断：${name}`, duration: 2 })
    }
  }

  const answeredCount = suggestions.filter(s => s.selectedOptions.length > 0).length

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '40px 0' }}>
        <Spin size="small" />
        <div style={{ marginTop: 8, color: '#94a3b8', fontSize: 12 }}>AI 分析中...</div>
      </div>
    )
  }

  if (suggestions.length === 0) {
    return (
      <div style={{ textAlign: 'center', marginTop: 40 }}>
        <Empty
          description={
            <span style={{ fontSize: 13, color: '#94a3b8' }}>
              保存问诊信息后，点击下方按钮生成追问建议
            </span>
          }
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
        <Button
          type="primary"
          icon={<QuestionCircleOutlined />}
          onClick={handleLoadSuggestions}
          disabled={!inquiry.chief_complaint.trim()}
          style={{ marginTop: 12, borderRadius: 8 }}
        >
          生成追问建议
        </Button>
      </div>
    )
  }

  return (
    <>
      {suggestions.map((item, idx) => (
        <div
          key={item.id}
          style={{
            borderBottom: idx < suggestions.length - 1 ? '1px solid #f1f5f9' : 'none',
            padding: '12px 0',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6 }}>
            <Text style={{ fontSize: 11, color: '#94a3b8', fontWeight: 600 }}>Q{idx + 1}</Text>
            {item.is_red_flag && (
              <Tag color="red" style={{ margin: 0, fontSize: 11, padding: '0 6px' }}>
                危险信号
              </Tag>
            )}
            {!item.is_red_flag && item.priority === 'high' && (
              <Tag color="orange" style={{ margin: 0, fontSize: 11, padding: '0 6px' }}>
                高优先
              </Tag>
            )}
            {item.priority === 'medium' && (
              <Tag color="blue" style={{ margin: 0, fontSize: 11, padding: '0 6px' }}>
                建议问
              </Tag>
            )}
            <Text type="secondary" style={{ fontSize: 11 }}>
              {item.category}
            </Text>
            {item.selectedOptions.length > 1 && (
              <Tag color="green" style={{ margin: '0 0 0 auto', fontSize: 11, padding: '0 6px' }}>
                已选{item.selectedOptions.length}项
              </Tag>
            )}
            {item.selectedOptions.length === 1 && (
              <CheckOutlined style={{ color: '#22c55e', marginLeft: 'auto', fontSize: 13 }} />
            )}
          </div>
          <Text
            style={{
              fontSize: 13,
              display: 'block',
              marginBottom: 8,
              color: '#1e293b',
              lineHeight: 1.5,
            }}
          >
            {item.text}
          </Text>
          {item.options.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {item.options.map(opt => {
                const isSelected = item.selectedOptions.includes(opt)
                return (
                  <Button
                    key={opt}
                    size="small"
                    type={isSelected ? 'primary' : 'default'}
                    onClick={() => handleSelectOption(item.id, opt)}
                    style={{
                      fontSize: 12,
                      height: 'auto',
                      padding: '4px 10px',
                      borderRadius: 16,
                      whiteSpace: 'normal',
                      lineHeight: 1.4,
                      ...(isSelected
                        ? { background: '#2563eb', borderColor: '#2563eb' }
                        : { borderColor: '#e2e8f0', color: '#374151' }),
                    }}
                  >
                    {isSelected && <CheckOutlined style={{ marginRight: 3, fontSize: 11 }} />}
                    {opt}
                  </Button>
                )
              })}
            </div>
          )}
          {item.selectedOptions.length > 0 && (
            <div style={{ marginTop: 6 }}>
              <Text style={{ fontSize: 11, color: '#22c55e' }}>
                ✓ 已选：{item.selectedOptions.join('、')}（再次点击可取消）
              </Text>
            </div>
          )}
        </div>
      ))}

      <div style={{ textAlign: 'center', paddingTop: 8, paddingBottom: 4 }}>
        <Button
          icon={<PlusOutlined />}
          size="small"
          loading={loadingMore}
          onClick={handleLoadMore}
          style={{ fontSize: 12, borderRadius: 16, color: '#64748b' }}
        >
          获取更多追问
        </Button>
      </div>

      <Divider style={{ margin: '16px 0 12px', borderColor: '#e2e8f0' }}>
        <span
          style={{ fontSize: 12, color: '#94a3b8', display: 'flex', alignItems: 'center', gap: 4 }}
        >
          <BulbOutlined />
          诊断建议
        </span>
      </Divider>

      {answeredCount > 0 && (
        <div
          style={{
            fontSize: 12,
            color: '#64748b',
            background: '#f8fafc',
            borderRadius: 8,
            padding: '8px 12px',
            marginBottom: 10,
          }}
        >
          已回答{' '}
          <Text strong style={{ color: '#2563eb' }}>
            {answeredCount}
          </Text>{' '}
          个问题，已同步至病历【追问补充】区块
        </div>
      )}

      <Button
        block
        icon={<BulbOutlined />}
        loading={diagnosisLoading}
        onClick={handleGetDiagnosis}
        style={{
          borderRadius: 8,
          height: 36,
          fontSize: 13,
          background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
          borderColor: '#86efac',
          color: '#166534',
          fontWeight: 500,
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
              <div
                key={idx}
                style={{
                  background: isApplied ? '#f0fdf4' : conf.bg,
                  border: `1px solid ${isApplied ? '#86efac' : '#e2e8f0'}`,
                  borderRadius: 10,
                  padding: '12px 14px',
                  transition: 'all 0.2s',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    justifyContent: 'space-between',
                    gap: 8,
                    marginBottom: 6,
                  }}
                >
                  <div
                    style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}
                  >
                    <Tag
                      color={
                        d.confidence === 'high'
                          ? 'success'
                          : d.confidence === 'medium'
                            ? 'warning'
                            : 'default'
                      }
                      style={{ fontSize: 11, margin: 0, flexShrink: 0 }}
                    >
                      {conf.label}
                    </Tag>
                    <Text strong style={{ fontSize: 13, color: '#0f172a', lineHeight: 1.3 }}>
                      {d.name}
                    </Text>
                  </div>
                  <Tooltip title={isApplied ? '点击取消' : '写入初步诊断'}>
                    <Button
                      size="small"
                      type={isApplied ? 'primary' : 'default'}
                      icon={isApplied ? <CheckOutlined /> : <ArrowRightOutlined />}
                      onClick={() => handleApplyDiagnosis(d.name)}
                      style={{
                        borderRadius: 16,
                        fontSize: 11,
                        height: 24,
                        flexShrink: 0,
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
                  <div
                    style={{
                      marginTop: 6,
                      padding: '5px 8px',
                      background: 'rgba(37,99,235,0.06)',
                      borderRadius: 6,
                    }}
                  >
                    <Text style={{ fontSize: 11, color: '#2563eb' }}>建议：{d.next_steps}</Text>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}
