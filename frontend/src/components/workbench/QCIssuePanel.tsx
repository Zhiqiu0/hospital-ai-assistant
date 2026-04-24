/**
 * 质控问题面板（components/workbench/QCIssuePanel.tsx）
 *
 * 展示质控扫描结果，提供问题处理能力：
 *   - 规则引擎问题（source='rule'，蓝色标签"结构"）：必须修复才能签发
 *   - LLM 质量建议（source='llm'，绿色标签"建议"）：可忽略
 *   - 每条问题支持：标记已解决（✓）/ 标记忽略（跳过）/ AI 修复（生成补充文本）
 *   - 问题状态持久化：调用 PATCH /qc-issues/{id} 更新数据库状态
 *   - 底部显示 GradeScoreCard（病历评分卡）
 *
 * 状态监听：
 *   qcRunId 变化时（新一轮质控开始）自动重置所有问题的本地操作状态（resolved/ignored/fixing）。
 *   这样可以避免上一轮用户操作残留影响新一轮结果。
 *
 * AI 修复（qc-fix）：
 *   对单条质控问题调用 POST /ai/qc-fix，返回可直接写入对应字段的修复文本。
 *   修复结果通过 writeSectionToRecord（qcFieldMaps.ts）写入病历编辑区。
 */
import { useState, useEffect } from 'react'
import { Button, Typography, Empty, Alert, Tag, message, Input, Spin } from 'antd'
import { BulbOutlined, EditOutlined } from '@ant-design/icons'
import { useWorkbenchStore, QCIssue } from '@/store/workbenchStore'
import { FIELD_NAME_LABEL, writeSectionToRecord } from './qcFieldMaps'
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
    qcRunId,
    qcLlmLoading,
    gradeScore,
    recordContent,
    setRecordContent,
    inquiry,
    qcFixTexts,
    setQCFixTexts,
    qcWrittenIndices,
    setQCWrittenIndices,
  } = useWorkbenchStore()

  // fixTexts 持久化到 store，刷新后保留；支持函数式更新
  const fixTexts = qcFixTexts
  const setFixTexts = (
    updater: Record<number, string> | ((prev: Record<number, string>) => Record<number, string>)
  ) => {
    const next = typeof updater === 'function' ? updater(qcFixTexts) : updater
    setQCFixTexts(next)
  }
  const writtenSet = new Set(qcWrittenIndices)
  const setWrittenSet = (updater: Set<number> | ((prev: Set<number>) => Set<number>)) => {
    const next = typeof updater === 'function' ? updater(writtenSet) : updater
    setQCWrittenIndices(Array.from(next))
  }

  const [fixLoading, setFixLoading] = useState<Record<number, boolean>>({})
  // 写入前的病历快照，取消时用于还原（不需持久化，取消只在本次会话内有效）
  const [originalSnapshots, setOriginalSnapshots] = useState<Record<number, string>>({})

  // 只在新一轮质控开始时清空本地加载状态（store 侧由 startQCRun 清空）
  useEffect(() => {
    setFixLoading({})
    setOriginalSnapshots({})
  }, [qcRunId])

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
      // 取消写入：还原到写入前的病历快照，而不是置空
      const snapshot = originalSnapshots[idx]
      if (snapshot !== undefined) setRecordContent(snapshot)
      setWrittenSet(prev => {
        const s = new Set(prev)
        s.delete(idx)
        return s
      })
      message.info('已取消写入，已还原原内容')
    } else {
      const fix = fixTexts[idx]?.trim() || ''
      if (!fix) return
      // 写入前先保存当前病历快照
      setOriginalSnapshots(prev => ({ ...prev, [idx]: recordContent }))
      const nextContent = writeSectionToRecord(recordContent, item.field_name, fix)
      // 安全网：若内容完全没变（映射缺失或 field_name 是全文类 "content" 等），
      // 不静默跳过，明确提示医生，避免"按了没反应"的体验
      if (nextContent === recordContent) {
        message.warning(`未能定位到章节"${item.field_name}"，建议手动粘贴修复文本到病历`)
        return
      }
      setRecordContent(nextContent)
      setWrittenSet(prev => new Set(prev).add(idx))
      message.success('已写入病历')
    }
  }

  const renderIssue = (item: QCIssue, idx: number) => (
    <div
      key={idx}
      style={{
        background: 'var(--surface)',
        border: `1px solid ${item.source === 'rule' || item.source == null ? '#fca5a5' : 'var(--border)'}`,
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
          color: 'var(--text-1)',
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
                ...(writtenSet.has(idx)
                  ? { background: 'var(--text-4)', borderColor: 'var(--text-4)', color: 'var(--surface)' }
                  : {}),
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
            <span style={{ fontSize: 13, color: 'var(--text-4)' }}>点击「AI质控」进行病历质量检查</span>
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
        {(suggestionIssues.length > 0 || qcLlmLoading) && (
          <>
            <Text
              style={{
                fontSize: 11,
                color: '#92400e',
                fontWeight: 600,
                marginTop: blockingIssues.length > 0 ? 4 : 0,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              ▍质量建议
              {suggestionIssues.length > 0
                ? `（共 ${suggestionIssues.length} 项，不影响出具，但建议改进）`
                : ''}
              {qcLlmLoading && <Spin size="small" style={{ marginLeft: 4 }} />}
              {qcLlmLoading && (
                <span style={{ fontWeight: 400, color: 'var(--text-4)' }}>AI 分析中...</span>
              )}
            </Text>
            {suggestionIssues.map(item => renderIssue(item, qcIssues.indexOf(item)))}
          </>
        )}
      </div>
    </>
  )
}
