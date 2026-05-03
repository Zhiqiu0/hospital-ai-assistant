/**
 * 问诊时间字段（components/workbench/inquiry/InquiryTimeFields.tsx）
 *
 * 内容：就诊时间 + 病发时间，两个 DatePicker。
 * 用 ClockCircleOutlined 图标 + 浅灰背景突出"时间"分组。
 */
import { Form, DatePicker } from 'antd'
import { ClockCircleOutlined } from '@ant-design/icons'

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-2)',
  marginBottom: 2,
  display: 'block',
}

interface InquiryTimeFieldsProps {
  inquiry: any
  updateInquiryFields: (data: any) => void
}

export default function InquiryTimeFields({
  inquiry,
  updateInquiryFields,
}: InquiryTimeFieldsProps) {
  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: '8px 10px',
        marginBottom: 10,
        display: 'flex',
        gap: 10,
        alignItems: 'flex-start',
      }}
    >
      <ClockCircleOutlined style={{ color: 'var(--text-3)', marginTop: 6, flexShrink: 0 }} />
      <div style={{ flex: 1, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Form.Item
          style={{ marginBottom: 0, flex: '1 1 140px' }}
          name="visit_time"
          label={
            <span style={labelStyle}>
              就诊时间 <span style={{ color: '#ef4444' }}>*</span>
            </span>
          }
          // 之前只挂红 * 没挂 rules，UI 标必填但实际不校验，属于"骗用户"。
          // 跟 onset_time 对齐，让红 * 跟实际 required 校验一致。
          rules={[{ required: true, message: '请选择就诊时间' }]}
        >
          <DatePicker
            showTime={{ format: 'HH:mm', use12Hours: false }}
            format="YYYY-MM-DD HH:mm"
            placeholder="选择就诊时间"
            style={{ width: '100%', borderRadius: 6, fontSize: 12 }}
            size="small"
            onChange={val =>
              updateInquiryFields({
                ...inquiry,
                visit_time: val ? val.format('YYYY-MM-DD HH:mm') : '',
              })
            }
          />
        </Form.Item>
        <Form.Item
          style={{ marginBottom: 0, flex: '1 1 140px' }}
          name="onset_time"
          label={
            <span style={labelStyle}>
              病发时间 <span style={{ color: '#ef4444' }}>*</span>
            </span>
          }
          rules={[{ required: true, message: '请选择病发时间' }]}
        >
          <DatePicker
            showTime={{ format: 'HH:mm', use12Hours: false }}
            format="YYYY-MM-DD HH:mm"
            placeholder="请选择病发时间"
            style={{ width: '100%', borderRadius: 6, fontSize: 12 }}
            size="small"
            onChange={val =>
              updateInquiryFields({
                ...inquiry,
                onset_time: val ? val.format('YYYY-MM-DD HH:mm') : '',
              })
            }
          />
        </Form.Item>
      </div>
    </div>
  )
}
