/**
 * 问诊基础字段（components/workbench/inquiry/InquiryBasicFields.tsx）
 *
 * 内容：主诉 + 现病史。复诊时现病史顶部加黄色 banner 提示必填症状变化。
 */
import { Form, Input } from 'antd'

const { TextArea } = Input

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-2)',
  marginBottom: 4,
  display: 'block',
}

const fs: React.CSSProperties = { marginBottom: 10 }

interface InquiryBasicFieldsProps {
  isFirstVisit: boolean
}

export default function InquiryBasicFields({ isFirstVisit }: InquiryBasicFieldsProps) {
  return (
    <>
      <Form.Item
        style={fs}
        name="chief_complaint"
        rules={[{ required: true, message: '请输入主诉' }]}
        label={
          <span style={labelStyle}>
            主诉 <span style={{ color: '#ef4444' }}>*</span>
          </span>
        }
      >
        <TextArea
          rows={2}
          placeholder={
            isFirstVisit
              ? '症状 + 持续时间，如：发热伴咳嗽3天'
              : '本次就诊原因，可含诊断名称，如：高血压复诊'
          }
          style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
        />
      </Form.Item>

      <Form.Item
        style={fs}
        name="history_present_illness"
        label={
          <span style={labelStyle}>
            现病史 <span style={{ color: '#ef4444' }}>*</span>
          </span>
        }
      >
        {!isFirstVisit && (
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 6,
              background: '#fffbeb',
              border: '1px solid #fcd34d',
              borderRadius: 6,
              padding: '6px 10px',
              marginBottom: 6,
              fontSize: 12,
              color: '#92400e',
              lineHeight: 1.5,
            }}
          >
            <span style={{ fontSize: 14, flexShrink: 0 }}>⚠️</span>
            <span>
              <b>复诊必填：</b>
              须记录上次治疗后症状改变情况（好转／无变化／加重），否则质控不通过。
            </span>
          </div>
        )}
        <TextArea
          rows={isFirstVisit ? 4 : 5}
          placeholder={
            isFirstVisit
              ? '起病经过、主要症状体征、诊治经过、一般情况（饮食/睡眠/二便）'
              : '【必填】上次治疗后症状变化：好转/无变化/加重；本次主要症状；一般情况（饮食/睡眠/二便）'
          }
          style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
        />
      </Form.Item>
    </>
  )
}
