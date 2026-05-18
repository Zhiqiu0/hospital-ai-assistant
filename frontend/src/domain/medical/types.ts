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
  /** 是否有进行中的住院接诊；驱动"在院中"绿色 Tag */
  has_active_inpatient?: boolean | null
  /** 是否曾经住过院（含已出院）；区分"已出院"(true) vs "纯门诊从未住过院"(false) */
  has_any_inpatient_history?: boolean | null
  // ── 病案首页扩展字段（2026-05-16 新增） ────────────────────────────────
  // 后端 PatientResponse 已暴露完整字段，前端用于渲染查看/打印/导出顶部首页
  id_card?: string | null
  address?: string | null
  ethnicity?: string | null
  marital_status?: string | null
  occupation?: string | null
  workplace?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  contact_relation?: string | null
  blood_type?: string | null
}

/**
 * 病案首页快照（PatientSnapshot）
 *
 * 合规级要求：病历签发那一刻，把患者+医生+科室+就诊时间冻结进 medical_records.patient_snapshot
 * JSONB 字段。之后患者档案的改动、医生调岗、科室合并都不会改写历史病历首页。
 * 查看/导出/打印病历时，前端优先用 patient_snapshot；为空（旧记录）才回落到当前 patient。
 */
export interface PatientSnapshot {
  // 患者人口学
  name?: string | null
  gender?: string | null // 后端原样存："男"/"女"/"未知"
  birth_date?: string | null
  patient_no?: string | null
  id_card?: string | null
  phone?: string | null
  address?: string | null
  ethnicity?: string | null
  marital_status?: string | null
  occupation?: string | null
  workplace?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  contact_relation?: string | null
  blood_type?: string | null
  // 就诊
  visit_type?: VisitType | string | null
  visit_time?: string | null
  bed_no?: string | null
  // 医生 / 科室
  doctor_name?: string | null
  doctor_id?: string | null
  department_name?: string | null
}

// ── PatientProfile (Longitudinal Record，JSONB 重构后) ──────────────────────
/**
 * 单字段元数据：何时更新 / 谁更新（FHIR verificationStatus 思路）。
 * 后端用 JSONB 字段级存储，前端展示"X 天前由某医生确认"。
 */
export interface ProfileFieldMeta {
  updated_at?: string | null // ISO datetime
  updated_by?: string | null // doctor user id
}

export interface PatientProfile {
  past_history?: string | null // 既往史
  allergy_history?: string | null // 过敏史
  family_history?: string | null // 家族史
  personal_history?: string | null // 个人史
  current_medications?: string | null // 长期用药（变化稍快，>30 天前端高亮提示）
  marital_history?: string | null // 婚育史
  religion_belief?: string | null // 宗教信仰
  // 月经史已移除：时变信息，每次接诊在 inquiry_inputs.menstrual_history 重填
  updated_at?: string | null // 各字段最大 updated_at 聚合（兼容旧"档案最后更新于"展示）
  fields_meta?: Record<string, ProfileFieldMeta> | null // 字段级元数据
}

/** 档案字段名清单（共 7 个，月经史已剔除） */
export const PROFILE_FIELD_KEYS = [
  'past_history',
  'allergy_history',
  'family_history',
  'personal_history',
  'current_medications',
  'marital_history',
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
  /** 病案首页快照（签发那一刻冻结的患者+医生+科室+就诊信息）。旧记录可能为 null */
  patient_snapshot?: PatientSnapshot | null
}
