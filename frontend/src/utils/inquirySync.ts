/**
 * 问诊面板字段构建 + 病历章节同步（utils/inquirySync.ts）
 *
 * 抽出来供 useInquiryPanel 使用。原 hook 内联了 buildData / buildDiagnosisText /
 * buildTreatmentText / 章节正则替换 4 段逻辑，与 AI/state 编排混在一起。
 */
import type { Dayjs } from 'dayjs'

/** 门诊问诊"本次接诊"字段集合（不含 PatientProfile 纵向字段） */
export const INQUIRY_FORM_FIELDS = [
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
  // 生命体征（结构化独立字段，与 physical_exam 文字完全分离）
  'temperature',
  'pulse',
  'respiration',
  'bp_systolic',
  'bp_diastolic',
  'spo2',
  'height',
  'weight',
] as const

/** 把 antd Form 的 values 转成扁平字符串字典；时间字段把 Dayjs 序列化。 */
export function buildInquiryData(values: Record<string, any>): Record<string, string> {
  const data: Record<string, string> = {}
  for (const key of INQUIRY_FORM_FIELDS) {
    const val = values[key]
    if (key === 'visit_time' || key === 'onset_time') {
      // DatePicker 返回 dayjs 对象，转为字符串
      data[key] = val
        ? typeof val === 'string'
          ? val
          : (val as Dayjs).format('YYYY-MM-DD HH:mm')
        : ''
    } else {
      data[key] = val || ''
    }
  }
  return data
}

/** 中医 + 西医诊断合并文本（用于病历【诊断】章节） */
export function buildDiagnosisText(d: Record<string, string>): string {
  const parts: string[] = []
  if (d.tcm_disease_diagnosis || d.tcm_syndrome_diagnosis) {
    parts.push(
      `中医诊断：${d.tcm_disease_diagnosis || '待明确'} — ${d.tcm_syndrome_diagnosis || '待明确'}`
    )
  }
  if (d.western_diagnosis) parts.push(`西医诊断：${d.western_diagnosis}`)
  return parts.join('\n')
}

/** 治则/处理/复诊/注意四件套合并文本（用于病历【治疗意见及措施】章节） */
export function buildTreatmentText(d: Record<string, string>): string {
  const parts: string[] = []
  if (d.treatment_method) parts.push(`治则治法：${d.treatment_method}`)
  if (d.treatment_plan) parts.push(`处理意见：${d.treatment_plan}`)
  if (d.followup_advice) parts.push(`复诊建议：${d.followup_advice}`)
  if (d.precautions) parts.push(`注意事项：${d.precautions}`)
  return parts.join('\n')
}

/**
 * 把已改动的字段同步到病历对应章节（正则替换）。
 *
 * 规则：
 *   - 只处理已改的字段（changedFields[fieldKey] 存在）
 *   - 章节存在才替换；章节不存在不新增（避免污染 AI 生成的结构）
 *   - 既往/过敏/个人/月经史 已迁到 PatientProfileCard，不在这里同步
 */
export function syncInquiryToRecord(
  recordContent: string,
  normalizedData: Record<string, string>,
  changedFields: Record<string, string>
): string {
  const sectionMap: Array<[string, string, string]> = [
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
  return updated
}
