import { useState, useEffect } from 'react'
import { Button, Typography, Empty, Alert, Tag, message, Input } from 'antd'
import { BulbOutlined, EditOutlined } from '@ant-design/icons'
import { useWorkbenchStore, QCIssue } from '@/store/workbenchStore'
import { FIELD_NAME_LABEL, FIELD_TO_INQUIRY_KEY, writeSectionToRecord } from './qcFieldMaps'
import GradeScoreCard from './GradeScoreCard'
import api from '@/services/api'

const { Text } = Typography

const QC_RISK_COLOR: Record<string, string> = { high: 'red', medium: 'orange', low: 'default' }
const QC_RISK_LABEL: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险' }
const QC_TYPE_COLOR: Record<string, string> = {
  completeness: 'blue',
  insurance: 'purple',
  format: 'cyan',
  logic: 'gold',
  normality: 'geekblue',
}
const QC_TYPE_LABEL: Record<string, string> = {
  completeness: '完整性',
  insurance: '医保风险',
  format: '格式',
  logic: '逻辑',
  normality: '规范性',
}

export default function QCIssuePanel() {
  const {
    qcIssues,
    qcSummary,
    qcPass,
    gradeScore,
    recordContent,
    setRecordContent,
    inquiry,
    setInquiry,
  } = useWorkbenchStore()

  const [fixTexts, setFixTexts] = useState<Record<number, string>>({})
  const [fixLoading, setFixLoading] = useState<Record<number, boolean>>({})
  const [writtenSet, setWrittenSet] = useState<Set<number>>(new Set())

  useEffect(() => {
    setFixTexts({})
    setWrittenSet(new Set())
  }, [qcIssues])

  const handleAIFix = async (item: QCIssue, idx: number) => {
    setFixLoading(prev => ({ ...prev, [idx]: true }))
    try {
      const result: any = await api.post('/ai/qc-fix', {
        field_name: item.field_name,
        issue_description: item.issue_description,
        suggestion: item.suggestion,
        current_record: recordContent,
        chief_complaint: inquiry.chief_complaint,
        history_present_illness: inquiry.history_present_illness,
      })
      setFixTexts(prev => ({ ...prev, [idx]: result.fix_text }))
    } catch {
      message.error('AI 生成修复失败，请重试')
    } finally {
      setFixLoading(prev => ({ ...prev, [idx]: false }))
    }
  }

  const handleWriteToRecord = (item: QCIssue, idx: number) => {
    if (writtenSet.has(idx)) {
      // 取消写入：还原该字段
      setRecordContent(writeSectionToRecord(recordContent, item.field_name, ''))
      const inquiryKey = FIELD_TO_INQUIRY_KEY[item.field_name]
      if (inquiryKey) setInquiry({ ...inquiry, [inquiryKey]: '' })
      setWrittenSet(prev => {
        const s = new Set(prev)
        s.delete(idx)
        return s
      })
      message.info('已取消写入')
    } else {
      const fix = fixTexts[idx]?.trim() || ''
      if (!fix) return
      setRecordContent(writeSectionToRecord(recordContent, item.field_name, fix))
      const inquiryKey = FIELD_TO_INQUIRY_KEY[item.field_name]
      if (inquiryKey) setInquiry({ ...inquiry, [inquiryKey]: fix })
      setWrittenSet(prev => new Set(prev).add(idx))
      message.success('已写入病历')
    }
  }

  const renderIssue = (item: QCIssue, idx: number) => (
    <div
      key={idx}
      style={{
        background: '#fff',
        border: `1px solid ${item.source === 'rule' || item.source == null ? '#fca5a5' : '#e2e8f0'}`,
        borderRadius: 10,
        padding: '12px 14px',
        boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
      }}
    >
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}
      >
        {item.source === 'rule' || item.source == null ? (
          <Tag color="red" style={{ margin: 0, fontSize: 11, fontWeight: 600 }}>
            必须修复
          </Tag>
        ) : (
          <Tag color="orange" style={{ margin: 0, fontSize: 11 }}>
            质量建议
          </Tag>
        )}
        <Tag color={QC_RISK_COLOR[item.risk_level]} style={{ margin: 0, fontSize: 11 }}>
          {QC_RISK_LABEL[item.risk_level] || item.risk_level}
        </Tag>
        {item.issue_type && (
          <Tag
            color={QC_TYPE_COLOR[item.issue_type] || 'default'}
            style={{ margin: 0, fontSize: 11 }}
          >
            {QC_TYPE_LABEL[item.issue_type] || item.issue_type}
          </Tag>
        )}
        {item.field_name && (
          <Text type="secondary" style={{ fontSize: 11 }}>
            {FIELD_NAME_LABEL[item.field_name] || item.field_name}
          </Text>
        )}
        {item.score_impact && item.source !== 'llm' && (
          <Text style={{ fontSize: 10, color: '#ef4444', marginLeft: 'auto' }}>
            {item.score_impact}
          </Text>
        )}
      </div>
      <Text
        style={{
          fontSize: 13,
          lineHeight: 1.5,
          display: 'block',
          marginBottom: 8,
          color: '#1e293b',
        }}
      >
        {item.issue_description}
      </Text>
      {item.source === 'llm' && (!item.field_name || item.field_name === 'content') ? (
        <div
          style={{
            marginTop: 4,
            padding: '6px 10px',
            background: '#fef9c3',
            borderRadius: 6,
            fontSize: 12,
            color: '#92400e',
          }}
        >
          💡 此为格式/全文问题，建议点击上方「AI 润色」自动修复
        </div>
      ) : (
        <>
          <Input.TextArea
            value={fixTexts[idx] ?? ''}
            onChange={e => setFixTexts(prev => ({ ...prev, [idx]: e.target.value }))}
            rows={3}
            style={{ fontSize: 13, borderRadius: 6, marginBottom: 8, resize: 'vertical' }}
            placeholder="修复建议（可编辑）..."
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <Button
              size="small"
              icon={<BulbOutlined />}
              loading={fixLoading[idx] || false}
              onClick={() => handleAIFix(item, idx)}
              style={{ fontSize: 12, borderRadius: 6 }}
            >
              逐条修复
            </Button>
            <Button
              size="small"
              type={writtenSet.has(idx) ? 'primary' : 'default'}
              icon={<EditOutlined />}
              disabled={!writtenSet.has(idx) && !fixTexts[idx]?.trim()}
              onClick={() => handleWriteToRecord(item, idx)}
              style={{
                fontSize: 12,
                borderRadius: 6,
                ...(writtenSet.has(idx) ? { background: '#22c55e', borderColor: '#22c55e' } : {}),
              }}
            >
              {writtenSet.has(idx) ? '已写入' : '写入病历'}
            </Button>
          </div>
        </>
      )}
    </div>
  )

  if (qcIssues.length === 0 && qcPass === null) {
    return (
      <>
        {gradeScore != null && <GradeScoreCard gradeScore={gradeScore} />}
        <Empty
          description={
            <span style={{ fontSize: 13, color: '#94a3b8' }}>点击「AI质控」进行病历质量检查</span>
          }
          style={{ marginTop: gradeScore ? 16 : 40 }}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      </>
    )
  }

  if (qcPass === true && qcIssues.length === 0) {
    return (
      <>
        {gradeScore != null && <GradeScoreCard gradeScore={gradeScore} />}
        <Alert
          message="质控通过"
          description={qcSummary || '病历内容符合规范要求'}
          type="success"
          showIcon
          style={{ marginTop: 8, borderRadius: 8 }}
        />
      </>
    )
  }

  const blockingIssues = qcIssues.filter(i => i.source === 'rule' || i.source == null)
  const suggestionIssues = qcIssues.filter(i => i.source === 'llm')

  return (
    <>
      {gradeScore != null && <GradeScoreCard gradeScore={gradeScore} />}
      {qcSummary && (
        <Alert
          message={qcPass ? '结构检查通过，可出具病历' : '存在结构性问题，需修复后才可出具'}
          description={qcSummary}
          type={qcPass ? 'success' : 'error'}
          showIcon
          style={{ marginBottom: 12, borderRadius: 8 }}
        />
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {blockingIssues.length > 0 && (
          <>
            <Text style={{ fontSize: 11, color: '#dc2626', fontWeight: 600 }}>
              ▍必须修复（共 {blockingIssues.length} 项，修复后重新质控即可出具病历）
            </Text>
            {blockingIssues.map(item => renderIssue(item, qcIssues.indexOf(item)))}
          </>
        )}
        {suggestionIssues.length > 0 && (
          <>
            <Text
              style={{
                fontSize: 11,
                color: '#92400e',
                fontWeight: 600,
                marginTop: blockingIssues.length > 0 ? 4 : 0,
              }}
            >
              ▍质量建议（共 {suggestionIssues.length} 项，不影响出具，但建议改进）
            </Text>
            {suggestionIssues.map(item => renderIssue(item, qcIssues.indexOf(item)))}
          </>
        )}
      </div>
    </>
  )
}
