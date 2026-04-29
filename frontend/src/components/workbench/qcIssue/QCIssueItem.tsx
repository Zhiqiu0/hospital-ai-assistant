/**
 * 单条质控问题卡片（components/workbench/qcIssue/QCIssueItem.tsx）
 *
 * 从 QCIssuePanel.tsx 拆出（Audit Round 4 M6）：每条问题渲染 + AI 修复 + 写入病历。
 *
 * 行为分支：
 *   - LLM 全文格式问题（field_name 为空 / 'content'）：仅展示提示，引导用户走"AI 润色"
 *   - 普通问题：展示 TextArea 修复文本（可手改）+ 「逐条修复」按钮（调 /ai/qc-fix）
 *               + 「写入病历」按钮（调 writeSectionToRecord）
 *
 * 状态由父组件 QCIssuePanel 集中管理（fixTexts / writtenSet / fixLoading），通过 props 传入；
 * 这样跨多个问题的"哪些已写入 / 哪些 AI 还在跑"可以在父侧统一控制 + 持久化到 store。
 */
import { Button, Input, Tag, Typography } from 'antd'
import { BulbOutlined, EditOutlined } from '@ant-design/icons'
import { QCIssue } from '@/store/types'
import { FIELD_NAME_LABEL } from '../qcFieldMaps'
import { QC_RISK_COLOR, QC_RISK_LABEL, QC_TYPE_COLOR, QC_TYPE_LABEL } from './qcConstants'

const { Text } = Typography

interface QCIssueItemProps {
  item: QCIssue
  idx: number
  fixText: string
  setFixText: (idx: number, text: string) => void
  written: boolean
  fixLoading: boolean
  onAIFix: (item: QCIssue, idx: number) => void
  onWriteToRecord: (item: QCIssue, idx: number) => void
}

export default function QCIssueItem(props: QCIssueItemProps) {
  const { item, idx, fixText, setFixText, written, fixLoading, onAIFix, onWriteToRecord } = props
  const isRule = item.source === 'rule' || item.source == null
  const isFullTextSuggestion =
    item.source === 'llm' && (!item.field_name || item.field_name === 'content')

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: `1px solid ${isRule ? '#fca5a5' : 'var(--border)'}`,
        borderRadius: 10,
        padding: '12px 14px',
        boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
      }}
    >
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}
      >
        {isRule ? (
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
      {isFullTextSuggestion ? (
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
            value={fixText}
            onChange={e => setFixText(idx, e.target.value)}
            rows={3}
            style={{ fontSize: 13, borderRadius: 6, marginBottom: 8, resize: 'vertical' }}
            placeholder="修复建议（可编辑）..."
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <Button
              size="small"
              icon={<BulbOutlined />}
              loading={fixLoading}
              onClick={() => onAIFix(item, idx)}
              style={{ fontSize: 12, borderRadius: 6 }}
            >
              逐条修复
            </Button>
            <Button
              size="small"
              type={written ? 'primary' : 'default'}
              icon={<EditOutlined />}
              disabled={!written && !fixText?.trim()}
              onClick={() => onWriteToRecord(item, idx)}
              style={{
                fontSize: 12,
                borderRadius: 6,
                ...(written
                  ? {
                      background: 'var(--text-4)',
                      borderColor: 'var(--text-4)',
                      color: 'var(--surface)',
                    }
                  : {}),
              }}
            >
              {written ? '已写入' : '写入病历'}
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
