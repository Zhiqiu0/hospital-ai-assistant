/**
 * 单份检验报告卡片（LabReportCard.tsx）
 * 展示报告类型、异常提示、展开详情、插入/删除操作。
 */
import { Button, Tag, Typography } from 'antd'
import {
  FileTextOutlined,
  DeleteOutlined,
  CheckCircleOutlined,
  PlusOutlined,
  WarningOutlined,
} from '@ant-design/icons'

const { Text } = Typography

interface LabReportItem {
  id: string
  original_filename: string
  ocr_text: string
  status: string
  created_at: string
}

function extractReportType(text: string): string {
  return text.match(/【报告类型】([^\n【]+)/)?.[1]?.trim() || '未知类型'
}

function extractPatientName(text: string): string {
  return text.match(/姓名[：:]\s*([^\s\n]+)/)?.[1]?.trim() || ''
}

interface Props {
  report: LabReportItem
  inserted: boolean
  expanded: boolean
  currentPatientName?: string
  onInsert: () => void
  onDelete: () => void
  onToggleExpand: () => void
}

export default function LabReportCard({
  report,
  inserted,
  expanded,
  currentPatientName,
  onInsert,
  onDelete,
  onToggleExpand,
}: Props) {
  const reportType = extractReportType(report.ocr_text)
  const anomalyMatch = report.ocr_text.match(/【异常项汇总】([\s\S]*?)(?=\n【|$)/)
  const hasAnomaly = !!anomalyMatch
  const anomalyItems = anomalyMatch
    ? anomalyMatch[1]
        .split(/\n?\d+\.\s+/)
        .filter(Boolean)
        .map(s => s.replace(/\*\*/g, '').split(/[：:]/)[0].trim())
        .filter(Boolean)
        .slice(0, 2)
    : []
  const reportPatientName = extractPatientName(report.ocr_text)
  const nameMismatch =
    !!reportPatientName && !!currentPatientName && reportPatientName !== currentPatientName

  return (
    <div
      style={{
        border: `1px solid ${nameMismatch ? '#fecaca' : inserted ? '#bbf7d0' : 'var(--border)'}`,
        borderRadius: 8,
        background: nameMismatch ? '#fff5f5' : inserted ? '#f0fdf4' : 'var(--surface)',
        overflow: 'hidden',
      }}
    >
      {/* 卡片标题行 */}
      <div
        style={{
          padding: '8px 10px',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
        onClick={onToggleExpand}
      >
        <FileTextOutlined
          style={{ color: nameMismatch ? '#ef4444' : '#7c3aed', fontSize: 13, flexShrink: 0 }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: 'var(--text-1)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {reportType}
          </div>
          <div
            style={{
              fontSize: 10,
              color: 'var(--text-4)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {report.original_filename}
          </div>
        </div>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 2,
            alignItems: 'flex-end',
            flexShrink: 0,
          }}
        >
          {inserted && (
            <Tag color="success" style={{ fontSize: 10, margin: 0, lineHeight: '16px' }}>
              已插入
            </Tag>
          )}
          {nameMismatch && (
            <Tag color="error" style={{ fontSize: 10, margin: 0, lineHeight: '16px' }}>
              <WarningOutlined /> 患者不符
            </Tag>
          )}
          {hasAnomaly && (
            <Tag color="warning" style={{ fontSize: 10, margin: 0, lineHeight: '16px' }}>
              <WarningOutlined /> 有异常
            </Tag>
          )}
        </div>
      </div>

      {/* 异常项摘要 */}
      {hasAnomaly && anomalyItems.length > 0 && (
        <div
          style={{
            padding: '4px 10px',
            background: '#fffbeb',
            borderTop: '1px solid #fef3c7',
            display: 'flex',
            gap: 6,
            flexWrap: 'wrap',
          }}
        >
          {anomalyItems.map((item, i) => (
            <span key={i} style={{ fontSize: 10, color: '#92400e' }}>
              ▲ {item}
            </span>
          ))}
        </div>
      )}

      {/* 展开内容 */}
      {expanded && (
        <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
          <div
            style={{
              padding: '8px 10px',
              fontSize: 11,
              lineHeight: 1.6,
              whiteSpace: 'pre-wrap',
              color: '#334155',
              maxHeight: 200,
              overflowY: 'auto',
              background: '#fafafa',
            }}
          >
            {report.ocr_text}
          </div>
        </div>
      )}

      {/* 操作栏 */}
      <div
        style={{
          padding: '6px 10px',
          display: 'flex',
          gap: 6,
          justifyContent: 'flex-end',
          borderTop: '1px solid var(--border-subtle)',
        }}
      >
        <Text style={{ fontSize: 10, color: 'var(--text-4)', flex: 1, alignSelf: 'center' }}>
          {report.created_at
            ? new Date(report.created_at).toLocaleString('zh-CN', {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
              })
            : ''}
        </Text>
        <Button
          size="small"
          icon={<DeleteOutlined />}
          danger
          onClick={onDelete}
          style={{ fontSize: 11, borderRadius: 5, height: 24 }}
        />
        <Button
          size="small"
          icon={inserted ? <CheckCircleOutlined /> : <PlusOutlined />}
          onClick={onInsert}
          style={{
            fontSize: 11,
            borderRadius: 5,
            height: 24,
            color: inserted ? '#16a34a' : '#7c3aed',
            borderColor: inserted ? '#86efac' : '#ddd6fe',
            background: inserted ? '#f0fdf4' : '#f5f3ff',
          }}
        >
          {inserted ? '已插入' : '插入'}
        </Button>
      </div>
    </div>
  )
}
