/**
 * 诊断建议列表（DiagnosisSuggestionList.tsx）
 * 展示 AI 生成的鉴别诊断列表，支持一键写入病历【初步诊断】章节。
 */
import { Button, Tag, Tooltip, Typography } from 'antd'
import { BulbOutlined, CheckOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { DiagnosisItem } from '@/store/workbenchStore'

const { Text } = Typography

const CONFIDENCE_CONFIG: Record<string, { color: string; label: string; bg: string }> = {
  high: { color: '#059669', label: '高度符合', bg: '#f0fdf4' },
  medium: { color: '#d97706', label: '可能符合', bg: '#fffbeb' },
  low: { color: '#64748b', label: '待排除', bg: '#f8fafc' },
}

interface Props {
  diagnosisSuggestions: DiagnosisItem[]
  appliedDiagnosis: string | null
  diagnosisLoading: boolean
  isInputLocked: boolean
  answeredCount: number
  onGetDiagnosis: () => void
  onApplyDiagnosis: (name: string) => void
}

export default function DiagnosisSuggestionList({
  diagnosisSuggestions,
  appliedDiagnosis,
  diagnosisLoading,
  isInputLocked,
  answeredCount,
  onGetDiagnosis,
  onApplyDiagnosis,
}: Props) {
  return (
    <>
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
        onClick={onGetDiagnosis}
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
                  <Tooltip title={isApplied ? '点击取消' : '写入初步诊断'}>
                    <Button
                      size="small"
                      type={isApplied ? 'primary' : 'default'}
                      icon={isApplied ? <CheckOutlined /> : <ArrowRightOutlined />}
                      onClick={() => onApplyDiagnosis(d.name)}
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
