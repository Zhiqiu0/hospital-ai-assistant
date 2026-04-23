/**
 * 住院问诊面板逻辑（hooks/useInpatientInquiryPanel.ts）
 * 从 InpatientInquiryPanel 提取的业务逻辑 hook。
 */
import { useEffect, useState } from 'react'
import { Form, message } from 'antd'
import { useWorkbenchStore } from '@/store/workbenchStore'
import { usePatientProfileEditStore } from '@/store/patientProfileEditStore'
import api from '@/services/api'
import { applyVoiceToRecordWithFeedback } from '@/utils/inquiryUtils'

// 1.6.2：8 个 profile 字段（past/allergy/personal/marital/family/menstrual/
// current_medications/religion_belief）已迁出到 PatientProfileCard，本 hook 仅
// 处理"住院本次接诊"字段：主诉/现病史/体格/辅助/入院诊断/专项评估/陈述者
export function useInpatientInquiryPanel() {
  const [form] = Form.useForm()
  const {
    inquiry,
    inquirySavedAt,
    setInquiry,
    updateInquiryFields,
    setPendingGenerate,
    currentEncounterId,
    recordContent,
    setRecordContent,
    isPolishing,
  } = useWorkbenchStore()

  // 润色期间 recordContent 会短暂清空，isPolishing 防止表单闪烁解锁
  const isInputLocked = !!recordContent.trim() || isPolishing
  const [isDirty, setIsDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  // 切换接诊或 inquirySavedAt 更新时全量同步表单
  useEffect(() => {
    form.setFieldsValue({
      chief_complaint: inquiry.chief_complaint,
      history_present_illness: inquiry.history_present_illness,
      physical_exam: inquiry.physical_exam,
      history_informant: inquiry.history_informant,
      rehabilitation_assessment: inquiry.rehabilitation_assessment,
      pain_assessment: inquiry.pain_assessment ? Number(inquiry.pain_assessment) : 0,
      vte_risk: inquiry.vte_risk,
      nutrition_assessment: inquiry.nutrition_assessment,
      psychology_assessment: inquiry.psychology_assessment,
      auxiliary_exam: inquiry.auxiliary_exam,
      admission_diagnosis: inquiry.admission_diagnosis || inquiry.initial_impression,
      // 生命体征 8 字段（结构化独立字段，VitalSignsInput 通过 Form.Item name 绑定）
      temperature: inquiry.temperature,
      pulse: inquiry.pulse,
      respiration: inquiry.respiration,
      bp_systolic: inquiry.bp_systolic,
      bp_diastolic: inquiry.bp_diastolic,
      spo2: inquiry.spo2,
      height: inquiry.height,
      weight: inquiry.weight,
    })
    // inquirySavedAt=0 且有数据说明是刷新前填了但未保存，保持 dirty 提示用户保存
    if (inquirySavedAt === 0 && inquiry.chief_complaint) {
      setIsDirty(true)
    } else {
      setIsDirty(false)
    }
  }, [form, currentEncounterId, inquirySavedAt])

  // 追问建议修改现病史时同步表单并激活保存按钮
  useEffect(() => {
    const current = form.getFieldValue('history_present_illness') || ''
    if (inquiry.history_present_illness !== current) {
      form.setFieldValue('history_present_illness', inquiry.history_present_illness || '')
      setIsDirty(true)
    }
  }, [inquiry.history_present_illness])

  // AI 诊断建议写入 initial_impression 时同步 admission_diagnosis 字段
  useEffect(() => {
    const current = form.getFieldValue('admission_diagnosis') || ''
    const newVal = inquiry.admission_diagnosis || inquiry.initial_impression || ''
    if (newVal !== current) {
      form.setFieldValue('admission_diagnosis', newVal)
      setIsDirty(true)
    }
  }, [inquiry.initial_impression])

  const onSave = async (values: any) => {
    setSaving(true)
    const painScore = values.pain_assessment ?? 0

    // 本次接诊字段：profile 8 字段已迁出，由 PatientProfileCard 单独 PUT
    const inquiryData = {
      chief_complaint: values.chief_complaint || '',
      history_present_illness: values.history_present_illness || '',
      physical_exam: values.physical_exam || '',
      initial_impression: values.admission_diagnosis || '',
      history_informant: values.history_informant || '',
      rehabilitation_assessment: values.rehabilitation_assessment || '',
      pain_assessment: String(painScore),
      vte_risk: values.vte_risk || '',
      nutrition_assessment: values.nutrition_assessment || '',
      psychology_assessment: values.psychology_assessment || '',
      auxiliary_exam: values.auxiliary_exam || '',
      admission_diagnosis: values.admission_diagnosis || '',
      // 生命体征结构化字段
      temperature: values.temperature || '',
      pulse: values.pulse || '',
      respiration: values.respiration || '',
      bp_systolic: values.bp_systolic || '',
      bp_diastolic: values.bp_diastolic || '',
      spo2: values.spo2 || '',
      height: values.height || '',
      weight: values.weight || '',
    }

    // 找出本次修改的字段，用于病历章节同步
    const changedFields = new Set<string>()
    const fieldKeys = [
      'chief_complaint',
      'history_present_illness',
      'physical_exam',
      'history_informant',
      'rehabilitation_assessment',
      'pain_assessment',
      'vte_risk',
      'nutrition_assessment',
      'psychology_assessment',
      'auxiliary_exam',
      'admission_diagnosis',
      'initial_impression',
    ] as const
    for (const key of fieldKeys) {
      const val = (inquiryData[key as keyof typeof inquiryData] ?? '') as string
      if (val && val !== ((inquiry[key as keyof typeof inquiry] ?? '') as string)) {
        changedFields.add(key)
      }
    }

    setInquiry({ ...inquiry, ...inquiryData })
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, inquiryData).catch(() => {})
    }

    // 将已改动的字段同步到右侧病历对应章节
    // profile 字段（既往/过敏/个人/婚育/月经/家族/用药/宗教）章节由 PatientProfileCard 维护
    if (recordContent) {
      const escReg = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const replaceSection = (content: string, header: string, value: string) =>
        content.replace(
          new RegExp(`${escReg(header)}[^\\S\\n]*\\n?[\\s\\S]*?(?=\\n【|$)`),
          `${header}\n${value}`
        )

      const fieldMap: [string, string, string | string[]][] = [
        ['【主诉】', inquiryData.chief_complaint, 'chief_complaint'],
        ['【现病史】', inquiryData.history_present_illness, 'history_present_illness'],
        ['【体格检查】', inquiryData.physical_exam, 'physical_exam'],
        ['【辅助检查（入院前）】', inquiryData.auxiliary_exam || '', 'auxiliary_exam'],
        [
          '【入院诊断】',
          inquiryData.admission_diagnosis || '',
          ['admission_diagnosis', 'initial_impression'],
        ],
      ]

      // 专项评估：仅含住院本次评估字段（用药/宗教已迁出 PatientProfileCard）
      const assessmentKeys = [
        'pain_assessment',
        'rehabilitation_assessment',
        'psychology_assessment',
        'nutrition_assessment',
        'vte_risk',
      ]
      const assessmentChanged = assessmentKeys.some(k => changedFields.has(k))
      const assessmentText = [
        `· 疼痛评估（NRS评分）：${inquiryData.pain_assessment || '0'}分`,
        inquiryData.rehabilitation_assessment
          ? `· 康复需求：${inquiryData.rehabilitation_assessment}`
          : '',
        inquiryData.psychology_assessment ? `· 心理状态：${inquiryData.psychology_assessment}` : '',
        inquiryData.nutrition_assessment ? `· 营养风险：${inquiryData.nutrition_assessment}` : '',
        inquiryData.vte_risk ? `· VTE风险：${inquiryData.vte_risk}` : '',
      ]
        .filter(Boolean)
        .join('\n')

      let updated = recordContent
      for (const [header, value, keys] of fieldMap) {
        const keyArr = Array.isArray(keys) ? keys : [keys]
        if (!keyArr.some(k => changedFields.has(k))) continue
        if (!value || !updated.includes(header)) continue
        updated = replaceSection(updated, header, value)
      }
      if (assessmentChanged && assessmentText && updated.includes('【专项评估】')) {
        updated = replaceSection(updated, '【专项评估】', assessmentText)
      }
      if (updated !== recordContent) setRecordContent(updated)
    }

    // 病历为空且已填主诉时，触发自动生成
    if (!recordContent.trim() && inquiryData.chief_complaint) {
      setPendingGenerate(true)
    }

    message.success({ content: '入院问诊信息已保存', duration: 1.5 })
    setIsDirty(false)
    setSaving(false)
  }

  // 辅助检查文本插入（检验单 / 上传报告回调）
  const handleLabInsert = (text: string) => {
    const current = form.getFieldValue('auxiliary_exam') || ''
    form.setFieldValue('auxiliary_exam', current ? current + '\n' + text : text)
    setIsDirty(true)
  }

  // 问诊模式：语音结构化结果分流入左侧表单 + 患者档案
  // 1.6.3：profile 8 字段路由到 patientProfileEditStore（统一保存按钮再提交），
  // 避免被丢弃；inquiry 字段照旧填表单
  const applyVoiceInquiry = (patch: any) => {
    // AI 返回的 patch 可能含 vital_signs 结构体，铺平到 form 顶层字段
    const flattened = { ...patch }
    if (patch.vital_signs && typeof patch.vital_signs === 'object') {
      Object.assign(flattened, patch.vital_signs)
      delete flattened.vital_signs
    }
    const nextValues = { ...form.getFieldsValue(), ...flattened }
    form.setFieldsValue({
      ...nextValues,
      pain_assessment: nextValues.pain_assessment ? Number(nextValues.pain_assessment) : 0,
      admission_diagnosis: nextValues.admission_diagnosis || nextValues.initial_impression,
    })
    const data = {
      ...inquiry,
      chief_complaint: nextValues.chief_complaint || '',
      history_present_illness: nextValues.history_present_illness || '',
      physical_exam: nextValues.physical_exam || '',
      initial_impression: nextValues.admission_diagnosis || '',
      history_informant: nextValues.history_informant || '',
      rehabilitation_assessment: nextValues.rehabilitation_assessment || '',
      pain_assessment: String(nextValues.pain_assessment ?? 0),
      vte_risk: nextValues.vte_risk || '',
      nutrition_assessment: nextValues.nutrition_assessment || '',
      psychology_assessment: nextValues.psychology_assessment || '',
      auxiliary_exam: nextValues.auxiliary_exam || '',
      admission_diagnosis: nextValues.admission_diagnosis || '',
      // 生命体征结构化字段
      temperature: nextValues.temperature || '',
      pulse: nextValues.pulse || '',
      respiration: nextValues.respiration || '',
      bp_systolic: nextValues.bp_systolic || '',
      bp_diastolic: nextValues.bp_diastolic || '',
      spo2: nextValues.spo2 || '',
      height: nextValues.height || '',
      weight: nextValues.weight || '',
    }
    updateInquiryFields(data)
    setIsDirty(true)

    // profile 字段路由到档案 store
    const { mergedCount } = usePatientProfileEditStore.getState().mergeVoicePatch(patch)
    if (mergedCount > 0) {
      message.info(`已将 ${mergedCount} 项档案信息填入患者档案，请确认后保存`)
    }
  }

  // 追记模式：语音结构化结果写入病历对应章节（锁定后专用）
  const applyVoiceToRecord = (patch: any) => {
    applyVoiceToRecordWithFeedback(recordContent, patch, setRecordContent)
  }

  const painMarks = { 0: '0', 2: '2', 4: '4', 6: '轻中', 8: '重', 10: '10' }

  // 同 useInquiryPanel：用 inquirySavedAt>0 判断"是否曾保存过本接诊问诊"，
  // 让按钮在初始空白状态显示"尚未填写"而非误导性的"已保存"
  const hasSavedInquiry = inquirySavedAt > 0

  // 1.6.3 统一保存：订阅档案 store dirty/saving + 提供 saveAll
  const profileDirty = usePatientProfileEditStore(s => s.isDirty)
  const profileSaving = usePatientProfileEditStore(s => s.saving)

  const saveAll = async () => {
    const { currentPatient } = useWorkbenchStore.getState()
    const profilePromise = profileDirty
      ? usePatientProfileEditStore.getState().save(currentPatient?.id || '')
      : Promise.resolve('noop' as const)
    if (isDirty) form.submit()
    const profileResult = await profilePromise
    if (profileResult === true) {
      message.success({ content: '患者档案已保存', duration: 1.5 })
    }
  }

  return {
    form,
    isInputLocked,
    isDirty,
    setIsDirty,
    saving,
    onSave,
    painMarks,
    handleLabInsert,
    applyVoiceInquiry,
    applyVoiceToRecord,
    hasSavedInquiry,
    profileDirty,
    profileSaving,
    saveAll,
  }
}
