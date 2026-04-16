/**
 * QC 字段映射常量 + 记录内容写入工具
 * 供 QCIssuePanel、AISuggestionPanel 等共享使用
 */

/** field_name → 病历中的章节标题（用于定位写入位置）*/
export const FIELD_TO_SECTION: Record<string, string> = {
  chief_complaint: '【主诉】',
  history_present_illness: '【现病史】',
  past_history: '【既往史】',
  allergy_history: '【过敏史】',
  personal_history: '【个人史】',
  physical_exam: '【体格检查】',
  physical_exam_vitals: '【体格检查】',
  tcm_diagnosis: '【中医诊断】',
  tcm_syndrome_diagnosis: '【中医诊断】',
  tcm_disease_diagnosis: '【中医诊断】',
  western_diagnosis: '【初步诊断】',
  content: '',
  initial_diagnosis: '【初步诊断】',
  initial_impression: '【初步诊断】',
  auxiliary_exam: '【辅助检查】',
  marital_history: '【婚育史】',
  family_history: '【家族史】',
  主诉: '【主诉】',
  现病史: '【现病史】',
  既往史: '【既往史】',
  过敏史: '【过敏史】',
  个人史: '【个人史】',
  '个人史/婚育史/月经史/家族史': '【个人史】',
  婚育史: '【婚育史】',
  月经史: '【月经史】',
  家族史: '【家族史】',
  体格检查: '【体格检查】',
  初步诊断: '【初步诊断】',
  入院诊断: '【入院诊断】',
  诊断: '【入院诊断】',
  辅助检查: '【辅助检查（入院前）】',
  '辅助检查（入院前）': '【辅助检查（入院前）】',
  专项评估: '【专项评估】',
}

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
}

/**
 * 将修复文本写入病历对应章节（找到 header 则替换，找不到则追加）
 */
export function writeSectionToRecord(content: string, fieldName: string, fixText: string): string {
  const header = FIELD_TO_SECTION[fieldName]
  // content 类字段（全文规则）或未知字段：不做写入
  if (header === undefined || header === '') return content

  const sectionPattern = /【[^】]+】/g
  const matches: Array<{ index: number; header: string }> = []
  let m: RegExpExecArray | null
  while ((m = sectionPattern.exec(content)) !== null) {
    matches.push({ index: m.index, header: m[0] })
  }

  const targetIdx = matches.findIndex(s => s.header === header)

  // 取消写入（fixText 为空）：移除该章节内容
  if (!fixText.trim()) {
    if (targetIdx === -1) return content
    const start = matches[targetIdx].index
    const end = targetIdx + 1 < matches.length ? matches[targetIdx + 1].index : content.length
    return (content.slice(0, start) + content.slice(end)).replace(/\n{3,}/g, '\n\n').trimEnd()
  }

  // 写入：替换或插入章节
  if (targetIdx === -1) {
    return content + '\n\n' + header + '\n' + fixText
  }
  const start = matches[targetIdx].index
  const end = targetIdx + 1 < matches.length ? matches[targetIdx + 1].index : content.length
  return content.slice(0, start) + header + '\n' + fixText + '\n' + content.slice(end).trimStart()
}
