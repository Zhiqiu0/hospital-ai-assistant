/**
 * 语音录入处理（hooks/inquiryPanel/useVoiceIntake.ts）
 *
 * 从 useInquiryPanel.ts 拆出（2026-06-11 Round 5.5 拆分），逻辑一字未改：
 *   - applyVoiceInquiry：问诊模式——语音结构化结果分流入左侧表单 + 患者档案
 *   - applyVoiceToRecord：追记模式——语音结构化结果写入病历对应章节（锁定后专用）
 */
import type { FormInstance } from 'antd'
import { message } from '@/services/messageBridge'
import { usePatientProfileEditStore } from '@/store/patientProfileEditStore'
import { applyVoiceToRecordWithFeedback } from '@/utils/inquiryUtils'
import { buildInquiryData } from '@/utils/inquirySync'
import type { InquiryData } from '@/store/types'

interface VoiceIntakeParams {
  form: FormInstance
  updateInquiryFields: (data: InquiryData) => void
  setIsDirty: (v: boolean) => void
  recordContent: string
  setRecordContent: (content: string) => void
}

export function useVoiceIntake({
  form,
  updateInquiryFields,
  setIsDirty,
  recordContent,
  setRecordContent,
}: VoiceIntakeParams) {
  // 问诊模式：语音结构化结果分流入左侧表单 + 患者档案
  // 1.6.3：语音 LLM 输出含 8 个 profile 字段（past/allergy/personal/family/
  // marital/menstrual/current_medications/religion_belief），这些字段属于患者
  // 纵向档案，应路由到 PatientProfileCard（待医生确认后通过统一保存按钮提交），
  // 不再随 inquiry 一起 PUT 到接诊表
  const applyVoiceInquiry = (patch: Record<string, unknown>) => {
    // AI 返回的 patch 可能含 vital_signs 结构体，铺平到 form 顶层字段
    const flattened: Record<string, unknown> = { ...patch }
    if (patch.vital_signs && typeof patch.vital_signs === 'object') {
      Object.assign(flattened, patch.vital_signs as Record<string, unknown>)
      delete flattened.vital_signs
    }
    // 1) inquiry 字段填表单（profile 字段交给 form 也无影响，反正没对应 Form.Item）
    const nextValues = { ...form.getFieldsValue(), ...flattened }
    form.setFieldsValue(nextValues)
    // buildInquiryData 返回的扁平字符串字典与 InquiryData 字段集兼容；
    // 用 unknown 桥接而非 any，避免污染下游签名
    updateInquiryFields(buildInquiryData(nextValues) as unknown as InquiryData)
    setIsDirty(true)

    // 2) profile 字段路由到 patientProfileEditStore
    const { mergedCount } = usePatientProfileEditStore.getState().mergeVoicePatch(patch)
    if (mergedCount > 0) {
      message.info(`已将 ${mergedCount} 项档案信息填入患者档案，请确认后保存`)
    }
  }

  // 追记模式：语音结构化结果写入病历对应章节（锁定后专用）
  const applyVoiceToRecord = (patch: Record<string, unknown>) => {
    applyVoiceToRecordWithFeedback(recordContent, patch, setRecordContent)
  }

  return { applyVoiceInquiry, applyVoiceToRecord }
}
