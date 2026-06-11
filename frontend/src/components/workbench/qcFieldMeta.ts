/**
 * QC 字段元数据（components/workbench/qcFieldMeta.ts）
 *
 * 2026-06-11 从 qcFieldMaps.ts 拆出，内容零改动。
 * 含：字段→问诊 store 键、字段→中文标签、不可写字段集合与 UI 引导文案。
 */

/** field_name → 问诊 store 中对应的 key */
export const FIELD_TO_INQUIRY_KEY: Record<string, string> = {
  chief_complaint: 'chief_complaint',
  history_present_illness: 'history_present_illness',
  past_history: 'past_history',
  allergy_history: 'allergy_history',
  personal_history: 'personal_history',
  physical_exam: 'physical_exam',
  initial_diagnosis: 'initial_diagnosis',
  initial_impression: 'initial_impression',
  auxiliary_exam: 'auxiliary_exam',
  marital_history: 'marital_history',
  family_history: 'family_history',
  tcm_inspection: 'tcm_inspection',
  tcm_auscultation: 'tcm_auscultation',
  tongue_coating: 'tongue_coating',
  pulse_condition: 'pulse_condition',
  tcm_disease_diagnosis: 'tcm_disease_diagnosis',
  tcm_syndrome_diagnosis: 'tcm_syndrome_diagnosis',
  treatment_method: 'treatment_method',
  treatment_plan: 'treatment_plan',
  western_diagnosis: 'western_diagnosis',
  followup_advice: 'followup_advice',
  precautions: 'precautions',
  admission_diagnosis: 'admission_diagnosis',
  pain_assessment: 'pain_assessment',
  vte_risk: 'vte_risk',
  nutrition_assessment: 'nutrition_assessment',
  psychology_assessment: 'psychology_assessment',
  rehabilitation_assessment: 'rehabilitation_assessment',
  current_medications: 'current_medications',
  religion_belief: 'religion_belief',
  onset_time: 'onset_time',
  主诉: 'chief_complaint',
  现病史: 'history_present_illness',
  既往史: 'past_history',
  过敏史: 'allergy_history',
  个人史: 'personal_history',
  婚育史: 'marital_history',
  月经史: 'menstrual_history',
  家族史: 'family_history',
  体格检查: 'physical_exam',
  初步诊断: 'initial_diagnosis',
  入院诊断: 'admission_diagnosis',
  诊断: 'initial_diagnosis',
  辅助检查: 'auxiliary_exam',
  中医证候诊断: 'tcm_syndrome_diagnosis',
  中医疾病诊断: 'tcm_disease_diagnosis',
  治则治法: 'treatment_method',
  处理意见: 'treatment_plan',
  舌象: 'tongue_coating',
  脉象: 'pulse_condition',
  疼痛评估: 'pain_assessment',
  VTE风险评估: 'vte_risk',
  营养评估: 'nutrition_assessment',
  心理评估: 'psychology_assessment',
  康复评估: 'rehabilitation_assessment',
  当前用药: 'current_medications',
  用药情况: 'current_medications',
  宗教信仰: 'religion_belief',
  起病时间: 'onset_time',
}

/** field_name（英文键）→ 中文显示标签 */
export const FIELD_NAME_LABEL: Record<string, string> = {
  chief_complaint: '主诉',
  history_present_illness: '现病史',
  past_history: '既往史',
  allergy_history: '过敏史',
  personal_history: '个人史',
  physical_exam: '体格检查',
  initial_diagnosis: '初步诊断',
  initial_impression: '初步诊断',
  auxiliary_exam: '辅助检查',
  marital_history: '婚育史',
  family_history: '家族史',
  tcm_inspection: '望诊',
  tcm_auscultation: '闻诊',
  tongue_coating: '舌象',
  pulse_condition: '脉象',
  tcm_disease_diagnosis: '中医疾病诊断',
  tcm_syndrome_diagnosis: '中医证候诊断',
  treatment_method: '治则治法',
  treatment_plan: '处理意见',
  western_diagnosis: '西医诊断',
  followup_advice: '复诊建议',
  precautions: '注意事项',
  admission_diagnosis: '入院诊断',
  // 急诊 + 住院专项评估（补齐，原表缺失）
  observation_notes: '留观记录',
  patient_disposition: '患者去向',
  history_informant: '病史陈述者',
  pain_assessment: '疼痛评估',
  vte_risk: 'VTE风险评估',
  nutrition_assessment: '营养评估',
  psychology_assessment: '心理评估',
  rehabilitation_assessment: '康复评估',
  current_medications: '当前用药',
  religion_belief: '宗教信仰',
  menstrual_history: '月经史',
  // 不可写字段（__xxx__ 内部键）→ 中文显示标签
  // 避免医生看到 "__visit_time__" 这种工程实现细节
  __patient_basic_info__: '患者基础信息',
  __visit_time__: '就诊时间',
  __tcm_four_diagnoses__: '中医四诊',
  __special_assessment__: '专项评估',
}

/**
 * 不可写入病历正文的字段——QC 规则要扣分但修复路径不是改正文章节。
 *
 * 这些字段由 backend/app/services/qc_engine/_writable_fields.py 的
 * NON_WRITABLE_FIELDS 同步过来——后端 target_field 命中这里时，前端 QCIssuePanel：
 *   - 隐藏/禁用"写入病历"按钮
 *   - 显示对应 NON_WRITABLE_HINTS 文案，告诉医生去哪里修
 *
 * L2 契约护栏（2026-05-19）：前后端必须同步维护这份集合，
 * qcFieldMaps.test.ts 会断言所有后端 NON_WRITABLE 都在这里。
 */
// 2026-05-24 治本：删除 __tcm_four_diagnoses__ / __special_assessment__——
// 这些字段在病历正文里有独立子行（望/闻/舌/脉 + 7 项专项评估），
// 旧设计错把它们标 NON_WRITABLE 引导去左侧问诊面板，违反"病历正文是
// 唯一编辑入口"原则。新设计：这些字段在 WRITABLE_FIELDS / FIELD_TO_LINE_PREFIX
// 里走正常行级写入，逐条修复 / 批量补全都能正常工作。
export const NON_WRITABLE_FIELDS = new Set<string>([
  '__patient_basic_info__', // 患者姓名/性别/年龄 → 患者表单（确实不在病历正文）
  '__visit_time__', // 就诊时间 → 病历头部"就诊时间："那行（引导指向病历正文头部）
])

/** 不可写字段对应的 UI 引导文案——医生点修复按钮时显示。 */
export const NON_WRITABLE_HINTS: Record<string, string> = {
  __patient_basic_info__: '此项需在患者档案中补全（姓名/性别/年龄），不在病历正文里',
  __visit_time__: '此项是接诊系统字段，请在病历最上方"就诊时间："那一行直接修改',
}
