/**
 * 质控问题面板（components/workbench/QCIssuePanel.tsx）
 *
 * 展示质控扫描结果，提供问题处理能力：
 *   - 规则引擎问题（source='rule'，蓝色标签"结构"）：必须修复才能签发
 *   - LLM 质量建议（source='llm'，绿色标签"建议"）：可忽略
 *   - 每条问题：标记已解决（✓）/ 标记忽略（跳过）/ AI 修复（生成补充文本）
 *   - 底部显示 GradeScoreCard（病历评分卡）
 *
 * 状态监听：
 *   qcRunId 变化时（新一轮质控开始）自动重置所有问题的本地操作状态（fixLoading / 写入快照）。
 *   避免上一轮用户操作残留影响新一轮结果。
 *
 * Audit Round 4 M6 拆分：
 *   - 单条问题渲染 → qcIssue/QCIssueItem.tsx
 *   - 颜色/标签常量 → qcIssue/qcConstants.ts
 *   - 本主文件保留：状态聚合 + AI 修复 / 写入逻辑 + 三种空态视图 + 列表分组
 */
import { useEffect, useMemo, useState } from 'react'
import { Alert, Empty, Spin, Tag, Tooltip, Typography } from 'antd'
import { CaretDownOutlined, CaretRightOutlined, WarningOutlined } from '@ant-design/icons'
import { message } from '@/services/messageBridge'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { useQCStore } from '@/store/qcStore'
import { useAiWrittenFieldsStore } from '@/store/aiWrittenFieldsStore'
import { QCIssue } from '@/store/types'
import {
  type FieldSnapshot,
  NON_WRITABLE_FIELDS,
  NON_WRITABLE_HINTS,
  restoreFieldState,
  snapshotFieldState,
  writeSectionToRecord,
} from './qcFieldMaps'
import GradeScoreCard from './GradeScoreCard'
import QCIssueItem from './qcIssue/QCIssueItem'
import api from '@/services/api'

const { Text } = Typography

export default function QCIssuePanel() {
  const {
    qcIssues,
    qcSummary,
    qcPass,
    qcRunId,
    qcLlmLoading,
    gradeScore,
    scoreReport,
    qcFixTexts,
    setQCFixTexts,
    qcWrittenIndices,
    setQCWrittenIndices,
  } = useQCStore()
  const { recordContent, setRecordContent } = useRecordStore()
  const inquiry = useInquiryStore(s => s.inquiry)

  const writtenSet = new Set(qcWrittenIndices)

  const [fixLoading, setFixLoading] = useState<Record<number, boolean>>({})
  // per-field 写入前快照——撤销时按字段精准还原（区分原本不存在 / 占位符 / 医生原值三态）
  // 比"全文快照"更精细：交错写入多条 issue 时取消其中一条不会冲掉其他条。
  const [fieldSnapshots, setFieldSnapshots] = useState<Record<number, FieldSnapshot>>({})

  // 新一轮质控开始时清空本地加载状态（store 侧由 startQCRun 清空 fixTexts / written）
  useEffect(() => {
    setFixLoading({})
    setFieldSnapshots({})
  }, [qcRunId])

  const setFixTextAt = (idx: number, text: string) => {
    setQCFixTexts({ ...qcFixTexts, [idx]: text })
  }

  const handleAIFix = async (item: QCIssue, idx: number) => {
    setFixLoading(prev => ({ ...prev, [idx]: true }))
    try {
      const result = (await api.post('/ai/qc-fix', {
        field_name: item.field_name,
        issue_description: item.issue_description,
        suggestion: item.suggestion,
        current_record: recordContent,
        chief_complaint: inquiry.chief_complaint,
        history_present_illness: inquiry.history_present_illness,
      })) as { fix_text?: string }
      setQCFixTexts({ ...qcFixTexts, [idx]: result.fix_text ?? '' })
    } catch {
      message.error('AI 生成修复失败，请重试')
    } finally {
      setFixLoading(prev => ({ ...prev, [idx]: false }))
    }
  }

  const handleWriteToRecord = (item: QCIssue, idx: number) => {
    // 治本（2026-05-19）：不可写入正文的字段（患者档案/就诊时间/中医四诊集合）
    // 不走写入路径——告诉医生去哪里修，避免在病历末尾创建错误章节。
    if (NON_WRITABLE_FIELDS.has(item.field_name)) {
      message.info(
        NON_WRITABLE_HINTS[item.field_name] || '该问题需手动修改，无法自动写入病历'
      )
      return
    }
    if (writtenSet.has(idx)) {
      // 取消写入：用 per-field 快照精准还原该字段
      //
      // 历史踩坑两轮：
      //   1. 整段全文快照回退 → 多条交错操作时取消会冲掉其他字段
      //   2. writeSectionToRecord(content, field, '') 字段级回滚到占位符
      //      → 写入前该行不存在的场景（LLM 精简版没生成）取消会留下莫名占位符
      //
      // 现在用 snapshotFieldState 在写入时记录三态（absent / placeholder / value），
      // 取消时按状态还原：原本没 → 删除行；原本占位符 → 留占位符；原本有值 → 写回值。
      const snapshot = fieldSnapshots[idx]
      if (snapshot) {
        const restored = restoreFieldState(recordContent, item.field_name, snapshot)
        setRecordContent(restored)
      }
      const next = new Set(writtenSet)
      next.delete(idx)
      setQCWrittenIndices(Array.from(next))
      // 清掉该 idx 的快照——下次再写入要重新捕获当时的快照
      setFieldSnapshots(prev => {
        const { [idx]: _removed, ...rest } = prev
        return rest
      })
      // AI 写入字段池移除该字段 —— 撤销 = 写入回滚，对应顶部 chip + 侧边 gutter 高亮消失
      useAiWrittenFieldsStore.getState().removeField(item.field_name)
      message.info('已取消写入')
      return
    }
    const fix = qcFixTexts[idx]?.trim() || ''
    if (!fix) return
    // 写入前先快照该字段当时的真实状态，撤销时据此精准还原
    const snapshot = snapshotFieldState(recordContent, item.field_name)
    const nextContent = writeSectionToRecord(recordContent, item.field_name, fix)
    // 安全网：若内容完全没变（映射缺失或 field_name 是全文类 "content" 等），
    // 不静默跳过，明确提示医生，避免"按了没反应"的体验
    if (nextContent === recordContent) {
      message.warning(`未能定位到章节"${item.field_name}"，建议手动粘贴修复文本到病历`)
      return
    }
    setRecordContent(nextContent)
    setFieldSnapshots(prev => ({ ...prev, [idx]: snapshot }))
    const next = new Set(writtenSet)
    next.add(idx)
    setQCWrittenIndices(Array.from(next))
    // AI 写入字段池追加该字段 —— 顶部 chip + 侧边 gutter 高亮出现，
    // 持续到医生点击该行 / 编辑该行 / 撤回 / 签发，统一标记"AI 写入未确认"。
    useAiWrittenFieldsStore.getState().addFields([item.field_name])
    message.success('已写入病历')
  }

  // ⚠️ Hooks 顺序约束：所有 useMemo / useState / useEffect 必须在 early-return 之前。
  // blockingIssues / suggestionIssues / groupedBlocking 提到这里统一计算。
  const blockingIssues = useMemo(
    () => qcIssues.filter(i => i.source === 'rule' || i.source == null),
    [qcIssues]
  )
  const suggestionIssues = useMemo(() => qcIssues.filter(i => i.source === 'llm'), [qcIssues])

  /** 按 PDF 大项分组：把每条 blocking issue 归入它所属的 score_report.items[].name。
   *
   * 关键：用 issue.item_name（大项名）而非 issue.field_name（写入目标字段）分组。
   * field_name 治本后变成子字段名（如"处理意见"），跟 item.name（"治疗意见及措施"）
   * 对不上；item_name 才是 PDF 大项名，跟 score_report.items[].name 严格对应。
   *
   * 向后兼容：旧后端 issue 没有 item_name 时退到 field_name（适用 1:1 映射场景）。
   */
  const groupedBlocking = useMemo(() => {
    if (!scoreReport) {
      // 无 score_report（旧后端返回 / persist 后向兼容）→ 退到平铺渲染
      return null
    }
    // 按 score_report.items 顺序构建分组
    const groups = scoreReport.items.map(item => {
      const issuesInItem = blockingIssues.filter(
        iss => (iss.item_name || iss.field_name) === item.name
      )
      const rawSum = item.deductions.reduce((s, d) => s + d.points, 0)
      // 触达上限：原始扣分 > 实际扣分（cap 生效）
      const cappedDown = rawSum > item.deducted && item.deducted > 0
      return { item, issues: issuesInItem, rawSum, cappedDown }
    })
    // 只保留触发扣分（即"必修问题"挂得上的）的大项
    return groups.filter(g => g.issues.length > 0 || g.item.deducted > 0)
  }, [scoreReport, blockingIssues])

  if (qcIssues.length === 0 && qcPass === null) {
    return (
      <>
        {gradeScore != null && <GradeScoreCard gradeScore={gradeScore} />}
        <Empty
          description={
            <span style={{ fontSize: 13, color: 'var(--text-4)' }}>
              点击「AI质控」进行病历质量检查
            </span>
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

  const renderItem = (item: QCIssue) => {
    const idx = qcIssues.indexOf(item)
    return (
      <QCIssueItem
        key={idx}
        item={item}
        idx={idx}
        fixText={qcFixTexts[idx] ?? ''}
        setFixText={setFixTextAt}
        written={writtenSet.has(idx)}
        fixLoading={fixLoading[idx] || false}
        onAIFix={handleAIFix}
        onWriteToRecord={handleWriteToRecord}
      />
    )
  }

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
            {/* A 方案：score_report 在 → 按 PDF 大项分组；缺 → 退到平铺旧 UI */}
            {groupedBlocking ? (
              groupedBlocking.map(g => (
                <RubricItemGroup
                  key={g.item.name}
                  itemName={g.item.name}
                  maxPoints={g.item.max_points}
                  deducted={g.item.deducted}
                  rawSum={g.rawSum}
                  cappedDown={g.cappedDown}
                  vetoTriggered={g.item.veto_triggered}
                  issues={g.issues}
                  renderItem={renderItem}
                />
              ))
            ) : (
              blockingIssues.map(renderItem)
            )}
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
            {suggestionIssues.map(renderItem)}
          </>
        )}
      </div>
    </>
  )
}


/** 单大项分组块（A 方案核心组件）。
 *
 * 显示：
 *   ▶ 现病史 (实际扣 7/20 分)              ← 头部，可点击折叠
 *     [-5 分] 现病史缺失或主要症状描述不清
 *     [-2 分] 缺诊治经过
 *
 *   ▶ 治疗意见及措施 (实际扣 10/10 分 ⚠️ 已达上限)
 *     [-5 分] 检查治疗项目不明确
 *     [-5 分] 治则治法与证型不符
 *     [-5 分] 无复诊建议或注意事项
 *     原始扣分 15 分 → 按 PDF 大项上限保护实际扣 10 分
 *
 * 默认展开（医生需要一屏看完），头部可点击切折叠。
 */
interface RubricItemGroupProps {
  itemName: string
  maxPoints: number
  deducted: number
  rawSum: number
  cappedDown: boolean
  vetoTriggered: boolean
  issues: QCIssue[]
  renderItem: (issue: QCIssue) => JSX.Element
}

function RubricItemGroup({
  itemName,
  maxPoints,
  deducted,
  rawSum,
  cappedDown,
  vetoTriggered,
  issues,
  renderItem,
}: RubricItemGroupProps) {
  // 默认展开（A 方案核心：一屏看完所有问题，医生可手动折叠）
  const [expanded, setExpanded] = useState(true)

  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 8,
        background: 'var(--surface-1)',
        marginBottom: 8,
      }}
    >
      {/* 头部：大项名 + 实际扣分/满分 + 角标 */}
      <div
        onClick={() => setExpanded(v => !v)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '8px 12px',
          cursor: 'pointer',
          userSelect: 'none',
          background: vetoTriggered ? '#fff1f2' : '#fffbeb',
          borderRadius: '8px 8px 0 0',
          fontSize: 12,
        }}
      >
        {expanded ? (
          <CaretDownOutlined style={{ fontSize: 10, color: 'var(--text-4)' }} />
        ) : (
          <CaretRightOutlined style={{ fontSize: 10, color: 'var(--text-4)' }} />
        )}
        <Text strong style={{ fontSize: 12 }}>
          {itemName}
        </Text>
        <Text type="secondary" style={{ fontSize: 11 }}>
          （实际扣 <Text type="danger">{deducted}</Text>/{maxPoints} 分）
        </Text>
        {vetoTriggered && (
          <Tag color="red" style={{ fontSize: 10, marginLeft: 4 }}>
            单项否决
          </Tag>
        )}
        {cappedDown && !vetoTriggered && (
          <Tooltip
            title={`原始扣分 ${rawSum} 分 → 按 PDF 大项上限保护实际扣 ${deducted} 分（同一项扣分不超过该项满分）`}
          >
            <Tag
              color="orange"
              icon={<WarningOutlined />}
              style={{ fontSize: 10, marginLeft: 4 }}
            >
              已达上限
            </Tag>
          </Tooltip>
        )}
      </div>

      {/* 展开后：该大项内所有 issue */}
      {expanded && (
        <div style={{ padding: '4px 8px 8px 8px' }}>
          {issues.map(renderItem)}
          {cappedDown && !vetoTriggered && (
            <Text
              type="secondary"
              style={{
                display: 'block',
                fontSize: 10,
                marginTop: 4,
                paddingLeft: 8,
                fontStyle: 'italic',
              }}
            >
              ↑ 原始扣分总计 {rawSum} 分，按 PDF 大项上限保护实际扣 {deducted} 分
            </Text>
          )}
        </div>
      )}
    </div>
  )
}
