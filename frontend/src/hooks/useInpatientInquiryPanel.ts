/**
 * 住院问诊面板逻辑（hooks/useInpatientInquiryPanel.ts）
 *
 * 从 InpatientInquiryPanel 提取的业务逻辑 hook。
 * Audit Round 4 M6 拆分：
 *   - 字段构建 / changed-fields 计算 / 病历章节同步 / 语音 patch 铺平 → utils/inpatientInquirySync.ts
 *   - 本 hook 仅留 React 状态 + Form 编排 + 副作用 + API 调度
 */
import { useEffect, useState } from 'react'
import { Form, message } from 'antd'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { usePatientProfileEditStore } from '@/store/patientProfileEditStore'
import api from '@/services/api'
import { applyVoiceToRecordWithFeedback } from '@/utils/inquiryUtils'
import {
  buildInpatientInquiryData,
  diffInpatientChangedFields,
  flattenVoicePatch,
  syncInpatientToRecord,
} from '@/utils/inpatientInquirySync'

// 1.6.2：8 个 profile 字段（past/allergy/personal/marital/family/menstrual/
// current_medications/religion_belief）已迁出到 PatientProfileCard，本 hook 仅
// 处理"住院本次接诊"字段：主诉/现病史/体格/辅助/入院诊断/专项评估/陈述者
export function useInpatientInquiryPanel() {
  const [form] = Form.useForm()
  const { inquiry, inquirySavedAt, setInquiry, updateInquiryFields } = useInquiryStore()
  const { recordContent, setRecordContent, setPendingGenerate, isPolishing } = useRecordStore()
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)

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

    // 本次接诊字段：profile 8 字段已迁出，由 PatientProfileCard 单独 PUT
    const inquiryData = buildInpatientInquiryData(values)
    const changedFields = diffInpatientChangedFields(inquiryData, inquiry)

    setInquiry({ ...inquiry, ...inquiryData })
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, inquiryData).catch(() => {})
    }

    // 把已改动的字段同步到右侧病历对应章节（profile 字段章节由 PatientProfileCard 维护）
    if (recordContent) {
      const updated = syncInpatientToRecord(recordContent, inquiryData, changedFields)
      if (updated !== recordContent) setRecordContent(updated)
    }

    // 病历为空且已填主诉时，触发自动生成（门诊也是这套逻辑）
    if (!recordContent.trim() && inquiryData.chief_complaint) {
      setPendingGenerate(true)
    }

    message.success({ content: '入院问诊信息已保存', duration: 1.5 })
    setIsDirty(false)
    setSaving(false)
  }

  // 问诊模式：语音结构化结果分流入左侧表单 + 患者档案
  // 1.6.3：profile 8 字段路由到 patientProfileEditStore（统一保存按钮再提交），
  // 避免被丢弃；inquiry 字段照旧填表单
  const applyVoiceInquiry = (patch: any) => {
    const flattened = flattenVoicePatch(patch)
    const nextValues = { ...form.getFieldsValue(), ...flattened }
    form.setFieldsValue({
      ...nextValues,
      pain_assessment: nextValues.pain_assessment ? Number(nextValues.pain_assessment) : 0,
      admission_diagnosis: nextValues.admission_diagnosis || nextValues.initial_impression,
    })
    const data = { ...inquiry, ...buildInpatientInquiryData(nextValues) }
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
    // 必填校验守卫：跟门诊端对齐，避免"必填没填也算保存成功 + 病历自动生成 → 字段
    // 变灰再也填不进去"的连锁 bug。详见 useInquiryPanel.saveAll 同步注释。
    if (isDirty) {
      try {
        await form.validateFields()
      } catch (errInfo: any) {
        const first = errInfo?.errorFields?.[0]
        if (first?.name) {
          form.scrollToField(first.name, { behavior: 'smooth', block: 'center' })
          setTimeout(() => {
            const inst: any = form.getFieldInstance(first.name)
            inst?.focus?.()
          }, 300)
        }
        message.error(first?.errors?.[0] || '请补全必填项后再保存')
        return
      }
    }
    // 当前患者 ID 走 activeEncounterStore；详情对象不需要，直接拿 ID 调 profile save
    const patientId = useActiveEncounterStore.getState().patientId || ''
    const profilePromise = profileDirty
      ? usePatientProfileEditStore.getState().save(patientId)
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
    applyVoiceInquiry,
    applyVoiceToRecord,
    hasSavedInquiry,
    profileDirty,
    profileSaving,
    saveAll,
  }
}
