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
import type { VisitType } from '@/domain/medical'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import {
  useActiveEncounterStore,
  useCurrentPatient,
  resetAllWorkbench,
  setCurrentEncounterFromPatient,
} from '@/store/activeEncounterStore'
import { applyQuickStartResult } from '@/store/encounterIntake'
import { usePatientProfileEditStore } from '@/store/patientProfileEditStore'
import api from '@/services/api'
import { applyVoiceToRecordWithFeedback } from '@/utils/inquiryUtils'
import { INQUIRY_FORM_FIELDS, buildInquiryData, syncInquiryToRecord } from '@/utils/inquirySync'

export function useInquiryPanel() {
  const [form] = Form.useForm()
  const navigate = useNavigate()
  // 拆分后从子 store 读字段：
  //   inquiry / record 各管自己的；接诊上下文走 activeEncounterStore；
  //   currentPatient 通过 useCurrentPatient 聚合 patientCache + activeEncounter
  const { inquiry, setInquiry, updateInquiryFields, inquirySavedAt } = useInquiryStore()
  const { recordContent, setRecordContent, setPendingGenerate, isPolishing, isFinal } =
    useRecordStore()
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const isFirstVisit = useActiveEncounterStore(s => s.isFirstVisit)
  const isPatientReused = useActiveEncounterStore(s => s.isPatientReused)
  const currentVisitType = useActiveEncounterStore(s => s.visitType)
  const patchActive = useActiveEncounterStore(s => s.patchActive)
  const currentPatient = useCurrentPatient()
  // 兼容封装：保留原 hook 暴露给 InquiryPanel 的 setVisitMeta 形状
  const setVisitMeta = (firstVisit: boolean, vt: string) =>
    patchActive({ isFirstVisit: firstVisit, visitType: vt as VisitType })

  // 润色期间 recordContent 会短暂清空，isPolishing 防止表单闪烁解锁
  const isInputLocked = !!recordContent.trim() || isPolishing
  const isEmergency = currentVisitType === 'emergency'

  const [isDirty, setIsDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  // 保存后的患者去向，用于驱动急诊流转提示
  const [savedDisposition, setSavedDisposition] = useState<string>('')

  // 切换接诊或 inquirySavedAt 更新时全量同步表单
  useEffect(() => {
    form.setFieldsValue({
      ...inquiry,
      visit_time: inquiry.visit_time ? dayjs(inquiry.visit_time, 'YYYY-MM-DD HH:mm') : dayjs(),
      onset_time: inquiry.onset_time ? dayjs(inquiry.onset_time, 'YYYY-MM-DD HH:mm') : null,
    })
    // inquirySavedAt=0 且有数据说明是刷新前填了但未保存，保持 dirty 提示用户保存
    if (inquirySavedAt === 0 && inquiry.chief_complaint) {
      setIsDirty(true)
    } else {
      setIsDirty(false)
    }
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

  const onSave = async (values: any) => {
    setSaving(true)
    const data = buildInquiryData(values)

    // 找出本次新增或修改的字段，用于 AI 规范化和病历章节同步
    const changedFields: Record<string, string> = {}
    for (const key of INQUIRY_FORM_FIELDS) {
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

    setInquiry(normalizedData as any)
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, normalizedData).catch(() => {})
    }

    // 将已改动的字段同步到右侧病历对应章节
    // 既往/过敏/个人/月经史 已迁到 PatientProfileCard，由其保存时单独同步章节
    if (recordContent) {
      const updated = syncInquiryToRecord(recordContent, normalizedData, changedFields)
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
      resetAllWorkbench()
      // 1.6 数据接入：把住院 quick-start 的 patient + profile 写入新 store
      applyQuickStartResult(res)
      // 一次性写入接诊指针 + 元信息（visitType/firstVisit/previousRecordContent 全在 options 里）
      setCurrentEncounterFromPatient(res.patient, res.encounter_id, {
        visitType: 'inpatient',
        isFirstVisit: false,
        previousRecordContent: emergencyRecord || null,
      })
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
    // AI 返回的 patch 可能含 vital_signs 结构体，铺平到 form 顶层字段
    const flattened = { ...patch }
    if (patch.vital_signs && typeof patch.vital_signs === 'object') {
      Object.assign(flattened, patch.vital_signs)
      delete flattened.vital_signs
    }
    // 1) inquiry 字段填表单（profile 字段交给 form 也无影响，反正没对应 Form.Item）
    const nextValues = { ...form.getFieldsValue(), ...flattened }
    form.setFieldsValue(nextValues)
    updateInquiryFields(buildInquiryData(nextValues) as any)
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

  // 转住院前置条件：有病历草稿但未签发时禁止转住院（A 方案，强制先签发）
  // 原因：转住院会创建新接诊并跳走，未签发的门诊草稿留在原接诊里悬空，
  // 既污染待办列表也让责任界限模糊。等医生测试后再评估是否放宽。
  const hasUnsignedRecord = !!recordContent.trim() && !isFinal

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
    isPolishing,
    isEmergency,
    isDirty,
    setIsDirty,
    saving,
    onSave,
    applyVoiceInquiry,
    applyVoiceToRecord,
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
    /** 当前接诊患者（供子组件按 patient_id 拉数据用，如影像报告） */
    currentPatient,
    /** 是否存在未签发的病历草稿（转住院按钮的前置条件） */
    hasUnsignedRecord,
  }
}
