/**
 * 问诊字段 Schema（domain/medical/inquirySchema.ts）
 *
 * 把原来 30+ 平铺字段组织成"字段 → 分组 → 场景可见性"的结构化 schema。
 * 组件通过 getInquiryGroups(scene) 取到该场景要渲染的分组列表。
 *
 * 设计目标：
 *   - 新增/删除字段只改此文件，组件自动适应
 *   - 每个字段知道自己属于"患者档案"还是"本次接诊"（决定调哪个 API）
 *   - 场景（门诊/急诊/住院/中医门诊）可见性由声明决定，不在组件里写 if
 */
import type { VisitType } from './types'

/** 字段归属：patient 字段进 profile API；encounter 字段进 inquiry API */
export type FieldOwner = 'patient' | 'encounter'

/** 字段基本元信息 */
export interface InquiryField {
  key: string
  label: string
  owner: FieldOwner
  /** 多行文本渲染行数（undefined 时用单行 Input） */
  rows?: number
  /** 限定场景；不设则所有场景可见 */
  scenes?: ReadonlyArray<VisitType>
  /** 限定性别；常见于月经史 */
  genderScope?: 'male' | 'female'
  /** 占位文本 */
  placeholder?: string
  /** 是否中医专用（非中医场景隐藏） */
  tcmOnly?: boolean
}

export interface InquiryGroup {
  key: string
  title: string
  /** 默认折叠（长字段组建议 true，核心字段组建议 false） */
  defaultCollapsed?: boolean
  /** 分组限定场景 */
  scenes?: ReadonlyArray<VisitType>
  fields: InquiryField[]
}

// ── 分组定义 ──────────────────────────────────────────────────────────────────
export const INQUIRY_GROUPS: InquiryGroup[] = [
  {
    key: 'chief_history',
    title: '主诉 / 现病史',
    fields: [
      { key: 'chief_complaint', label: '主诉', owner: 'encounter', rows: 2 },
      { key: 'history_present_illness', label: '现病史', owner: 'encounter', rows: 4 },
      { key: 'onset_time', label: '发病时间', owner: 'encounter' },
    ],
  },
  {
    key: 'patient_profile',
    title: '患者档案（跟随患者，复诊自动带入）',
    fields: [
      { key: 'past_history', label: '既往史', owner: 'patient', rows: 2 },
      { key: 'allergy_history', label: '过敏史', owner: 'patient', rows: 1 },
      { key: 'personal_history', label: '个人史', owner: 'patient', rows: 2 },
      { key: 'family_history', label: '家族史', owner: 'patient', rows: 1, scenes: ['inpatient'] },
      { key: 'current_medications', label: '长期用药', owner: 'patient', rows: 2 },
      { key: 'marital_history', label: '婚育史', owner: 'patient', scenes: ['inpatient'] },
      // 月经史已移出档案：是时变信息（每月都变），跟主诉/生命体征一类，
      // 每次接诊重填。在 InpatientInquiryPanel 的"专项评估"段以 inquiry 字段呈现。
      { key: 'religion_belief', label: '宗教信仰', owner: 'patient', scenes: ['inpatient'] },
    ],
  },
  {
    key: 'exams',
    title: '体格检查 / 辅助检查',
    fields: [
      { key: 'physical_exam', label: '体格检查', owner: 'encounter', rows: 3 },
      { key: 'auxiliary_exam', label: '辅助检查', owner: 'encounter', rows: 3 },
    ],
  },
  {
    key: 'tcm',
    title: '中医四诊',
    defaultCollapsed: true,
    scenes: ['outpatient'],
    fields: [
      { key: 'tcm_inspection', label: '望诊', owner: 'encounter', tcmOnly: true },
      { key: 'tcm_auscultation', label: '闻诊', owner: 'encounter', tcmOnly: true },
      { key: 'tongue_coating', label: '舌象', owner: 'encounter', tcmOnly: true },
      { key: 'pulse_condition', label: '脉象', owner: 'encounter', tcmOnly: true },
    ],
  },
  {
    key: 'diagnosis',
    title: '诊断意见',
    fields: [
      { key: 'initial_impression', label: '初步印象', owner: 'encounter', rows: 2 },
      {
        key: 'western_diagnosis',
        label: '西医诊断',
        owner: 'encounter',
        scenes: ['outpatient', 'emergency'],
      },
      {
        key: 'tcm_disease_diagnosis',
        label: '中医疾病诊断',
        owner: 'encounter',
        scenes: ['outpatient'],
      },
      {
        key: 'tcm_syndrome_diagnosis',
        label: '中医证候诊断',
        owner: 'encounter',
        scenes: ['outpatient'],
      },
      {
        key: 'admission_diagnosis',
        label: '入院诊断',
        owner: 'encounter',
        scenes: ['inpatient'],
        rows: 2,
      },
    ],
  },
  {
    key: 'treatment',
    title: '治疗意见',
    defaultCollapsed: true,
    scenes: ['outpatient', 'emergency'],
    fields: [
      { key: 'treatment_method', label: '治则治法', owner: 'encounter' },
      { key: 'treatment_plan', label: '处理意见', owner: 'encounter', rows: 2 },
      { key: 'followup_advice', label: '复诊建议', owner: 'encounter' },
      { key: 'precautions', label: '注意事项', owner: 'encounter' },
    ],
  },
  {
    key: 'emergency_only',
    title: '急诊附加',
    scenes: ['emergency'],
    fields: [
      { key: 'observation_notes', label: '留观记录', owner: 'encounter', rows: 3 },
      { key: 'patient_disposition', label: '患者去向', owner: 'encounter' },
    ],
  },
  {
    key: 'inpatient_assessment',
    title: '住院专项评估',
    defaultCollapsed: true,
    scenes: ['inpatient'],
    fields: [
      { key: 'pain_assessment', label: '疼痛评估（NRS）', owner: 'encounter' },
      { key: 'vte_risk', label: 'VTE 风险', owner: 'encounter' },
      { key: 'nutrition_assessment', label: '营养评估', owner: 'encounter' },
      { key: 'psychology_assessment', label: '心理评估', owner: 'encounter' },
      { key: 'rehabilitation_assessment', label: '康复评估', owner: 'encounter' },
      { key: 'history_informant', label: '陈述者', owner: 'encounter' },
    ],
  },
]

// ── 查询工具函数 ──────────────────────────────────────────────────────────────
export function getInquiryGroups(
  scene: VisitType,
  opts: { patientGender?: string; isTcm?: boolean } = {}
): InquiryGroup[] {
  return INQUIRY_GROUPS.filter(g => !g.scenes || g.scenes.includes(scene))
    .map(g => ({
      ...g,
      fields: g.fields.filter(f => isFieldVisible(f, scene, opts)),
    }))
    .filter(g => g.fields.length > 0)
}

function isFieldVisible(
  field: InquiryField,
  scene: VisitType,
  opts: { patientGender?: string; isTcm?: boolean }
): boolean {
  if (field.scenes && !field.scenes.includes(scene)) return false
  if (field.genderScope && opts.patientGender !== field.genderScope) return false
  if (field.tcmOnly && !opts.isTcm) return false
  return true
}

/** 取所有 owner='patient' 的字段 key 列表，用于区分 profile / inquiry */
export function getPatientOwnedFieldKeys(): string[] {
  return INQUIRY_GROUPS.flatMap(g => g.fields)
    .filter(f => f.owner === 'patient')
    .map(f => f.key)
}
