/**
 * 问诊建议标签页（components/workbench/InquirySuggestionTab.tsx）
 *
 * 包含两部分：
 *   1. 追问建议：AI 根据主诉/现病史生成需要追问患者的问题，医生点选答案后
 *      同步写入病历【追问补充】章节。
 *   2. 诊断建议：基于追问答案生成鉴别诊断列表，医生点击「写入」后写入
 *      病历【初步诊断】章节。
 *
 * 锁定模式（病历已生成后）：
 *   - 追问选项按钮变为只读（不可选择）
 *   - 顶部显示只读提示条
 *   - 「获取更多追问」和「重新生成诊断建议」按钮仍可使用，供医生补充分析
 *
 * 状态持久化：
 *   inquirySuggestions / diagnosisSuggestions / appliedDiagnosis 均存于
 *   workbenchStore 并通过 localStorage 持久化，刷新后不丢失。
 */
import { useState, useCallback, useEffect } from 'react'
import { Button, Typography, Empty, Spin, Tag, message, Divider, Tooltip } from 'antd'
import {
  QuestionCircleOutlined,
  PlusOutlined,
  CheckOutlined,
  BulbOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons'
import {
  useWorkbenchStore,
  InquirySuggestion as Suggestion,
  DiagnosisItem,
} from '@/store/workbenchStore'
import { writeSectionToRecord } from './qcFieldMaps'
import api from '@/services/api'

const { Text } = Typography

/** 诊断置信度显示配置 */
const CONFIDENCE_CONFIG: Record<string, { color: string; label: string; bg: string }> = {
  high: { color: '#059669', label: '高度符合', bg: '#f0fdf4' },
  medium: { color: '#d97706', label: '可能符合', bg: '#fffbeb' },
  low: { color: '#64748b', label: '待排除', bg: '#f8fafc' },
}

/**
 * 调用后端接口获取追问建议列表
 */
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

/**
 * 根据已选追问答案构建【追问补充】章节文本
 */
function buildSupplementSection(items: Suggestion[]): string {
  const lines = items
    .filter(s => s.selectedOptions.length > 0)
    .map(s => `${s.text.replace(/[？?]$/, '')}：${s.selectedOptions.join('、')}`)
  if (lines.length === 0) return ''
  return '【追问补充】\n' + lines.join('\n')
}

/**
 * 将【追问补充】章节替换或插入到病历文本中
 */
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
    diagnosisSuggestions,
    setDiagnosisSuggestions,
    appliedDiagnosis,
    setAppliedDiagnosis,
    isPolishing,
    qcRunId,
  } = useWorkbenchStore()

  // 润色期间 recordContent 会短暂清空，isPolishing 防止提示条闪烁消失
  const isInputLocked = !!recordContent.trim() || isPolishing
  // 质控点击后视为医生已确认问诊内容，追问选项全部变灰禁用
  const isQCDone = !!qcRunId

  const suggestions = inquirySuggestions
  const setSuggestions = (v: Suggestion[] | ((prev: Suggestion[]) => Suggestion[])) =>
    setInquirySuggestions(typeof v === 'function' ? v(inquirySuggestions) : v)

  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [diagnosisLoading, setDiagnosisLoading] = useState(false)

  /** 主诉变化时重置诊断建议（病历未生成时才重置，锁定后保留） */
  useEffect(() => {
    if (!isInputLocked) {
      setDiagnosisSuggestions([])
      setAppliedDiagnosis(null)
    }
  }, [inquiry.chief_complaint])

  /** 生成追问建议（首次加载） */
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

  /** 获取更多追问（追加到现有列表，去重） */
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

  /**
   * 点选追问答案：更新选中状态并同步写入病历【追问补充】章节
   * 锁定模式下同样可点选，写入病历右侧【追问补充】章节
   */
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

  /** 调用 AI 生成诊断建议 */
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
      setDiagnosisSuggestions((data.diagnoses || []) as DiagnosisItem[])
      if (!data.diagnoses?.length) message.info('暂无诊断建议，请补充更多问诊信息')
    } catch {
      message.error('获取诊断建议失败')
    } finally {
      setDiagnosisLoading(false)
    }
  }

  /**
   * 点击「写入」：将诊断名称写入病历【初步诊断】章节。
   * 再次点击同一诊断则取消写入。
   */
  const handleApplyDiagnosis = (name: string) => {
    if (appliedDiagnosis === name) {
      setInitialImpression('')
      setRecordContent(writeSectionToRecord(recordContent, 'initial_impression', ''))
      setAppliedDiagnosis(null)
    } else {
      setInitialImpression(name)
      setRecordContent(writeSectionToRecord(recordContent, 'initial_impression', name))
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
      {/* 病历已生成后的提示：说明选择答案会写入病历章节 */}
      {isInputLocked && (
        <div
          style={{
            background: '#eff6ff',
            border: '1px solid #bfdbfe',
            borderRadius: 6,
            padding: '6px 10px',
            marginBottom: 10,
            fontSize: 12,
            color: '#1e40af',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <span>💡</span>
          <span>病历已生成。选择追问答案将追加至病历【追问补充】章节。</span>
        </div>
      )}

      {suggestions.map((item, idx) => {
        /** 既往信息类目已在问诊中填写，或质控已完成，视觉上降调处理 */
        const isPastHistory = item.category === '既往信息'
        const isDimmed = isPastHistory || isQCDone
        return (
          <div
            key={item.id}
            style={{
              borderBottom: idx < suggestions.length - 1 ? '1px solid #f1f5f9' : 'none',
              padding: '12px 0',
              opacity: isDimmed ? 0.45 : 1,
              pointerEvents: isQCDone ? 'none' : 'auto',
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
                      // 选项按钮始终可点：选中后写入病历【追问补充】章节，与输入框锁定无关
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
        )
      })}

      {/* 获取更多追问按钮：锁定模式下仍可使用，供医生补充分析 */}
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

      {/* 诊断建议按钮：锁定后改为「重新生成」文案 */}
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
        {diagnosisLoading
          ? 'AI 分析中...'
          : isInputLocked && diagnosisSuggestions.length > 0
            ? '重新生成诊断建议'
            : 'AI 生成诊断建议'}
      </Button>

      {diagnosisSuggestions.length > 0 && (
        <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {diagnosisSuggestions.map((d, idx) => {
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
                  {/* 写入按钮：锁定/未锁定均可使用（写入病历右侧） */}
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
