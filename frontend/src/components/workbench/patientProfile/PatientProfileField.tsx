/**
 * 患者档案单字段渲染（components/workbench/patientProfile/PatientProfileField.tsx）
 *
 * 一个字段 = label 行（标题 + 时间戳标签 + ✓ 仍准确按钮）+ 输入区（Input / TextArea）。
 * 时间戳染色 / 仍准确按钮的可见性逻辑都封装在这里，主面板只管传 fieldsMeta + 触发回调。
 *
 * 从 PatientProfileCard.tsx 拆出（Audit Round 4 M6）。
 */
import { Button, Input, Space } from 'antd'
import { CheckOutlined } from '@ant-design/icons'
import type { FieldConfig } from './staleness'
import { getStaleness } from './staleness'

const { TextArea } = Input

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-2)',
  marginBottom: 4,
  display: 'block',
}

interface PatientProfileFieldProps {
  field: FieldConfig
  value: string
  onChange: (value: string) => void
  fieldUpdatedAt: string | null | undefined
  confirming: boolean
  onConfirm: (key: string) => void
}

export default function PatientProfileField(props: PatientProfileFieldProps) {
  const { field, value, onChange, fieldUpdatedAt, confirming, onConfirm } = props
  const stale = getStaleness(fieldUpdatedAt, field.staleAfterDays ?? 180)
  const hasValue = !!value?.trim()

  return (
    <div style={{ marginBottom: 10 }}>
      {/* label 行：标签 + 时间戳/确认按钮（右对齐） */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 4,
        }}
      >
        <span style={labelStyle}>{field.label}</span>
        {stale && hasValue && (
          <Space size={4}>
            <span
              style={{
                fontSize: 10,
                color: stale.color,
                background: stale.bgColor,
                padding: stale.bgColor ? '1px 6px' : 0,
                borderRadius: 4,
              }}
            >
              {stale.label}
            </span>
            {/* 仅在"开始变黄"以后显示确认按钮，避免新数据也来打扰 */}
            {stale.days > 7 && (
              <Button
                size="small"
                type="link"
                icon={<CheckOutlined />}
                loading={confirming}
                onClick={e => {
                  e.stopPropagation()
                  onConfirm(field.key)
                }}
                style={{ fontSize: 10, height: 18, padding: '0 4px', color: '#059669' }}
              >
                仍准确
              </Button>
            )}
          </Space>
        )}
      </div>
      {field.singleLine ? (
        <Input
          size="small"
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={field.placeholder}
          style={{ borderRadius: 6, fontSize: 13 }}
        />
      ) : (
        <TextArea
          rows={field.rows}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={field.placeholder}
          style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
        />
      )}
    </div>
  )
}
