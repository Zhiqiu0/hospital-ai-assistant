import { useEffect, useState } from 'react'
import { Form, Input, Button, message, Divider } from 'antd'
import { SaveOutlined, CheckOutlined } from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import api from '@/services/api'
import VoiceInputCard from './VoiceInputCard'
import VitalSignsInput from './VitalSignsInput'
import LabOrderPopover from './LabOrderPopover'
import LabReportUploadButton from './LabReportUploadButton'

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
  const { inquiry, setInquiry, currentEncounterId, currentPatient, recordContent, setRecordContent } = useWorkbenchStore()
  const isFemale = currentPatient?.gender === 'female'
  const [isDirty, setIsDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    form.setFieldsValue(inquiry)
    setIsDirty(false)
  }, [form, inquiry, currentEncounterId])

  const buildData = (values: any) => ({
    chief_complaint: values.chief_complaint || '',
    history_present_illness: values.history_present_illness || '',
    past_history: values.past_history || '',
    allergy_history: values.allergy_history || '',
    personal_history: values.personal_history || '',
    menstrual_history: values.menstrual_history || '',
    physical_exam: values.physical_exam || '',
    auxiliary_exam: values.auxiliary_exam || '',
    initial_impression: values.initial_impression || '',
  })

  const onSave = async (values: any) => {
    setSaving(true)
    const data = buildData(values)
    setInquiry(data)
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, data).catch(() => {})
    }
    // 自动同步所有字段到已有病历对应段落
    if (recordContent) {
      const fieldMap: [string, string][] = [
        ['【主诉】', data.chief_complaint],
        ['【现病史】', data.history_present_illness],
        ['【既往史】', data.past_history],
        ['【体格检查】', data.physical_exam],
        ['【辅助检查】', data.auxiliary_exam || ''],
        ['【初步诊断】', data.initial_impression],
      ]
      let updated = recordContent
      for (const [header, value] of fieldMap) {
        if (!value) continue
        updated = updated.replace(
          new RegExp(`${header}\\n[\\s\\S]*?(?=\\n【|$)`),
          `${header}\n${value}`
        )
      }
      if (updated !== recordContent) setRecordContent(updated)
    }
    message.success({ content: '问诊信息已保存', duration: 1.5 })
    setIsDirty(false)
    setSaving(false)
  }

  const applyVoiceInquiry = (patch: any) => {
    const nextValues = { ...form.getFieldsValue(), ...patch }
    form.setFieldsValue(nextValues)
    const data = buildData(nextValues)
    setInquiry(data)
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, data).catch(() => {})
    }
    setIsDirty(false)
  }

  const handleVitalFill = (vitalText: string) => {
    const current = form.getFieldValue('physical_exam') || ''
    const lines = current.split('\n')
    const firstLine = lines[0] || ''
    const isVitalLine = /^(T:|P:|R:|BP:|SpO|身高:|体重:)/.test(firstLine)

    let mergedLine: string
    if (isVitalLine) {
      // 合并：保留已有项，用新值覆盖或追加
      const getKey = (s: string) => s.split(':')[0]
      const existingParts = firstLine.split(/\s{2,}/).filter(Boolean)
      const newParts = vitalText.split(/\s{2,}/).filter(Boolean)
      const result = [...existingParts]
      for (const part of newParts) {
        const key = getKey(part)
        const idx = result.findIndex(p => getKey(p) === key)
        if (idx >= 0) result[idx] = part
        else result.push(part)
      }
      mergedLine = result.join('  ')
    } else {
      mergedLine = vitalText
    }

    const newVal = isVitalLine
      ? [mergedLine, ...lines.slice(1)].join('\n')
      : mergedLine + (current ? '\n' + current : '')
    form.setFieldValue('physical_exam', newVal)
    setIsDirty(true)
  }

  const handleLabInsert = (text: string) => {
    const current = form.getFieldValue('auxiliary_exam') || ''
    const newVal = current ? current + '\n' + text : text
    form.setFieldValue('auxiliary_exam', newVal)
    setIsDirty(true)
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
        <Form form={form} layout="vertical" size="small" onFinish={onSave} onValuesChange={() => setIsDirty(true)}>
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

          {isFemale && (
            <Form.Item style={fieldStyle} name="menstrual_history"
              label={<span style={labelStyle}>月经史</span>}>
              <TextArea rows={2} placeholder="初潮年龄、周期、末次月经时间、经量、痛经情况..." style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
            </Form.Item>
          )}

          <Divider style={{ margin: '8px 0 12px', borderColor: '#f1f5f9' }} />

          {/* Vital signs quick input */}
          <VitalSignsInput onFill={handleVitalFill} />

          <Form.Item style={fieldStyle} name="physical_exam"
            label={<span style={labelStyle}>体格检查</span>}>
            <TextArea rows={4} placeholder="生命体征、各系统体检结果..." style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          {/* Auxiliary exam with lab order button */}
          <Form.Item
            style={fieldStyle}
            name="auxiliary_exam"
            label={
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
                <span style={labelStyle}>辅助检查</span>
                <div style={{ display: 'flex', gap: 6 }}>
                  <LabReportUploadButton onInsert={handleLabInsert} />
                  <LabOrderPopover onInsert={handleLabInsert} />
                </div>
              </div>
            }
          >
            <TextArea rows={3} placeholder="已有检查结果，或点击「快速开单」添加拟行检查..." style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
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
          icon={isDirty ? <SaveOutlined /> : <CheckOutlined />}
          block
          disabled={!isDirty}
          loading={saving}
          onClick={() => form.submit()}
          style={{
            borderRadius: 8, height: 36, fontWeight: 600,
            background: isDirty
              ? 'linear-gradient(135deg, #2563eb, #3b82f6)'
              : '#86efac',
            border: 'none',
            color: isDirty ? '#fff' : '#166534',
            transition: 'all 0.3s',
          }}
        >
          {isDirty ? '保存问诊信息' : '已保存 ✓'}
        </Button>
      </div>
    </div>
  )
}
