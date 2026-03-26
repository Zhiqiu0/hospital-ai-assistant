import { useEffect, useState } from 'react'
import { Form, Input, Button, message, Divider } from 'antd'
import { SaveOutlined, CheckOutlined } from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import api from '@/services/api'
import VoiceInputCard from './VoiceInputCard'
import VitalSignsInput, { ParsedVitals } from './VitalSignsInput'

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
  const { inquiry, setInquiry, updateInquiryFields, currentEncounterId, currentPatient, recordContent, setRecordContent, setPendingGenerate, inquirySavedAt } = useWorkbenchStore()
  const isFemale = currentPatient?.gender === 'female'
  const [isDirty, setIsDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [parsedVitals, setParsedVitals] = useState<ParsedVitals | undefined>(undefined)

  const parseVitalsFromText = (text: string): ParsedVitals => {
    const v: ParsedVitals = {}
    const tM = text.match(/(?:体温|T)[:\s：]*(\d+\.?\d*)\s*℃/i)
    if (tM) v.t = tM[1]
    const pM = text.match(/(?:脉搏|P)[:\s：]*(\d+)\s*次/i)
    if (pM) v.p = pM[1]
    const rM = text.match(/(?:呼吸|R)[:\s：]*(\d+)\s*次/i)
    if (rM) v.r = rM[1]
    const bpM = text.match(/(?:血压|BP)[:\s：]*(\d+)\s*\/\s*(\d+)/i)
    if (bpM) { v.bpS = bpM[1]; v.bpD = bpM[2] }
    const spo2M = text.match(/SpO[₂2][:\s：]*(\d+)\s*%/i)
    if (spo2M) v.spo2 = spo2M[1]
    const hM = text.match(/身高[:\s：]*(\d+\.?\d*)\s*cm/i)
    if (hM) v.h = hM[1]
    const wM = text.match(/体重[:\s：]*(\d+\.?\d*)\s*kg/i)
    if (wM) v.w = wM[1]
    return v
  }

  // 切换接诊时、或 reset 后（inquirySavedAt 归零）同步表单
  useEffect(() => {
    form.setFieldsValue(inquiry)
    setIsDirty(false)
  }, [form, currentEncounterId, inquirySavedAt])

  // 外部更新某些字段时同步到表单（如检验报告插入、建议面板回填），不影响 dirty 状态
  useEffect(() => {
    const current = form.getFieldValue('auxiliary_exam') || ''
    if (inquiry.auxiliary_exam !== current) {
      form.setFieldValue('auxiliary_exam', inquiry.auxiliary_exam || '')
    }
  }, [inquiry.auxiliary_exam])

  useEffect(() => {
    const current = form.getFieldValue('history_present_illness') || ''
    if (inquiry.history_present_illness !== current) {
      form.setFieldValue('history_present_illness', inquiry.history_present_illness || '')
      setIsDirty(true)
    }
  }, [inquiry.history_present_illness])

  useEffect(() => {
    const current = form.getFieldValue('initial_impression') || ''
    if (inquiry.initial_impression !== current) {
      form.setFieldValue('initial_impression', inquiry.initial_impression || '')
      setIsDirty(true)
    }
  }, [inquiry.initial_impression])

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

    // 找出本次修改的字段
    const changedFields: Record<string, string> = {}
    const fieldKeys: (keyof typeof data)[] = [
      'chief_complaint', 'history_present_illness', 'past_history',
      'allergy_history', 'personal_history', 'menstrual_history',
      'physical_exam', 'auxiliary_exam', 'initial_impression',
    ]
    for (const key of fieldKeys) {
      const val = (data[key] ?? '') as string
      if (val && val !== (inquiry[key] ?? '')) changedFields[key] = val
    }

    // 病历为空时跳过规范化，直接走一键生成（避免双重AI调用）
    const isFirstGeneration = !recordContent.trim()

    // AI 规范化修改过的字段（仅在病历已有内容时执行，避免和一键生成重复）
    let normalizedData = { ...data }
    if (!isFirstGeneration && Object.keys(changedFields).length > 0) {
      try {
        const res: any = await api.post('/ai/normalize-fields', { fields: changedFields })
        if (res?.fields) {
          normalizedData = { ...data, ...res.fields }
          // 把规范化后的值更新到表单显示
          form.setFieldsValue(res.fields)
        }
      } catch { /* 失败时用原值，不阻塞保存 */ }
    }

    setInquiry(normalizedData)
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, normalizedData).catch(() => {})
    }
    // 只同步本次实际修改的字段到病历对应段落
    if (recordContent) {
      const fieldMap: [string, string, keyof typeof normalizedData][] = [
        ['【主诉】', normalizedData.chief_complaint, 'chief_complaint'],
        ['【现病史】', normalizedData.history_present_illness, 'history_present_illness'],
        ['【既往史】', normalizedData.past_history, 'past_history'],
        ['【过敏史】', normalizedData.allergy_history || '', 'allergy_history'],
        ['【个人史】', normalizedData.personal_history || '', 'personal_history'],
        ['【月经史】', normalizedData.menstrual_history || '', 'menstrual_history'],
        ['【体格检查】', normalizedData.physical_exam, 'physical_exam'],
        ['【辅助检查】', normalizedData.auxiliary_exam || '', 'auxiliary_exam'],
        ['【初步诊断】', normalizedData.initial_impression, 'initial_impression'],
      ]
      let updated = recordContent
      for (const [header, value, fieldKey] of fieldMap) {
        // 跳过未修改的字段，避免覆盖医生在病历里的手动编辑
        if (!changedFields[fieldKey]) continue
        if (!value) continue
        if (updated.includes(header)) {
          // 章节已存在 → 替换内容
          updated = updated.replace(
            new RegExp(`${header}[^\\S\\n]*\\n?[\\s\\S]*?(?=\\n【|$)`),
            `${header}\n${value}`
          )
        } else if (header === '【辅助检查】') {
          // 辅助检查章节不存在 → 插入到【初步诊断】前，或追加到末尾
          if (updated.includes('【初步诊断】')) {
            updated = updated.replace('【初步诊断】', `【辅助检查】\n${value}\n\n【初步诊断】`)
          } else {
            updated = updated.trimEnd() + `\n\n【辅助检查】\n${value}`
          }
        }
      }
      if (updated !== recordContent) setRecordContent(updated)
    }
    // 病历为空时自动触发生成
    if (!recordContent.trim() && data.chief_complaint) {
      setPendingGenerate(true)
    }
    message.success({ content: '问诊信息已保存', duration: 1.5 })
    setIsDirty(false)
    setSaving(false)
  }

  const applyVoiceInquiry = (patch: any) => {
    const nextValues = { ...form.getFieldsValue(), ...patch }
    form.setFieldsValue(nextValues)
    updateInquiryFields(buildData(nextValues))  // 不更新 inquirySavedAt，不触发 AI 建议
    if (patch.physical_exam) {
      setParsedVitals(parseVitalsFromText(patch.physical_exam))
    }
    setIsDirty(true)  // 需要手动点保存才同步到病历
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
          <VitalSignsInput onFill={handleVitalFill} parsedVitals={parsedVitals} />

          <Form.Item style={fieldStyle} name="physical_exam"
            label={<span style={labelStyle}>体格检查</span>}>
            <TextArea rows={4} placeholder="生命体征、各系统体检结果..." style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Form.Item
            style={fieldStyle}
            name="auxiliary_exam"
            label={<span style={labelStyle}>辅助检查</span>}
          >
            <TextArea rows={3} placeholder="已有检查结果，或切换到上方「检验报告」Tab 上传报告后插入..." style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
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
          {isDirty ? '保存问诊信息' : '已保存'}
        </Button>
      </div>
    </div>
  )
}
