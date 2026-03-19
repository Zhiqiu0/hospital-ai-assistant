import { useEffect } from 'react'
import { Form, Input, Button, message, Divider } from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import api from '@/services/api'
import VoiceInputCard from './VoiceInputCard'

const { TextArea } = Input

const fieldStyle = {
  marginBottom: 14,
}

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: '#475569',
  marginBottom: 4,
  display: 'block',
}

export default function InquiryPanel() {
  const [form] = Form.useForm()
  const { inquiry, setInquiry, currentEncounterId } = useWorkbenchStore()

  useEffect(() => {
    form.setFieldsValue(inquiry)
  }, [form, inquiry, currentEncounterId])

  const onSave = async (values: any) => {
    const data = {
      chief_complaint: values.chief_complaint || '',
      history_present_illness: values.history_present_illness || '',
      past_history: values.past_history || '',
      allergy_history: values.allergy_history || '',
      personal_history: values.personal_history || '',
      physical_exam: values.physical_exam || '',
      initial_impression: values.initial_impression || '',
    }
    setInquiry(data)
    // Persist to DB if an encounter is active
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, data).catch(() => {})
    }
    message.success({ content: '问诊信息已保存', duration: 1.5 })
  }

  const applyVoiceInquiry = (patch: any) => {
    const nextValues = { ...form.getFieldsValue(), ...patch }
    form.setFieldsValue(nextValues)
    const data = {
      chief_complaint: nextValues.chief_complaint || '',
      history_present_illness: nextValues.history_present_illness || '',
      past_history: nextValues.past_history || '',
      allergy_history: nextValues.allergy_history || '',
      personal_history: nextValues.personal_history || '',
      physical_exam: nextValues.physical_exam || '',
      initial_impression: nextValues.initial_impression || '',
    }
    setInquiry(data)
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, data).catch(() => {})
    }
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Panel header */}
      <div style={{
        padding: '14px 16px 12px',
        borderBottom: '1px solid #f1f5f9',
        background: '#fff',
        flexShrink: 0,
      }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>问诊录入</div>
        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>填写后保存，AI自动同步建议</div>
      </div>

      {/* Form */}
      <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
        <Form form={form} layout="vertical" size="small" onFinish={onSave}>
          <VoiceInputCard
            visitType="outpatient"
            getFormValues={() => form.getFieldsValue()}
            onApplyInquiry={applyVoiceInquiry}
          />

          <Form.Item
            style={fieldStyle}
            name="chief_complaint"
            rules={[{ required: true, message: '请输入主诉' }]}
            label={<span style={labelStyle}>主诉 <span style={{ color: '#ef4444' }}>*</span></span>}
          >
            <TextArea
              rows={2}
              placeholder="症状 + 持续时间，如：发热伴咳嗽3天"
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
            />
          </Form.Item>

          <Divider style={{ margin: '8px 0 12px', borderColor: '#f1f5f9' }} />

          <Form.Item style={fieldStyle} name="history_present_illness"
            label={<span style={labelStyle}>现病史</span>}>
            <TextArea rows={4} placeholder="详细描述发病经过、症状变化..." style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Form.Item style={fieldStyle} name="past_history"
            label={<span style={labelStyle}>既往史</span>}>
            <TextArea rows={2} placeholder="慢性病、手术史、住院史..." style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Form.Item style={fieldStyle} name="allergy_history"
            label={<span style={labelStyle}>过敏史</span>}>
            <Input placeholder="如：青霉素过敏 / 否认过敏史" style={{ borderRadius: 6, fontSize: 13 }} />
          </Form.Item>

          <Form.Item style={fieldStyle} name="personal_history"
            label={<span style={labelStyle}>个人史</span>}>
            <TextArea rows={2} placeholder="吸烟、饮酒、职业、婚育史..." style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Divider style={{ margin: '8px 0 12px', borderColor: '#f1f5f9' }} />

          <Form.Item style={fieldStyle} name="physical_exam"
            label={<span style={labelStyle}>体格检查</span>}>
            <TextArea rows={3} placeholder="生命体征、各系统体检结果..." style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0 }} name="initial_impression"
            label={<span style={labelStyle}>初步印象</span>}>
            <Input placeholder="初步诊断方向..." style={{ borderRadius: 6, fontSize: 13 }} />
          </Form.Item>
        </Form>
      </div>

      {/* Save button */}
      <div style={{
        padding: '10px 16px',
        borderTop: '1px solid #f1f5f9',
        background: '#fff',
        flexShrink: 0,
      }}>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          block
          onClick={() => form.submit()}
          style={{
            borderRadius: 8, height: 36, fontWeight: 600,
            background: 'linear-gradient(135deg, #2563eb, #3b82f6)',
            border: 'none',
          }}
        >
          保存问诊信息
        </Button>
      </div>
    </div>
  )
}
