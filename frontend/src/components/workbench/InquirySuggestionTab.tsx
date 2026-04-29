/**
 * 问诊建议标签页（components/workbench/InquirySuggestionTab.tsx）
 * 子组件：InquirySuggestionItem（追问条目）、DiagnosisSuggestionList（诊断建议）。
 */
import { useState, useCallback, useEffect } from 'react'
import { Button, Typography, Empty, Spin, message, Divider } from 'antd'
import { QuestionCircleOutlined, PlusOutlined, BulbOutlined } from '@ant-design/icons'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { useAISuggestionStore } from '@/store/aiSuggestionStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { InquirySuggestion as Suggestion, DiagnosisItem } from '@/store/types'
import { writeSectionToRecord } from './qcFieldMaps'
import InquirySuggestionItem from './InquirySuggestionItem'
import DiagnosisSuggestionList from './DiagnosisSuggestionList'
import api from '@/services/api'

const { Text } = Typography

async function fetchInquirySuggestions(
  chiefComplaint: string,
  history: string,
  initialImpression: string,
  encounterId?: string | null
): Promise<Suggestion[]> {
  const data: any = await api.post('/ai/inquiry-suggestions', {
    chief_complaint: chiefComplaint,
    history_present_illness: history,
    initial_impression: initialImpression,
    encounter_id: encounterId || undefined,
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
  if (!lines.length) return ''
  return '【追问补充】\n' + lines.join('\n')
}

function updateRecordWithSupplement(content: string, newSection: string): string {
  const marker = '【追问补充】'
  const idx = content.indexOf(marker)
  if (newSection === '') return idx === -1 ? content : content.slice(0, idx).trimEnd()
  if (idx === -1) return content ? content.trimEnd() + '\n\n' + newSection : newSection
  return content.slice(0, idx).trimEnd() + '\n\n' + newSection
}

export default function InquirySuggestionTab() {
  const { inquiry, setInitialImpression } = useInquiryStore()
  const { recordContent, setRecordContent, isPolishing } = useRecordStore()
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const {
    inquirySuggestions,
    setInquirySuggestions,
    diagnosisSuggestions,
    setDiagnosisSuggestions,
    appliedDiagnosis,
    setAppliedDiagnosis,
  } = useAISuggestionStore()

  const isInputLocked = !!recordContent.trim() || isPolishing
  const suggestions = inquirySuggestions
  // 函数式更新从 store 读最新值，避免异步回调里拿到 stale closure
  const setSuggestions = (v: Suggestion[] | ((prev: Suggestion[]) => Suggestion[])) =>
    setInquirySuggestions(
      typeof v === 'function' ? v(useAISuggestionStore.getState().inquirySuggestions) : v
    )

  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [diagnosisLoading, setDiagnosisLoading] = useState(false)

  useEffect(() => {
    if (!isInputLocked) {
      setDiagnosisSuggestions([])
      setAppliedDiagnosis(null)
    }
  }, [inquiry.chief_complaint])

  const handleLoadSuggestions = useCallback(async () => {
    if (!inquiry.chief_complaint.trim()) {
      message.warning('请先填写主诉')
      return
    }
    setLoading(true)
    try {
      setSuggestions(
        await fetchInquirySuggestions(
          inquiry.chief_complaint,
          inquiry.history_present_illness,
          inquiry.initial_impression,
          currentEncounterId
        )
      )
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
  }, [inquiry.chief_complaint, inquiry.history_present_illness, inquiry.initial_impression])

  const handleSelectOption = (suggestionId: string, option: string) => {
    const s = suggestions.find(s => s.id === suggestionId)
    if (!s) return
    const newSelected = s.selectedOptions.includes(option)
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
        encounter_id: currentEncounterId || undefined,
      })
      setDiagnosisSuggestions((data.diagnoses || []) as DiagnosisItem[])
      if (!data.diagnoses?.length) message.info('暂无诊断建议，请补充更多问诊信息')
    } catch {
      message.error('获取诊断建议失败')
    } finally {
      setDiagnosisLoading(false)
    }
  }

  const handleApplyDiagnosis = (name: string) => {
    // 同步更新病历两处：【初步诊断】章节 + 【诊断】里的西医诊断行（润色生成）
    const syncRecord = (content: string, value: string) => {
      let updated = writeSectionToRecord(content, 'initial_impression', value)
      // 替换润色生成的「西医诊断：XXX」行，保证两处一致
      if (updated.includes('西医诊断：')) {
        const replacement = value ? `西医诊断：${value}` : '西医诊断：[未填写，需补充]'
        updated = updated.replace(/西医诊断：[^\n]*/g, replacement)
      }
      return updated
    }

    if (appliedDiagnosis === name) {
      setInitialImpression('')
      setRecordContent(syncRecord(recordContent, ''))
      setAppliedDiagnosis(null)
    } else {
      setInitialImpression(name)
      setRecordContent(syncRecord(recordContent, name))
      setAppliedDiagnosis(name)
      message.success({ content: `已写入诊断：${name}`, duration: 2 })
    }
  }

  const answeredCount = suggestions.filter(s => s.selectedOptions.length > 0).length

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '40px 0' }}>
        <Spin size="small" />
        <div style={{ marginTop: 8, color: 'var(--text-4)', fontSize: 12 }}>AI 分析中...</div>
      </div>
    )
  }

  if (suggestions.length === 0) {
    return (
      <div style={{ textAlign: 'center', marginTop: 40 }}>
        <Empty
          description={
            <span style={{ fontSize: 13, color: 'var(--text-4)' }}>
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
          <Text style={{ fontSize: 12, color: '#1e40af' }}>
            病历已生成。选择追问答案将追加至病历【追问补充】章节。
          </Text>
        </div>
      )}

      {suggestions.map((item, idx) => (
        <InquirySuggestionItem
          key={item.id}
          item={item}
          idx={idx}
          total={suggestions.length}
          onSelectOption={handleSelectOption}
        />
      ))}

      <div style={{ textAlign: 'center', paddingTop: 8, paddingBottom: 4 }}>
        <Button
          icon={<PlusOutlined />}
          size="small"
          loading={loadingMore}
          onClick={handleLoadMore}
          style={{ fontSize: 12, borderRadius: 16, color: 'var(--text-3)' }}
        >
          获取更多追问
        </Button>
      </div>

      <Divider style={{ margin: '16px 0 12px', borderColor: 'var(--border)' }}>
        <span
          style={{
            fontSize: 12,
            color: 'var(--text-4)',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          <BulbOutlined /> 诊断建议
        </span>
      </Divider>

      <DiagnosisSuggestionList
        diagnosisSuggestions={diagnosisSuggestions}
        appliedDiagnosis={appliedDiagnosis}
        diagnosisLoading={diagnosisLoading}
        isInputLocked={isInputLocked}
        answeredCount={answeredCount}
        onGetDiagnosis={handleGetDiagnosis}
        onApplyDiagnosis={handleApplyDiagnosis}
      />
    </>
  )
}
