/**
 * 单条追问建议条目（InquirySuggestionItem.tsx）
 * 包含问题文本、优先级标签、选项按钮、已选答案展示、👍/👎 反馈。
 */
import { useState } from 'react'
import { Button, Tag, Typography, message } from 'antd'
import { CheckOutlined, LikeOutlined, DislikeOutlined } from '@ant-design/icons'
import api from '@/services/api'
import { useWorkbenchStore } from '@/store/workbenchStore'

const { Text } = Typography

interface Suggestion {
  id: string
  text: string
  category: string
  options: string[]
  selectedOptions: string[]
  is_red_flag?: boolean
  priority?: string
}

interface Props {
  item: Suggestion
  idx: number
  total: number
  isQCDone?: boolean
  onSelectOption: (id: string, option: string) => void
}

export default function InquirySuggestionItem({
  item,
  idx,
  total,
  onSelectOption,
}: Props) {
  // 已选答案说明信息已采集，视觉变灰提示"已处理"；与病历是否锁定无关
  const isDimmed = item.selectedOptions.length > 0
  // 反馈状态（useful / useless / null），提交后禁用按钮
  const [feedback, setFeedback] = useState<null | 'useful' | 'useless'>(null)
  const [submitting, setSubmitting] = useState(false)
  const currentEncounterId = useWorkbenchStore(s => s.currentEncounterId)

  const handleFeedback = async (verdict: 'useful' | 'useless') => {
    if (feedback || submitting) return
    setSubmitting(true)
    try {
      await api.post('/ai/suggestion-feedback', {
        encounter_id: currentEncounterId,
        suggestion_category: 'inquiry',
        suggestion_id: item.id,
        suggestion_text: item.text,
        verdict,
      })
      setFeedback(verdict)
      message.success(verdict === 'useful' ? '感谢反馈「有用」' : '感谢反馈「无用」')
    } catch {
      message.error('反馈提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        borderBottom: idx < total - 1 ? '1px solid var(--border-subtle)' : 'none',
        padding: '12px 0',
        opacity: isDimmed ? 0.5 : 1,
        pointerEvents: 'auto',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6 }}>
        <Text style={{ fontSize: 11, color: 'var(--text-4)', fontWeight: 600 }}>Q{idx + 1}</Text>
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
          color: 'var(--text-1)',
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
                onClick={() => onSelectOption(item.id, opt)}
                style={{
                  fontSize: 12,
                  height: 'auto',
                  padding: '4px 10px',
                  borderRadius: 16,
                  whiteSpace: 'normal',
                  lineHeight: 1.4,
                  ...(isSelected
                    ? { background: '#2563eb', borderColor: '#2563eb' }
                    : { borderColor: 'var(--border)', color: '#374151' }),
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

      {/* 👍/👎 反馈栏（贴右下，始终可见） */}
      <div style={{ marginTop: 8, display: 'flex', justifyContent: 'flex-end', gap: 4 }}>
        <Button
          size="small"
          type="text"
          icon={<LikeOutlined />}
          disabled={!!feedback || submitting}
          onClick={() => handleFeedback('useful')}
          style={{
            fontSize: 11,
            height: 22,
            padding: '0 6px',
            color: feedback === 'useful' ? '#22c55e' : 'var(--text-4)',
          }}
        >
          有用
        </Button>
        <Button
          size="small"
          type="text"
          icon={<DislikeOutlined />}
          disabled={!!feedback || submitting}
          onClick={() => handleFeedback('useless')}
          style={{
            fontSize: 11,
            height: 22,
            padding: '0 6px',
            color: feedback === 'useless' ? '#ef4444' : 'var(--text-4)',
          }}
        >
          无用
        </Button>
      </div>
    </div>
  )
}
