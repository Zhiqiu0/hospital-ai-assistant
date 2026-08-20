/**
 * 患者档案单字段渲染（components/workbench/patientProfile/PatientProfileField.tsx）
 *
 * 一个字段 = label 行（标题 + 时间戳标签 + ✓ 仍准确按钮）+ 输入区（Input / TextArea）。
 * 时间戳染色 / 仍准确按钮的可见性逻辑都封装在这里，主面板只管传 fieldsMeta + 触发回调。
 *
 * 从 PatientProfileCard.tsx 拆出（Audit Round 4 M6）。
 *
 * 常用句式标签（2026-08-18）：输入框下方一排小标签，点一下把标准否认句式追加进正文，
 * 句式表在 profilePhrases.ts；医生自己点的才算医生确认，AI 不替他补。
 */
import { Button, Input, Space, Tag } from 'antd'
import { CheckOutlined, PlusOutlined } from '@ant-design/icons'
import type { FieldConfig } from './staleness'
import { getStaleness } from './staleness'
import { PROFILE_PHRASES, appendPhrase } from './profilePhrases'

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
  /** HIS 推来的、与本地不一致的值（2026-08-13）；无差异时为空 */
  hisPendingValue?: string | null
  /** 正在裁决该字段的 HIS 差异 */
  resolving?: boolean
  /** 裁决回调：adopt=true 采纳 HIS 值，false 保留本地值 */
  onResolveHis?: (key: string, adopt: boolean) => void
  /** 输入锁定：字段由 Form disabled 级联变灰，但句式 Tag 不受级联，需显式隐藏 */
  locked?: boolean
}

export default function PatientProfileField(props: PatientProfileFieldProps) {
  const { field, value, onChange, fieldUpdatedAt, confirming, onConfirm } = props
  const { hisPendingValue, resolving, onResolveHis, locked } = props
  const stale = getStaleness(fieldUpdatedAt, field.staleAfterDays ?? 180)
  const hasValue = !!value?.trim()
  // 该字段配置了的常用句式；已在正文里的不再显示，避免重复点；锁定时全部隐藏
  const phrases = locked
    ? []
    : (PROFILE_PHRASES[field.key] ?? []).filter(p => !(value || '').includes(p.text))

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
      {/* HIS 差异提示（2026-08-13）：HIS 推来的值与本地不一致时展示两边内容，
          由医生裁决。不自动覆盖（HIS 可能是陈旧数据），也不自动丢弃
          （过敏史漏一项会出用药事故）。 */}
      {hisPendingValue && onResolveHis && (
        <div
          style={{
            marginBottom: 6,
            padding: '6px 8px',
            borderRadius: 6,
            background: '#fffbeb',
            border: '1px solid #fcd34d',
            fontSize: 12,
            lineHeight: 1.6,
          }}
        >
          <div style={{ color: '#92400e', marginBottom: 2 }}>HIS 记录与本地不一致：</div>
          <div style={{ color: '#78350f', wordBreak: 'break-all' }}>{hisPendingValue}</div>
          <Space size={4} style={{ marginTop: 2 }}>
            <Button
              size="small"
              type="link"
              loading={resolving}
              onClick={e => {
                e.stopPropagation()
                onResolveHis(field.key, true)
              }}
              style={{ fontSize: 11, height: 20, padding: '0 4px' }}
            >
              采纳 HIS
            </Button>
            <Button
              size="small"
              type="link"
              loading={resolving}
              onClick={e => {
                e.stopPropagation()
                onResolveHis(field.key, false)
              }}
              style={{ fontSize: 11, height: 20, padding: '0 4px', color: 'var(--text-3)' }}
            >
              保留本地
            </Button>
          </Space>
        </div>
      )}
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
      {/* 常用句式：点标签追加标准句式（不覆盖已有内容） */}
      {phrases.length > 0 && (
        <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {phrases.map(p => (
            <Tag
              key={p.label}
              icon={<PlusOutlined />}
              onClick={() => onChange(appendPhrase(value, p.text))}
              title={p.text}
              style={{ cursor: 'pointer', fontSize: 11, margin: 0, userSelect: 'none' }}
            >
              {p.label}
            </Tag>
          ))}
        </div>
      )}
    </div>
  )
}
