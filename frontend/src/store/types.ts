/**
 * 工作台 store 共享类型 + 默认值（store/types.ts）
 *
 * Audit Round 4 M1 拆分：
 *   原来 workbenchStore.ts 集所有类型 + 状态 + actions 于一身（415 行上帝对象）。
 *   本文件抽出 5 个子 store 都要用的"纯数据形状"——类型定义 + 默认值常量。
 *   每个子 store 各自负责自己领域的 actions 和 persist 配置。
 *
 * 类型分组：
 *   - InquiryData          : 问诊面板字段（门诊/住院/中医/急诊都填这一张表）
 *   - QCIssue / GradeScore : 质控结果
 *   - ExamSuggestion       : AI 检查建议
 *   - InquirySuggestion    : AI 追问建议
 *   - DiagnosisItem        : AI 诊断建议
 *   - PatientInfo          : 当前接诊的患者信息（从 activeEncounterStore 读取）
 */

/** 问诊数据：门诊+住院+中医+急诊所有字段的并集 */
export interface InquiryData {
  // ── 通用核心字段 ──────────────────────────────────────────
  chief_complaint: string
  history_present_illness: string
  past_history: string
  allergy_history: string
  personal_history: string
  /** 体格检查文字部分（不含生命体征，生命体征单独走结构化字段） */
  physical_exam: string
  initial_impression: string

  // ── 生命体征（结构化字段，原本混在 physical_exam 里）────
  temperature?: string // 体温 ℃
  pulse?: string // 脉搏 次/分
  respiration?: string // 呼吸 次/分
  bp_systolic?: string // 血压收缩压 mmHg
  bp_diastolic?: string // 血压舒张压 mmHg
  spo2?: string // 血氧饱和度 %
  height?: string // 身高 cm
  weight?: string // 体重 kg

  // ── 住院 / 中医 / 复杂场景的扩展字段 ──────────────────────
  marital_history?: string
  menstrual_history?: string
  family_history?: string
  history_informant?: string
  current_medications?: string
  rehabilitation_assessment?: string
  religion_belief?: string
  pain_assessment?: string
  vte_risk?: string
  nutrition_assessment?: string
  psychology_assessment?: string
  auxiliary_exam?: string
  admission_diagnosis?: string

  // ── 中医四诊 ──────────────────────────────────────────────
  tcm_inspection?: string
  tcm_auscultation?: string
  tongue_coating?: string
  pulse_condition?: string

  // ── 中西医诊断细化 ────────────────────────────────────────
  western_diagnosis?: string
  tcm_disease_diagnosis?: string
  tcm_syndrome_diagnosis?: string

  // ── 治疗意见 ──────────────────────────────────────────────
  treatment_method?: string
  treatment_plan?: string
  followup_advice?: string
  precautions?: string

  // ── 急诊附加 ──────────────────────────────────────────────
  observation_notes?: string
  patient_disposition?: string

  // ── 时间字段 ──────────────────────────────────────────────
  visit_time?: string
  onset_time?: string
}

/** 质控问题条目 */
export interface QCIssue {
  /** rule=结构性必须修复，llm=质量建议 */
  source?: 'rule' | 'llm'
  /** completeness | insurance | format | logic 等 */
  issue_type?: string
  risk_level: 'high' | 'medium' | 'low'
  field_name: string
  issue_description: string
  suggestion: string
  score_impact?: string
}

/** 甲级评分 */
export interface GradeScore {
  /** 0-100 */
  grade_score: number
  /** 等级语义：
   *   甲级/乙级/丙级 = 分数区间
   *   待整改         = 任意分数 + 存在规则引擎产出的"必须修复"项时的强制等级，
   *                    含义是"病历不可签发"。与分数维度解耦，避免「93分甲级 +
   *                    需修复才可出具」的悖论（2026-04-30）。
   */
  grade_level: '甲级' | '乙级' | '丙级' | '待整改'
  /** 必须修复项数（source=='rule' 的 issue 数量），仅在"待整改"时用于文案显示 */
  must_fix_count?: number
  strengths?: string[]
}

/** AI 诊断建议条目 */
export interface DiagnosisItem {
  name: string
  confidence: 'high' | 'medium' | 'low'
  reasoning: string
  next_steps: string
}

/** AI 检查建议条目 */
export interface ExamSuggestion {
  exam_name: string
  category: 'basic' | 'differential' | 'high_risk'
  reason: string
  /** 医生是否已开单（纯前端标记，刷新不丢失） */
  isOrdered?: boolean
}

/** AI 追问建议条目 */
export interface InquirySuggestion {
  id: string
  text: string
  priority: 'high' | 'medium' | 'low'
  is_red_flag: boolean
  category: string
  options: string[]
  selectedOptions: string[]
}

/** 当前接诊的患者基础信息 */
export interface PatientInfo {
  id: string
  name: string
  gender?: string
  age?: number | null
}

/**
 * 问诊数据默认值（所有字段空字符串/空值）
 *
 * 单独抽出为常量，便于 inquiryStore.reset 和外部 hook 引用，
 * 避免每处都重复写一遍 38 个字段名。
 */
export const defaultInquiry: InquiryData = {
  chief_complaint: '',
  history_present_illness: '',
  past_history: '',
  allergy_history: '',
  personal_history: '',
  physical_exam: '',
  initial_impression: '',
  temperature: '',
  pulse: '',
  respiration: '',
  bp_systolic: '',
  bp_diastolic: '',
  spo2: '',
  height: '',
  weight: '',
  marital_history: '',
  menstrual_history: '',
  family_history: '',
  history_informant: '',
  current_medications: '',
  rehabilitation_assessment: '',
  religion_belief: '',
  pain_assessment: '',
  vte_risk: '',
  nutrition_assessment: '',
  psychology_assessment: '',
  auxiliary_exam: '',
  admission_diagnosis: '',
  tcm_inspection: '',
  tcm_auscultation: '',
  tongue_coating: '',
  pulse_condition: '',
  western_diagnosis: '',
  tcm_disease_diagnosis: '',
  tcm_syndrome_diagnosis: '',
  treatment_method: '',
  treatment_plan: '',
  followup_advice: '',
  precautions: '',
  observation_notes: '',
  patient_disposition: '',
  visit_time: '',
  onset_time: '',
}
