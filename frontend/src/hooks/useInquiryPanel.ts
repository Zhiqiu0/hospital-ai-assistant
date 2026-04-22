/**
 * 门诊/急诊问诊面板逻辑（hooks/useInquiryPanel.ts）
 *
 * 从 InquiryPanel 提取的业务逻辑 hook，包含：
 *   - 表单初始化与字段同步（useEffect）
 *   - 保存逻辑（AI 规范化 + 病历章节同步）
 *   - 语音录入处理（填表 / 追记病历）
 *   - 生命体征快填处理
 */
import { useEffect, useState } from 'react'
import { Form, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { useWorkbenchStore } from '@/store/workbenchStore'
import { applyQuickStartResult } from '@/store/encounterIntake'
import { usePatientProfileEditStore } from '@/store/patientProfileEditStore'
import api from '@/services/api'
import { mergeVitalText, applyVoiceToRecordWithFeedback } from '@/utils/inquiryUtils'
import type { ParsedVitals } from '@/components/workbench/VitalSignsInput'

// 门诊问诊表单"本次接诊"字段（不含纵向档案字段，那些由 PatientProfileCard 处理）
// past_history / allergy_history / personal_history / menstrual_history 已迁出
const allFields = [
  'chief_complaint',
  'history_present_illness',
  'physical_exam',
  'auxiliary_exam',
  'initial_impression',
  'tcm_inspection',
  'tcm_auscultation',
  'tongue_coating',
  'pulse_condition',
  'western_diagnosis',
  'tcm_disease_diagnosis',
  'tcm_syndrome_diagnosis',
  'treatment_method',
  'treatment_plan',
  'followup_advice',
  'precautions',
  'observation_notes',
  'patient_disposition',
  'visit_time',
  'onset_time',
] as const

export function useInquiryPanel() {
  const [form] = Form.useForm()
  const navigate = useNavigate()
  const {
    inquiry,
    setInquiry,
    updateInquiryFields,
    currentEncounterId,
    currentPatient,
    recordContent,
    setRecordContent,
    setPreviousRecordContent,
    setPendingGenerate,
    inquirySavedAt,
    isFirstVisit,
    isPatientReused,
    currentVisitType,
    setVisitMeta,
    setCurrentEncounter,
    reset,
    isPolishing,
  } = useWorkbenchStore()

  // 润色期间 recordContent 会短暂清空，isPolishing 防止表单闪烁解锁
  const isInputLocked = !!recordContent.trim() || isPolishing
  const isEmergency = currentVisitType === 'emergency'

  const [isDirty, setIsDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [parsedVitals, setParsedVitals] = useState<ParsedVitals | undefined>(undefined)
  // 保存后的患者去向，用于驱动急诊流转提示
  const [savedDisposition, setSavedDisposition] = useState<string>('')

  // 从语音识别文本中解析生命体征数值
  const parseVitalsFromText = (text: string): ParsedVitals => {
    const v: ParsedVitals = {}
    const tM = text.match(/(?:体温|T)[:\s：]*(\d+\.?\d*)\s*℃/i)
    if (tM) v.t = tM[1]
    const pM = text.match(/(?:脉搏|P)[:\s：]*(\d+)\s*次/i)
    if (pM) v.p = pM[1]
    const rM = text.match(/(?:呼吸|R)[:\s：]*(\d+)\s*次/i)
    if (rM) v.r = rM[1]
    const bpM = text.match(/(?:血压|BP)[:\s：]*(\d+)\s*\/\s*(\d+)/i)
    if (bpM) {
      v.bpS = bpM[1]
      v.bpD = bpM[2]
    }
    const spo2M = text.match(/SpO[₂2][:\s：]*(\d+)\s*%/i)
    if (spo2M) v.spo2 = spo2M[1]
    const hM = text.match(/身高[:\s：]*(\d+\.?\d*)\s*cm/i)
    if (hM) v.h = hM[1]
    const wM = text.match(/体重[:\s：]*(\d+\.?\d*)\s*kg/i)
    if (wM) v.w = wM[1]
    return v
  }

  // 切换接诊或 inquirySavedAt 更新时全量同步表单
  useEffect(() => {
    form.setFieldsValue({
      ...inquiry,
      visit_time: inquiry.visit_time ? dayjs(inquiry.visit_time, 'YYYY-MM-DD HH:mm') : dayjs(),
      onset_time: inquiry.onset_time ? dayjs(inquiry.onset_time, 'YYYY-MM-DD HH:mm') : null,
    })
    setIsDirty(false)
  }, [form, currentEncounterId, inquirySavedAt])

  // 辅助检查由外部（如追问建议）写入时同步表单
  useEffect(() => {
    const current = form.getFieldValue('auxiliary_exam') || ''
    if (inquiry.auxiliary_exam !== current) {
      form.setFieldValue('auxiliary_exam', inquiry.auxiliary_exam || '')
    }
  }, [inquiry.auxiliary_exam])

  // 就诊时间从 store 初始化（workspace snapshot 的 visited_at）
  useEffect(() => {
    if (inquiry.visit_time && !form.getFieldValue('visit_time')) {
      form.setFieldValue('visit_time', dayjs(inquiry.visit_time, 'YYYY-MM-DD HH:mm'))
    }
  }, [inquiry.visit_time])

  // 现病史被追问建议修改时同步表单并激活保存按钮
  useEffect(() => {
    const current = form.getFieldValue('history_present_illness') || ''
    if (inquiry.history_present_illness !== current) {
      form.setFieldValue('history_present_illness', inquiry.history_present_illness || '')
      setIsDirty(true)
    }
  }, [inquiry.history_present_illness])

  // AI 诊断建议写入 initial_impression 时同步表单
  useEffect(() => {
    const current = form.getFieldValue('initial_impression') || ''
    if (inquiry.initial_impression !== current) {
      form.setFieldValue('initial_impression', inquiry.initial_impression || '')
      setIsDirty(true)
    }
  }, [inquiry.initial_impression])

  // 将表单值构建为统一的问诊数据对象
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

  // 构建病历【诊断】章节文本
  const buildDiagnosisText = (d: any) => {
    const parts: string[] = []
    if (d.tcm_disease_diagnosis || d.tcm_syndrome_diagnosis) {
      parts.push(
        `中医诊断：${d.tcm_disease_diagnosis || '待明确'} — ${d.tcm_syndrome_diagnosis || '待明确'}`
      )
    }
    if (d.western_diagnosis) parts.push(`西医诊断：${d.western_diagnosis}`)
    return parts.join('\n')
  }

  // 构建病历【治疗意见及措施】章节文本
  const buildTreatmentText = (d: any) => {
    const parts: string[] = []
    if (d.treatment_method) parts.push(`治则治法：${d.treatment_method}`)
    if (d.treatment_plan) parts.push(`处理意见：${d.treatment_plan}`)
    if (d.followup_advice) parts.push(`复诊建议：${d.followup_advice}`)
    if (d.precautions) parts.push(`注意事项：${d.precautions}`)
    return parts.join('\n')
  }

  const onSave = async (values: any) => {
    setSaving(true)
    const data = buildData(values)

    // 找出本次新增或修改的字段，用于 AI 规范化和病历章节同步
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
      } catch {
        /* 规范化失败时继续用原值 */
      }
    }

    setInquiry(normalizedData)
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, normalizedData).catch(() => {})
    }

    // 将已改动的字段同步到右侧病历对应章节
    // 既往/过敏/个人/月经史 已迁到 PatientProfileCard，由其保存时单独同步章节
    if (recordContent) {
      const sectionMap: [string, string, string][] = [
        ['【主诉】', normalizedData.chief_complaint, 'chief_complaint'],
        ['【现病史】', normalizedData.history_present_illness, 'history_present_illness'],
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

    // 病历为空且已填主诉时，触发自动生成
    if (!recordContent.trim() && data.chief_complaint) {
      setPendingGenerate(true)
    }

    // 急诊场景：保存后记录患者去向，驱动流转提示
    if (isEmergency) setSavedDisposition(values.patient_disposition || '')
    message.success({ content: '问诊信息已保存', duration: 1.5 })
    setIsDirty(false)
    setSaving(false)
  }

  // 急诊→住院：保留急诊病历作参考，创建住院接诊并跳转
  const handleAdmitToInpatient = async () => {
    if (!currentPatient) return
    const emergencyRecord = recordContent
    try {
      const res = (await api.post('/encounters/quick-start', {
        patient_id: currentPatient.id,
        patient_name: currentPatient.name,
        visit_type: 'inpatient',
      })) as any
      reset()
      // 1.6 数据接入：把住院 quick-start 的 patient + profile 写入新 store
      applyQuickStartResult(res)
      setCurrentEncounter(
        {
          id: res.patient.id,
          name: res.patient.name,
          gender: res.patient.gender,
          age: res.patient.age,
        },
        res.encounter_id
      )
      setVisitMeta(false, 'inpatient')
      // 把急诊病历带入住院作为参考
      setPreviousRecordContent(emergencyRecord || null)
      navigate('/inpatient')
      message.success(`已为「${res.patient.name}」创建住院接诊`)
    } catch {
      message.error('创建住院接诊失败，请稍后重试')
    }
  }

  // 急诊留观追记：在病历末尾插入带时间戳的追记块
  const handleAddObservationNote = () => {
    const timestamp = dayjs().format('YYYY-MM-DD HH:mm')
    const block = `\n\n【留观追记 ${timestamp}】\n[请在此记录病情变化及处理措施]`
    setRecordContent(recordContent + block)
    message.success('已在病历末尾添加留观追记，请在右侧编辑')
  }

  // 问诊模式：语音结构化结果分流入左侧表单 + 患者档案
  // 1.6.3：语音 LLM 输出含 8 个 profile 字段（past/allergy/personal/family/
  // marital/menstrual/current_medications/religion_belief），这些字段属于患者
  // 纵向档案，应路由到 PatientProfileCard（待医生确认后通过统一保存按钮提交），
  // 不再随 inquiry 一起 PUT 到接诊表
  const applyVoiceInquiry = (patch: any) => {
    // 1) inquiry 字段填表单（profile 字段交给 form 也无影响，反正没对应 Form.Item）
    const nextValues = { ...form.getFieldsValue(), ...patch }
    form.setFieldsValue(nextValues)
    updateInquiryFields(buildData(nextValues))
    if (patch.physical_exam) {
      setParsedVitals(parseVitalsFromText(patch.physical_exam))
    }
    setIsDirty(true)

    // 2) profile 字段路由到 patientProfileEditStore
    const { mergedCount } = usePatientProfileEditStore.getState().mergeVoicePatch(patch)
    if (mergedCount > 0) {
      message.info(`已将 ${mergedCount} 项档案信息填入患者档案，请确认后保存`)
    }
  }

  // 追记模式：语音结构化结果写入病历对应章节（锁定后专用）
  const applyVoiceToRecord = (patch: any) => {
    applyVoiceToRecordWithFeedback(recordContent, patch, setRecordContent)
  }

  // 生命体征快填：合并或前插到 physical_exam 第一行
  const handleVitalFill = (vitalText: string) => {
    const newVal = mergeVitalText(form.getFieldValue('physical_exam') || '', vitalText)
    form.setFieldValue('physical_exam', newVal)
    updateInquiryFields({ ...inquiry, physical_exam: newVal })
    setIsDirty(true)
  }

  // 就诊类型标签颜色和文字
  const visitNatureColor = isFirstVisit ? '#2563eb' : '#7c3aed'
  const visitTypeLabel = currentVisitType === 'emergency' ? '急诊' : '门诊'
  const visitTypeColor = currentVisitType === 'emergency' ? '#dc2626' : '#0284c7'

  // 是否曾经保存过本次接诊的问诊：inquirySavedAt 在 setInquiry 时被打戳，
  // 0 表示从未保存。用于让"保存"按钮在未保存状态下显示"尚未填写"而非误导
  // 性的"已保存"。恢复接诊时 setInquiry(snapshot) 也会打戳，符合预期。
  const hasSavedInquiry = inquirySavedAt > 0

  // 1.6.3 统一保存：让组件订阅档案 store 的 dirty/saving，组合成统一按钮态
  const profileDirty = usePatientProfileEditStore(s => s.isDirty)
  const profileSaving = usePatientProfileEditStore(s => s.saving)

  /**
   * 统一保存：profile dirty 时调 PUT /patients/:id/profile；
   * inquiry dirty 时调 form.submit()（触发 onSave → PUT /encounters/:id/inquiry）。
   * 两个动作并发执行，互不阻塞。
   */
  const saveAll = async () => {
    const profilePromise = profileDirty
      ? usePatientProfileEditStore.getState().save(currentPatient?.id || '')
      : Promise.resolve('noop' as const)
    if (isDirty) form.submit() // form.submit 走 onSave 异步链路，不需要 await
    const profileResult = await profilePromise
    if (profileResult === true) {
      message.success({ content: '患者档案已保存', duration: 1.5 })
    }
    // inquiry 的 toast 由 onSave 内部弹；profile === 'noop' / false 不再额外弹
  }

  return {
    form,
    isInputLocked,
    isEmergency,
    isDirty,
    setIsDirty,
    saving,
    parsedVitals,
    onSave,
    applyVoiceInquiry,
    applyVoiceToRecord,
    handleVitalFill,
    visitNatureColor,
    visitTypeLabel,
    visitTypeColor,
    isFirstVisit,
    isPatientReused,
    currentVisitType,
    setVisitMeta,
    inquiry,
    updateInquiryFields,
    savedDisposition,
    handleAdmitToInpatient,
    handleAddObservationNote,
    hasSavedInquiry,
    /** 档案是否有未保存改动（来自 patientProfileEditStore） */
    profileDirty,
    /** 档案保存进行中 */
    profileSaving,
    /** 统一保存按钮调用入口 */
    saveAll,
  }
}
