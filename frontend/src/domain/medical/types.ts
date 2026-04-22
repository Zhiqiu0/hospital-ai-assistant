/**
 * 医疗领域通用类型定义（domain/medical/types.ts）
 *
 * 门诊、急诊、住院共用的核心类型。参考 HL7 FHIR 资源模型：
 *   Patient         — 患者本人（人口学信息）
 *   PatientProfile  — 纵向持久档案（过敏/既往/用药等）
 *   Encounter       — 单次接诊/住院（时间有始有终）
 *   MedicalRecord   — 某次接诊下的病历文档
 *
 * 禁止在此文件引入任何 UI 库或业务 hook，保持纯类型层。
 */

// ── Patient ──────────────────────────────────────────────────────────────────
export type Gender = 'male' | 'female' | 'unknown'

export interface Patient {
  id: string
  patient_no?: string | null
  name: string
  gender?: Gender | null
  age?: number | null
  phone?: string | null
  birth_date?: string | null // ISO date
}

// ── PatientProfile (Longitudinal Record) ─────────────────────────────────────
export interface PatientProfile {
  past_history?: string | null // 既往史
  allergy_history?: string | null // 过敏史
  family_history?: string | null // 家族史
  personal_history?: string | null // 个人史
  current_medications?: string | null // 长期用药
  marital_history?: string | null // 婚育史
  menstrual_history?: string | null // 月经史
  religion_belief?: string | null // 宗教信仰
  updated_at?: string | null // 档案最后更新时间 ISO
}

/** 档案字段名清单，便于遍历与序列化 */
export const PROFILE_FIELD_KEYS = [
  'past_history',
  'allergy_history',
  'family_history',
  'personal_history',
  'current_medications',
  'marital_history',
  'menstrual_history',
  'religion_belief',
] as const satisfies ReadonlyArray<keyof PatientProfile>

export type PatientProfileFieldKey = (typeof PROFILE_FIELD_KEYS)[number]

// ── Encounter ────────────────────────────────────────────────────────────────
export type VisitType = 'outpatient' | 'emergency' | 'inpatient'
export type EncounterStatus = 'in_progress' | 'completed' | 'cancelled'

export interface Encounter {
  id: string
  patient_id: string
  doctor_id: string
  visit_type: VisitType
  status: EncounterStatus
  is_first_visit: boolean
  visited_at: string // ISO datetime
  completed_at?: string | null
  // 住院特有
  bed_no?: string | null
  admission_route?: string | null
  admission_condition?: string | null
}

// ── MedicalRecord ────────────────────────────────────────────────────────────
export type RecordStatus = 'draft' | 'submitted'

export interface MedicalRecord {
  id: string
  encounter_id: string
  record_type: string // 使用 recordTypes.ts 里定义的 key
  status: RecordStatus
  current_version: number
  content: string // 规范化后的纯文本
  submitted_at?: string | null
  updated_at?: string | null
}
