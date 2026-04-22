/**
 * 单条追问建议条目（InquirySuggestionItem.tsx）
 * 包含问题文本、优先级标签、选项按钮、已选答案展示。
 */
import { Button, Tag, Typography } from 'antd'
import { CheckOutlined } from '@ant-design/icons'

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
  isQCDone: boolean
  onSelectOption: (id: string, option: string) => void
}

export default function InquirySuggestionItem({
  item,
  idx,
  total,
  isQCDone,
  onSelectOption,
}: Props) {
  const isPastHistory = item.category === '既往信息'
  const isDimmed = isPastHistory || isQCDone

  return (
    <div
      style={{
        borderBottom: idx < total - 1 ? '1px solid #f1f5f9' : 'none',
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
}
