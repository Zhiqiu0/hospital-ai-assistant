/**
 * 门诊/急诊问诊面板逻辑（hooks/useInquiryPanel.ts）
 *
 * 从 InquiryPanel 提取的业务逻辑 hook。
 * 2026-06-11 Round 5.5 拆分（纯搬家不改逻辑，门面签名与返回值结构不变）：
 *   - 表单初始化与字段同步（useEffect 组）→ inquiryPanel/useInquiryFormSync.ts
 *   - 保存逻辑（AI 规范化 + 病历章节同步 + 统一保存）→ inquiryPanel/useInquirySave.ts
 *   - 急诊流转（转住院 / 留观追记）→ inquiryPanel/useEmergencyFlow.ts
 *   - 语音录入处理（填表 / 追记病历）→ inquiryPanel/useVoiceIntake.ts
 *   - 本门面保留：store 订阅 + 派生状态 + 子 hook 组装
 */
import { useState } from 'react'
import { Form } from 'antd'
import type { VisitType } from '@/domain/medical'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { useActiveEncounterStore, useCurrentPatient } from '@/store/activeEncounterStore'
import { usePatientProfileEditStore } from '@/store/patientProfileEditStore'
import { useInquiryFormSync } from './inquiryPanel/useInquiryFormSync'
import { useInquirySave } from './inquiryPanel/useInquirySave'
import { useEmergencyFlow } from './inquiryPanel/useEmergencyFlow'
import { useVoiceIntake } from './inquiryPanel/useVoiceIntake'

export function useInquiryPanel() {
  const [form] = Form.useForm()
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

  // 表单初始化与字段同步副作用（接诊切换 / store 字段被外部写入时同步表单）
  useInquiryFormSync({ form, inquiry, currentEncounterId, inquirySavedAt, setIsDirty })

  // 1.6.3 统一保存：让组件订阅档案 store 的 dirty/saving，组合成统一按钮态
  const profileDirty = usePatientProfileEditStore(s => s.isDirty)
  const profileSaving = usePatientProfileEditStore(s => s.saving)

  // 保存逻辑（onSave / saveAll + saving / savedDisposition 状态）
  const { saving, savedDisposition, onSave, saveAll } = useInquirySave({
    form,
    inquiry,
    setInquiry,
    currentEncounterId,
    recordContent,
    setRecordContent,
    setPendingGenerate,
    isEmergency,
    isDirty,
    setIsDirty,
    profileDirty,
    currentPatient,
  })

  // 急诊流转动作（转住院 / 留观追记）
  const { handleAdmitToInpatient, handleAddObservationNote } = useEmergencyFlow({
    currentPatient,
    recordContent,
    setRecordContent,
  })

  // 语音录入处理（问诊填表 / 追记病历）
  const { applyVoiceInquiry, applyVoiceToRecord } = useVoiceIntake({
    form,
    updateInquiryFields,
    setIsDirty,
    recordContent,
    setRecordContent,
  })

  // 就诊类型标签颜色和文字
  const visitNatureColor = isFirstVisit ? '#2563eb' : '#7c3aed'
  const visitTypeLabel = currentVisitType === 'emergency' ? '急诊' : '门诊'
  const visitTypeColor = currentVisitType === 'emergency' ? '#dc2626' : '#0284c7'

  // 是否曾经保存过本次接诊的问诊：inquirySavedAt 在 setInquiry 时被打戳，
  // 0 表示从未保存。用于让"保存"按钮在未保存状态下显示"尚未填写"而非误导
  // 性的"已保存"。恢复接诊时 setInquiry(snapshot) 也会打戳，符合预期。
  const hasSavedInquiry = inquirySavedAt > 0

  // 转住院前置条件：有病历草稿但未签发时禁止转住院（A 方案，强制先签发）
  // 原因：转住院会创建新接诊并跳走，未签发的门诊草稿留在原接诊里悬空，
  // 既污染待办列表也让责任界限模糊。等医生测试后再评估是否放宽。
  const hasUnsignedRecord = !!recordContent.trim() && !isFinal

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
