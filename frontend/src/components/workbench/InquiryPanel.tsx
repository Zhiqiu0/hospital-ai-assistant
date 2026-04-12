import { useEffect, useState } from 'react'
import { Form, Input, Button, message, Divider, Radio, Tag, Collapse, Select, DatePicker } from 'antd'
import { SaveOutlined, CheckOutlined, MedicineBoxOutlined, HeartOutlined, BulbOutlined, AlertOutlined, ClockCircleOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useWorkbenchStore } from '@/store/workbenchStore'
import api from '@/services/api'
import VoiceInputCard from './VoiceInputCard'
import VitalSignsInput, { ParsedVitals } from './VitalSignsInput'

const { TextArea } = Input
const { Panel } = Collapse

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: '#475569',
  marginBottom: 4,
  display: 'block',
}

const sectionHeaderStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: '#64748b',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  padding: '6px 0 4px',
}

const fs: React.CSSProperties = { marginBottom: 10 }

export default function InquiryPanel() {
  const [form] = Form.useForm()
  const {
    inquiry, setInquiry, updateInquiryFields,
    currentEncounterId, currentPatient, recordContent, setRecordContent,
    setPendingGenerate, inquirySavedAt,
    isFirstVisit, currentVisitType, setVisitMeta,
  } = useWorkbenchStore()
  const isFemale = currentPatient?.gender === 'female'
  const isEmergency = currentVisitType === 'emergency'
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

  useEffect(() => {
    form.setFieldsValue({
      ...inquiry,
      visit_time: inquiry.visit_time ? dayjs(inquiry.visit_time, 'YYYY-MM-DD HH:mm') : dayjs(),
      onset_time: inquiry.onset_time ? dayjs(inquiry.onset_time, 'YYYY-MM-DD HH:mm') : null,
    })
    setIsDirty(false)
  }, [form, currentEncounterId, inquirySavedAt])

  useEffect(() => {
    const current = form.getFieldValue('auxiliary_exam') || ''
    if (inquiry.auxiliary_exam !== current) {
      form.setFieldValue('auxiliary_exam', inquiry.auxiliary_exam || '')
    }
  }, [inquiry.auxiliary_exam])

  // 就诊时间：从 store 初始化（来自 workspace snapshot 的 visited_at）
  useEffect(() => {
    if (inquiry.visit_time && !form.getFieldValue('visit_time')) {
      form.setFieldValue('visit_time', dayjs(inquiry.visit_time, 'YYYY-MM-DD HH:mm'))
    }
  }, [inquiry.visit_time])

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

  const allFields = [
    'chief_complaint', 'history_present_illness', 'past_history', 'allergy_history',
    'personal_history', 'menstrual_history', 'physical_exam', 'auxiliary_exam', 'initial_impression',
    'tcm_inspection', 'tcm_auscultation', 'tongue_coating', 'pulse_condition',
    'western_diagnosis', 'tcm_disease_diagnosis', 'tcm_syndrome_diagnosis',
    'treatment_method', 'treatment_plan', 'followup_advice', 'precautions',
    'observation_notes', 'patient_disposition',
    'visit_time', 'onset_time',
  ] as const

  const buildData = (values: any) => {
    const data: Record<string, string> = {}
    for (const key of allFields) {
      const val = values[key]
      if (key === 'visit_time' || key === 'onset_time') {
        // DatePicker 返回 dayjs 对象，转为字符串
        data[key] = val ? (typeof val === 'string' ? val : val.format('YYYY-MM-DD HH:mm')) : ''
      } else {
        data[key] = val || ''
      }
    }
    return data as any
  }

  const onSave = async (values: any) => {
    setSaving(true)
    const data = buildData(values)

    const changedFields: Record<string, string> = {}
    for (const key of allFields) {
      const val = data[key] ?? ''
      if (val && val !== ((inquiry as any)[key] ?? '')) changedFields[key] = val
    }

    const isFirstGeneration = !recordContent.trim()

    let normalizedData = { ...data }
    if (!isFirstGeneration && Object.keys(changedFields).length > 0) {
      try {
        const res: any = await api.post('/ai/normalize-fields', { fields: changedFields })
        if (res?.fields) {
          normalizedData = { ...data, ...res.fields }
          form.setFieldsValue(res.fields)
        }
      } catch { /* 失败时用原值 */ }
    }

    setInquiry(normalizedData)
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, normalizedData).catch(() => {})
    }

    // 同步修改字段到病历对应段落
    if (recordContent) {
      const sectionMap: [string, string, string][] = [
        ['【主诉】', normalizedData.chief_complaint, 'chief_complaint'],
        ['【现病史】', normalizedData.history_present_illness, 'history_present_illness'],
        ['【既往史】', normalizedData.past_history, 'past_history'],
        ['【过敏史】', normalizedData.allergy_history || '', 'allergy_history'],
        ['【个人史】', normalizedData.personal_history || '', 'personal_history'],
        ['【月经史】', normalizedData.menstrual_history || '', 'menstrual_history'],
        ['【体格检查】', normalizedData.physical_exam, 'physical_exam'],
        ['【辅助检查】', normalizedData.auxiliary_exam || '', 'auxiliary_exam'],
        ['【诊断】', buildDiagnosisText(normalizedData), 'western_diagnosis'],
        ['【治疗意见及措施】', buildTreatmentText(normalizedData), 'treatment_method'],
      ]
      let updated = recordContent
      for (const [header, value, fieldKey] of sectionMap) {
        if (!changedFields[fieldKey]) continue
        if (!value) continue
        if (updated.includes(header)) {
          updated = updated.replace(
            new RegExp(`${header}[^\\S\\n]*\\n?[\\s\\S]*?(?=\\n【|$)`),
            `${header}\n${value}`
          )
        }
      }
      if (updated !== recordContent) setRecordContent(updated)
    }

    if (!recordContent.trim() && data.chief_complaint) {
      setPendingGenerate(true)
    }
    message.success({ content: '问诊信息已保存', duration: 1.5 })
    setIsDirty(false)
    setSaving(false)
  }

  const buildDiagnosisText = (d: any) => {
    const parts: string[] = []
    if (d.tcm_disease_diagnosis || d.tcm_syndrome_diagnosis) {
      parts.push(`中医诊断：${d.tcm_disease_diagnosis || '待明确'} — ${d.tcm_syndrome_diagnosis || '待明确'}`)
    }
    if (d.western_diagnosis) parts.push(`西医诊断：${d.western_diagnosis}`)
    return parts.join('\n')
  }

  const buildTreatmentText = (d: any) => {
    const parts: string[] = []
    if (d.treatment_method) parts.push(`治则治法：${d.treatment_method}`)
    if (d.treatment_plan) parts.push(`处理意见：${d.treatment_plan}`)
    if (d.followup_advice) parts.push(`复诊建议：${d.followup_advice}`)
    if (d.precautions) parts.push(`注意事项：${d.precautions}`)
    return parts.join('\n')
  }

  const applyVoiceInquiry = (patch: any) => {
    const nextValues = { ...form.getFieldsValue(), ...patch }
    form.setFieldsValue(nextValues)
    updateInquiryFields(buildData(nextValues))
    if (patch.physical_exam) {
      setParsedVitals(parseVitalsFromText(patch.physical_exam))
    }
    setIsDirty(true)
  }

  const handleVitalFill = (vitalText: string) => {
    const current = form.getFieldValue('physical_exam') || ''
    const lines = current.split('\n')
    const firstLine = lines[0] || ''
    const isVitalLine = /^(T:|P:|R:|BP:|SpO|身高:|体重:)/.test(firstLine)
    let mergedLine: string
    if (isVitalLine) {
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
    updateInquiryFields({ ...inquiry, physical_exam: newVal })
    setIsDirty(true)
  }

  const visitNatureColor = isFirstVisit ? '#2563eb' : '#7c3aed'
  const visitTypeLabel = currentVisitType === 'emergency' ? '急诊' : '门诊'
  const visitTypeColor = currentVisitType === 'emergency' ? '#dc2626' : '#0284c7'

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Panel header */}
      <div style={{ padding: '12px 16px 10px', borderBottom: '1px solid #f1f5f9', background: '#fff', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>问诊录入</div>
            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 1 }}>填写后保存，AI自动同步建议</div>
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <Tag color={visitTypeColor} style={{ margin: 0, fontSize: 11 }}>{visitTypeLabel}</Tag>
            <Radio.Group
              size="small"
              value={isFirstVisit}
              onChange={e => { setVisitMeta(e.target.value, currentVisitType); setIsDirty(true) }}
              optionType="button"
              buttonStyle="solid"
            >
              <Radio.Button value={true} style={{ fontSize: 11, padding: '0 8px', height: 24, lineHeight: '22px', borderColor: visitNatureColor, background: isFirstVisit ? visitNatureColor : undefined }}>初诊</Radio.Button>
              <Radio.Button value={false} style={{ fontSize: 11, padding: '0 8px', height: 24, lineHeight: '22px' }}>复诊</Radio.Button>
            </Radio.Group>
          </div>
        </div>
      </div>

      {/* Form */}
      <div style={{ flex: 1, overflow: 'auto', padding: '10px 16px' }}>
        <Form form={form} layout="vertical" size="small" onFinish={onSave} onValuesChange={() => setIsDirty(true)}>
          <VoiceInputCard
            visitType="outpatient"
            getFormValues={() => form.getFieldsValue()}
            onApplyInquiry={applyVoiceInquiry}
          />

          {/* ── 时间信息 ── */}
          <div style={{
            background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8,
            padding: '8px 10px', marginBottom: 10,
            display: 'flex', gap: 10, alignItems: 'flex-start',
          }}>
            <ClockCircleOutlined style={{ color: '#64748b', marginTop: 6, flexShrink: 0 }} />
            <div style={{ flex: 1, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Form.Item
                style={{ marginBottom: 0, flex: '1 1 140px' }}
                name="visit_time"
                label={<span style={{ ...labelStyle, marginBottom: 2 }}>就诊时间 <span style={{ color: '#ef4444' }}>*</span></span>}
              >
                <DatePicker
                  showTime={{ format: 'HH:mm', use12Hours: false }}
                  format="YYYY-MM-DD HH:mm"
                  placeholder="选择就诊时间"
                  style={{ width: '100%', borderRadius: 6, fontSize: 12 }}
                  size="small"
                  onChange={(val) => {
                    const str = val ? val.format('YYYY-MM-DD HH:mm') : ''
                    updateInquiryFields({ ...inquiry, visit_time: str })
                  }}
                />
              </Form.Item>
              <Form.Item
                style={{ marginBottom: 0, flex: '1 1 140px' }}
                name="onset_time"
                label={<span style={{ ...labelStyle, marginBottom: 2 }}>病发时间 <span style={{ color: '#ef4444' }}>*</span></span>}
                rules={[{ required: true, message: '请选择病发时间' }]}
              >
                <DatePicker
                  showTime={{ format: 'HH:mm', use12Hours: false }}
                  format="YYYY-MM-DD HH:mm"
                  placeholder="请选择病发时间"
                  style={{ width: '100%', borderRadius: 6, fontSize: 12 }}
                  size="small"
                  onChange={(val) => {
                    const str = val ? val.format('YYYY-MM-DD HH:mm') : ''
                    updateInquiryFields({ ...inquiry, onset_time: str })
                  }}
                />
              </Form.Item>
            </div>
          </div>

          {/* ── 基础问诊 ── */}
          <Form.Item
            style={fs}
            name="chief_complaint"
            rules={[{ required: true, message: '请输入主诉' }]}
            label={<span style={labelStyle}>主诉 <span style={{ color: '#ef4444' }}>*</span></span>}
          >
            <TextArea
              rows={2}
              placeholder={isFirstVisit ? '症状 + 持续时间，如：发热伴咳嗽3天' : '本次就诊原因，可含诊断名称，如：高血压复诊'}
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
            />
          </Form.Item>

          <Form.Item style={fs} name="history_present_illness"
            label={<span style={labelStyle}>现病史 <span style={{ color: '#ef4444' }}>*</span></span>}>
            {!isFirstVisit && (
              <div style={{
                display: 'flex', alignItems: 'flex-start', gap: 6,
                background: '#fffbeb', border: '1px solid #fcd34d',
                borderRadius: 6, padding: '6px 10px', marginBottom: 6,
                fontSize: 12, color: '#92400e', lineHeight: 1.5,
              }}>
                <span style={{ fontSize: 14, flexShrink: 0 }}>⚠️</span>
                <span><b>复诊必填：</b>须记录上次治疗后症状改变情况（好转／无变化／加重），否则质控不通过。</span>
              </div>
            )}
            <TextArea rows={isFirstVisit ? 4 : 5}
              placeholder={isFirstVisit
                ? '起病经过、主要症状体征、诊治经过、一般情况（饮食/睡眠/二便）'
                : '【必填】上次治疗后症状变化：好转/无变化/加重；本次主要症状；一般情况（饮食/睡眠/二便）'}
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Form.Item style={fs} name="past_history"
            rules={[{ required: true, message: '请填写既往史，无特殊病史可填写「既往体质可」' }]}
            label={<span style={labelStyle}>既往史 <span style={{ color: '#ef4444' }}>*</span></span>}>
            <TextArea rows={2} placeholder="既往病史、手术史、传染病史、家族史、长期用药史；无特殊可填「既往体质可」" style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Form.Item style={fs} name="allergy_history"
            rules={[{ required: true, message: '请填写过敏史，无过敏可填写「否认药物及食物过敏史」' }]}
            label={<span style={labelStyle}>过敏史 <span style={{ color: '#ef4444' }}>*</span></span>}>
            <Input placeholder="如：青霉素过敏 / 否认药物及食物过敏史" style={{ borderRadius: 6, fontSize: 13 }} />
          </Form.Item>

          <Form.Item style={fs} name="personal_history"
            rules={[{ required: true, message: '请填写个人史，无特殊可填写「无特殊」' }]}
            label={<span style={labelStyle}>个人史 <span style={{ color: '#ef4444' }}>*</span></span>}>
            <TextArea rows={2} placeholder="吸烟、饮酒、职业、婚育史；无特殊可填「无特殊」" style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          {isFemale && (
            <Form.Item style={fs} name="menstrual_history"
              label={<span style={labelStyle}>月经史 <span style={{ color: '#f59e0b', fontSize: 10 }}>育龄期必填</span></span>}>
              <TextArea rows={2} placeholder="初潮年龄、行经天数/间隔天数、末次月经、经量、痛经、生育情况" style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
            </Form.Item>
          )}

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* ── 体格检查 ── */}
          <div style={{ ...sectionHeaderStyle, display: 'flex', alignItems: 'center', gap: 6 }}>
            <HeartOutlined style={{ color: '#0284c7' }} />
            <span>体格检查</span>
          </div>

          {isEmergency && (
            <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '8px 10px', marginBottom: 10 }}>
              <div style={{ fontSize: 11, color: '#dc2626', fontWeight: 600, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
                <AlertOutlined /> 急诊生命体征（必填）
              </div>
              <VitalSignsInput onFill={handleVitalFill} parsedVitals={parsedVitals} />
            </div>
          )}
          {!isEmergency && <VitalSignsInput onFill={handleVitalFill} parsedVitals={parsedVitals} />}

          <Form.Item style={fs} name="physical_exam"
            label={<span style={labelStyle}>一般体检</span>}>
            <TextArea rows={3} placeholder="各系统体检结果、阳性体征、必要阴性体征" style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          {/* ── 中医四诊 ── */}
          <Collapse
            size="small"
            defaultActiveKey={['tcm']}
            style={{ marginBottom: 10, borderRadius: 8, border: '1px solid #bae6fd', background: '#f0f9ff' }}
          >
            <Panel
              key="tcm"
              header={
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <MedicineBoxOutlined style={{ color: '#0284c7' }} />
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#0369a1' }}>中医四诊</span>
                  <span style={{ fontSize: 10, color: '#7dd3fc' }}>望 · 闻 · 问 · 切</span>
                </div>
              }
            >
              <Form.Item style={fs} name="tcm_inspection"
                label={<span style={labelStyle}>望诊（神色形态）</span>}>
                <Input placeholder="如：神清气爽，面色略红，体形中等" style={{ borderRadius: 6, fontSize: 13 }} />
              </Form.Item>

              <Form.Item style={fs} name="tcm_auscultation"
                label={<span style={labelStyle}>闻诊（声音气味）</span>}>
                <Input placeholder="如：语声清晰，无异常气味" style={{ borderRadius: 6, fontSize: 13 }} />
              </Form.Item>

              <Form.Item style={fs} name="tongue_coating"
                label={<span style={{ ...labelStyle, color: '#0369a1' }}>舌象 <span style={{ color: '#ef4444' }}>*</span></span>}>
                <Input placeholder="如：舌淡红，苔薄白；或：舌红苔黄腻" style={{ borderRadius: 6, fontSize: 13 }} />
              </Form.Item>

              <Form.Item style={{ marginBottom: 0 }} name="pulse_condition"
                label={<span style={{ ...labelStyle, color: '#0369a1' }}>脉象 <span style={{ color: '#ef4444' }}>*</span></span>}>
                <Input placeholder="如：脉弦细；或：脉滑数" style={{ borderRadius: 6, fontSize: 13 }} />
              </Form.Item>
            </Panel>
          </Collapse>

          <Form.Item style={fs} name="auxiliary_exam"
            rules={[{ required: true, message: '请填写辅助检查，无检查项目请填写「暂无」' }]}
            label={<span style={labelStyle}>辅助检查 <span style={{ color: '#ef4444' }}>*</span></span>}>
            <TextArea rows={3} placeholder="已有检查结果原样填入；如无检查请填写「暂无」" style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* ── 诊断 ── */}
          <div style={{ ...sectionHeaderStyle, display: 'flex', alignItems: 'center', gap: 6 }}>
            <BulbOutlined style={{ color: '#7c3aed' }} />
            <span>诊断</span>
          </div>

          <div style={{ background: '#faf5ff', border: '1px solid #e9d5ff', borderRadius: 8, padding: '10px 10px 4px', marginBottom: 10 }}>
            <Form.Item style={fs} name="tcm_disease_diagnosis"
              label={<span style={{ ...labelStyle, color: '#7c3aed' }}>中医疾病诊断</span>}>
              <Input placeholder="如：眩晕病、胸痹、感冒" style={{ borderRadius: 6, fontSize: 13 }} />
            </Form.Item>

            <Form.Item style={fs} name="tcm_syndrome_diagnosis"
              label={<span style={{ ...labelStyle, color: '#7c3aed' }}>中医证候诊断</span>}>
              <Input placeholder="如：肝阳上亢证、痰热壅肺证" style={{ borderRadius: 6, fontSize: 13 }} />
            </Form.Item>

            <Form.Item style={{ marginBottom: 4 }} name="western_diagnosis"
              label={<span style={labelStyle}>西医诊断</span>}>
              <Input placeholder="如：高血压3级（极高危），2型糖尿病" style={{ borderRadius: 6, fontSize: 13 }} />
            </Form.Item>
          </div>

          <Form.Item style={fs} name="initial_impression"
            label={<span style={labelStyle}>初步印象（补充）</span>}>
            <Input placeholder="暂时无法明确时的印象或鉴别方向" style={{ borderRadius: 6, fontSize: 13 }} />
          </Form.Item>

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* ── 治疗意见 ── */}
          <div style={{ ...sectionHeaderStyle, display: 'flex', alignItems: 'center', gap: 6 }}>
            <MedicineBoxOutlined style={{ color: '#059669' }} />
            <span>治疗意见及措施</span>
          </div>

          <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: '10px 10px 4px', marginBottom: 10 }}>
            <Form.Item style={fs} name="treatment_method"
              label={<span style={{ ...labelStyle, color: '#059669' }}>治则治法</span>}>
              <Input placeholder="如：平肝潜阳、滋养肝肾；或：清热化痰、止咳平喘" style={{ borderRadius: 6, fontSize: 13 }} />
            </Form.Item>

            <Form.Item style={fs} name="treatment_plan"
              label={<span style={labelStyle}>处理意见</span>}>
              <TextArea rows={3} placeholder="检查建议、用药方案、中医治疗措施（针灸、推拿、中药等）" style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
            </Form.Item>

            <Form.Item style={fs} name="followup_advice"
              label={<span style={labelStyle}>复诊建议 <span style={{ color: '#ef4444' }}>*</span></span>}>
              <Input placeholder="如：2周后复诊，监测血压；如症状加重随时就诊" style={{ borderRadius: 6, fontSize: 13 }} />
            </Form.Item>

            <Form.Item style={{ marginBottom: 4 }} name="precautions"
              label={<span style={labelStyle}>注意事项</span>}>
              <TextArea rows={2} placeholder="饮食、生活方式、服药注意等" style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
            </Form.Item>
          </div>

          {/* ── 急诊附加项 ── */}
          {isEmergency && (
            <>
              <Divider style={{ margin: '8px 0 10px', borderColor: '#fecaca' }} />
              <div style={{ ...sectionHeaderStyle, color: '#dc2626', display: 'flex', alignItems: 'center', gap: 6 }}>
                <AlertOutlined />
                <span>急诊附加项</span>
              </div>

              <Form.Item style={fs} name="observation_notes"
                label={<span style={labelStyle}>留观记录</span>}>
                <TextArea rows={3} placeholder="留观期间病情变化、处理措施..." style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
              </Form.Item>

              <Form.Item style={fs} name="patient_disposition"
                label={<span style={labelStyle}>患者去向</span>}>
                <Select placeholder="选择患者去向" style={{ borderRadius: 6, fontSize: 13 }}>
                  <Select.Option value="回家观察">回家观察</Select.Option>
                  <Select.Option value="留院观察">留院观察</Select.Option>
                  <Select.Option value="收入住院">收入住院</Select.Option>
                  <Select.Option value="转院">转院</Select.Option>
                  <Select.Option value="手术室">手术室</Select.Option>
                </Select>
              </Form.Item>
            </>
          )}
        </Form>
      </div>

      {/* Save button */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid #f1f5f9', background: '#fff', flexShrink: 0 }}>
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
