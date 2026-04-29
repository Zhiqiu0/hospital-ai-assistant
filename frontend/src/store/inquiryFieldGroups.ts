/**
 * 问诊字段按场景分组（store/inquiryFieldGroups.ts）
 *
 * 目标（"打地基"路线）：
 *   InquiryData 是 43 字段扁平结构（兼容后端 Pydantic + DB 列 + antd Form 扁平 namePath），
 *   但语义上分属不同 record_type（门诊用中医字段 / 急诊用留观去向 / 住院用专项评估等）。
 *
 *   过去靠"约定"区分——门诊组件不渲染住院字段、住院组件不读中医字段——但 TypeScript 类型层面
 *   `InquiryData` 把所有字段都放一起，编译器无法阻止"门诊代码读了 pain_assessment 这个住院字段"
 *   这种串场 bug。
 *
 *   本文件用 const 数组 + Pick<> 工具类型派生出 record-type 专用子类型——
 *   各场景组件用对应派生类型当 props，编译器编译期就能拦住串场访问。
 *   思路同 GraphQL Fragment / Prisma select / zod schema 派生，但纯 TypeScript 实现，
 *   零依赖、零运行时开销，跟扁平的后端 schema 与 antd Form 完美对齐。
 *
 * 维护原则：
 *   1. 加新 InquiryData 字段必须同步加进至少一个分组（测试会断言"全集 = Σ 分组"）
 *   2. 字段绝不重复出现在两个分组（测试断言无交集）
 *   3. 派生类型组合用 union of typeof X[number]，零运行时代价
 */

import { InquiryData } from './types'

// ─── record_type 联合类型（与后端 NEW_ARCH_RECORD_TYPES 对齐） ──────
//
// 任何接受 record_type 的前端函数都该用这个联合类型，避免拼错时静默路由到
// "住院"分支（pickInquiryByRecordType 的 fallback）。后端有同名白名单，
// 改字段时两端要同步。

/** 病程记录类（住院相关，AI 生成时需要带入"上次病历"作为上下文） */
export const COURSE_RECORD_TYPES = [
  'first_course_record',
  'course_record',
  'senior_round',
  'discharge_record',
  'pre_op_summary',
  'op_record',
  'post_op_record',
] as const

/** 全部支持的 record_type（与后端 NEW_ARCH_RECORD_TYPES 对应） */
export const ALL_RECORD_TYPES = [
  'outpatient',
  'emergency',
  'admission_note',
  ...COURSE_RECORD_TYPES,
] as const

export type RecordType = (typeof ALL_RECORD_TYPES)[number]
export type CourseRecordType = (typeof COURSE_RECORD_TYPES)[number]

/** 路由用：判断是否是病程类（影响 AI 生成是否带入上次病历）。 */
export function isCourseRecordType(rt: string): rt is CourseRecordType {
  return (COURSE_RECORD_TYPES as readonly string[]).includes(rt)
}

// ─── 分组常量（扁平字段名清单，按场景归类） ────────────────────────

/** 元信息：时间、初步印象（跨所有 record_type 共用） */
export const META_FIELDS = ['visit_time', 'onset_time', 'initial_impression'] as const

/** 通用核心问诊字段（任何病历都填） */
export const COMMON_FIELDS = [
  'chief_complaint',
  'history_present_illness',
  'past_history',
  'allergy_history',
  'personal_history',
  'physical_exam',
] as const

/** 生命体征 8 项（数值类，体格检查结构化部分） */
export const VITAL_FIELDS = [
  'temperature',
  'pulse',
  'respiration',
  'bp_systolic',
  'bp_diastolic',
  'spo2',
  'height',
  'weight',
] as const

/** 辅助检查（独立分组，跨场景但有自己的语义） */
export const AUXILIARY_FIELDS = ['auxiliary_exam'] as const

/** 中医四诊：望/闻/舌/脉（仅中医门诊场景使用） */
export const TCM_FOUR_DIAG_FIELDS = [
  'tcm_inspection',
  'tcm_auscultation',
  'tongue_coating',
  'pulse_condition',
] as const

/** 中医诊断三项 + 西医诊断（中医门诊用） */
export const TCM_DIAGNOSIS_FIELDS = [
  'tcm_disease_diagnosis',
  'tcm_syndrome_diagnosis',
  'western_diagnosis',
] as const

/** 治疗意见 4 项（中医门诊场景） */
export const TREATMENT_FIELDS = [
  'treatment_method',
  'treatment_plan',
  'followup_advice',
  'precautions',
] as const

/** 住院档案类（既往的婚育/月经/家族/陈述者） */
export const INPATIENT_PROFILE_FIELDS = [
  'marital_history',
  'menstrual_history',
  'family_history',
  'history_informant',
] as const

/** 住院专项评估 7 项（疼痛/VTE/营养/心理/康复/用药/宗教信仰） */
export const INPATIENT_ASSESSMENT_FIELDS = [
  'current_medications',
  'rehabilitation_assessment',
  'religion_belief',
  'pain_assessment',
  'vte_risk',
  'nutrition_assessment',
  'psychology_assessment',
] as const

/** 住院诊断（独立于门诊 initial_impression） */
export const INPATIENT_DIAGNOSIS_FIELDS = ['admission_diagnosis'] as const

/** 急诊专属：留观记录 + 患者去向 */
export const EMERGENCY_FIELDS = ['observation_notes', 'patient_disposition'] as const

/** 所有分组的列表，供测试断言"全集 = Σ 分组"使用 */
export const ALL_FIELD_GROUPS = [
  META_FIELDS,
  COMMON_FIELDS,
  VITAL_FIELDS,
  AUXILIARY_FIELDS,
  TCM_FOUR_DIAG_FIELDS,
  TCM_DIAGNOSIS_FIELDS,
  TREATMENT_FIELDS,
  INPATIENT_PROFILE_FIELDS,
  INPATIENT_ASSESSMENT_FIELDS,
  INPATIENT_DIAGNOSIS_FIELDS,
  EMERGENCY_FIELDS,
] as const

// ─── Record-Type 专用派生类型（编译期类型保证，零运行时开销） ──────

/** 所有 record_type 共用的基础字段（元信息 + 核心问诊 + 生命体征 + 辅查） */
type BaseInquiryKeys =
  | (typeof META_FIELDS)[number]
  | (typeof COMMON_FIELDS)[number]
  | (typeof VITAL_FIELDS)[number]
  | (typeof AUXILIARY_FIELDS)[number]

/**
 * 门诊（中医）问诊数据：基础 + 中医四诊 + 中医诊断 + 治疗意见。
 *
 * 在门诊组件里写 `inquiry.pain_assessment` 编译器会立刻报错：
 * "Property 'pain_assessment' does not exist on type 'OutpatientInquiry'"。
 */
export type OutpatientInquiry = Pick<
  InquiryData,
  | BaseInquiryKeys
  | (typeof TCM_FOUR_DIAG_FIELDS)[number]
  | (typeof TCM_DIAGNOSIS_FIELDS)[number]
  | (typeof TREATMENT_FIELDS)[number]
>

/**
 * 急诊问诊数据：基础 + 急诊专属 + 治疗（急诊处置共用 treatment_plan）。
 *
 * 急诊场景不输出中医四诊；用此类型当 props 编译期阻止读 tongue_coating 等。
 */
export type EmergencyInquiry = Pick<
  InquiryData,
  BaseInquiryKeys | (typeof EMERGENCY_FIELDS)[number] | 'treatment_plan'
>

/**
 * 住院问诊数据：基础 + 住院档案 + 专项评估 + 住院诊断。
 *
 * 用此类型当 props 编译期阻止读中医/急诊字段。
 */
export type InpatientInquiry = Pick<
  InquiryData,
  | BaseInquiryKeys
  | (typeof INPATIENT_PROFILE_FIELDS)[number]
  | (typeof INPATIENT_ASSESSMENT_FIELDS)[number]
  | (typeof INPATIENT_DIAGNOSIS_FIELDS)[number]
>

// ─── Selector 函数（运行时按场景挑字段子集） ────────────────────────
//
// 字段清单 hoist 到模块级 const——每次 AI 请求都新建一遍 spread 数组属于
// 重复劳动；这里固化下来，selector 函数只做"按 keys 取值"。

const OUTPATIENT_KEYS = [
  ...META_FIELDS,
  ...COMMON_FIELDS,
  ...VITAL_FIELDS,
  ...AUXILIARY_FIELDS,
  ...TCM_FOUR_DIAG_FIELDS,
  ...TCM_DIAGNOSIS_FIELDS,
  ...TREATMENT_FIELDS,
] as const

const EMERGENCY_KEYS = [
  ...META_FIELDS,
  ...COMMON_FIELDS,
  ...VITAL_FIELDS,
  ...AUXILIARY_FIELDS,
  ...EMERGENCY_FIELDS,
  'treatment_plan',
] as const

const INPATIENT_KEYS = [
  ...META_FIELDS,
  ...COMMON_FIELDS,
  ...VITAL_FIELDS,
  ...AUXILIARY_FIELDS,
  ...INPATIENT_PROFILE_FIELDS,
  ...INPATIENT_ASSESSMENT_FIELDS,
  ...INPATIENT_DIAGNOSIS_FIELDS,
] as const

/**
 * 通用 selector：按字段名清单从 InquiryData 挑出子集。
 *
 * 类型签名是 `Partial<Pick<...>>` 而非 `Pick<...>`：因为 InquiryData 字段
 * 大多是 optional，运行时取出来的值可能是 undefined。返回 Partial<> 让
 * 调用方在使用时显式处理 undefined，比谎称 required 然后跑出 undefined 安全。
 *
 * 同时过滤 undefined 值——只把"实际有值的字段"放进结果，spread 进 payload
 * 时不会用 undefined 覆盖后端默认值。
 */
function pickFields<K extends keyof InquiryData>(
  inquiry: InquiryData,
  keys: readonly K[]
): Partial<Pick<InquiryData, K>> {
  const result: Partial<Pick<InquiryData, K>> = {}
  for (const key of keys) {
    const value = inquiry[key]
    if (value !== undefined) {
      result[key] = value
    }
  }
  return result
}

/** 取门诊场景所需字段子集 */
export function pickOutpatientInquiry(inquiry: InquiryData): Partial<OutpatientInquiry> {
  return pickFields(inquiry, OUTPATIENT_KEYS)
}

/** 取急诊场景所需字段子集 */
export function pickEmergencyInquiry(inquiry: InquiryData): Partial<EmergencyInquiry> {
  return pickFields(inquiry, EMERGENCY_KEYS)
}

/** 取住院场景所需字段子集 */
export function pickInpatientInquiry(inquiry: InquiryData): Partial<InpatientInquiry> {
  return pickFields(inquiry, INPATIENT_KEYS)
}

/**
 * 按 record_type 路由到对应 selector，取该场景的字段子集。
 *
 * 用于发请求 / AI 生成 payload 构造——把"全 43 字段透传"改成
 * "按场景取必要字段"，类型 + 行为双重保证不串场到后端。
 *
 * 入参用 RecordType 联合类型——拼错的字符串编译期就报错，
 * 不会再静默 fallback 到住院分支。
 */
export function pickInquiryByRecordType(
  recordType: RecordType,
  inquiry: InquiryData
): Partial<InquiryData> {
  if (recordType === 'emergency') return pickEmergencyInquiry(inquiry)
  if (recordType === 'outpatient') return pickOutpatientInquiry(inquiry)
  // 住院 + 7 个病程类共用 InpatientInquiry——同一份住院档案 + 评估 + 诊断
  return pickInpatientInquiry(inquiry)
}
