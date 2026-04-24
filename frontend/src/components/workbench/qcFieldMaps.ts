/**
 * QC 字段映射常量 + 记录内容写入工具
 * 供 QCIssuePanel、AISuggestionPanel 等共享使用
 */

/** field_name → 病历中的章节标题（用于定位写入位置）
 *
 * 设计原则：
 *   - 每个 field_name 必须有对应条目，否则 writeSectionToRecord 静默跳过写入
 *   - 专项评估各子项独立成章节，避免写一项覆盖其他子项
 *   - content / onset_time 等非章节字段映射为 ''（跳过写入）
 */
export const FIELD_TO_SECTION: Record<string, string> = {
  // ── 通用必填 ──
  chief_complaint: '【主诉】',
  history_present_illness: '【现病史】',
  past_history: '【既往史】',
  allergy_history: '【过敏史】',
  personal_history: '【个人史】',
  physical_exam: '【体格检查】',
  physical_exam_vitals: '【体格检查】',
  auxiliary_exam: '【辅助检查】',
  onset_time: '', // 时间戳字段，不对应独立章节
  content: '', // 全文类问题，不做章节替换

  // ── 诊断 ──
  initial_diagnosis: '【初步诊断】',
  initial_impression: '【初步诊断】',
  western_diagnosis: '【初步诊断】',
  tcm_diagnosis: '【中医诊断】',
  tcm_syndrome_diagnosis: '【中医诊断】',
  tcm_disease_diagnosis: '【中医诊断】',
  admission_diagnosis: '【入院诊断】',

  // ── 住院通用 ──
  marital_history: '【婚育史】',
  menstrual_history: '【月经史】',
  family_history: '【家族史】',

  // ── 中医四诊 ──
  tcm_inspection: '【望诊】',
  tcm_auscultation: '【闻诊】',
  tongue_coating: '【舌象】',
  pulse_condition: '【脉象】',
  treatment_method: '【治则治法】',

  // ── 治疗意见 & 复诊 ──
  treatment_plan: '【处理意见】',
  followup_advice: '【复诊建议】',
  precautions: '【注意事项】',

  // ── 急诊 ──
  observation_notes: '【留观记录】',
  patient_disposition: '【患者去向】',

  // ── 住院元信息 ──
  history_informant: '【病史陈述者】',

  // ── 住院专项评估（各自独立章节，避免互相覆盖）──
  pain_assessment: '【疼痛评估】',
  vte_risk: '【VTE风险评估】',
  nutrition_assessment: '【营养评估】',
  psychology_assessment: '【心理评估】',
  rehabilitation_assessment: '【康复评估】',
  current_medications: '【当前用药】',
  religion_belief: '【宗教信仰】',

  // ── 中文 field_name 别名（LLM 返回中文键时使用）──
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
  舌象: '【舌象】',
  脉象: '【脉象】',
  望诊: '【望诊】',
  闻诊: '【闻诊】',
  治则治法: '【治则治法】',
  处理意见: '【处理意见】',
  '治疗意见及措施': '【处理意见】',
  复诊建议: '【复诊建议】',
  随访建议: '【复诊建议】',
  注意事项: '【注意事项】',
  留观记录: '【留观记录】',
  患者去向: '【患者去向】',
  病史陈述者: '【病史陈述者】',
  初步诊断: '【初步诊断】',
  入院诊断: '【入院诊断】',
  诊断: '【入院诊断】',
  辅助检查: '【辅助检查】',
  '辅助检查（入院前）': '【辅助检查（入院前）】',
  专项评估: '【专项评估】',
  疼痛评估: '【疼痛评估】',
  VTE风险评估: '【VTE风险评估】',
  营养评估: '【营养评估】',
  心理评估: '【心理评估】',
  康复评估: '【康复评估】',
  当前用药: '【当前用药】',
  宗教信仰: '【宗教信仰】',
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
}

/**
 * 将修复文本写入病历对应章节（找到 header 则替换，找不到则追加）
 *
 * 章节定位策略（优先级递减）：
 *   1. 精确匹配目标 header
 *   2. 关键词模糊匹配：从 header 中提取核心词（去掉「入院」「初步」等修饰词），
 *      在记录中找含有该核心词的章节——自动兼容门诊/住院章节名差异
 *   3. 均未匹配：在末尾追加新章节
 *
 * 字段分 3 类处理：
 *   - primaryHeader === ''       → **明确跳过**（全文类规则，如 content / onset_time）
 *   - primaryHeader === undefined → **fallback 追加**（未映射字段用 fieldName/中文标签当章节名）
 *                                   避免"按了没反应"的静默失败
 *   - 其他                       → 正常走章节定位
 */
export function writeSectionToRecord(content: string, fieldName: string, fixText: string): string {
  const mapped = FIELD_TO_SECTION[fieldName]

  // 明确跳过的字段（全文类）—— 保持原行为
  if (mapped === '') return content

  // 未映射字段：fallback 用 FIELD_NAME_LABEL 或 fieldName 本身当章节标题追加
  // 这样即使漏了映射，内容不会丢，医生至少能在病历末尾看到一条"【XXX】"章节
  const primaryHeader =
    mapped ?? `【${FIELD_NAME_LABEL[fieldName] || fieldName}】`

  // 从章节标题提取核心关键词（去掉「入院」「初步」「（入院前）」等修饰成分）
  const coreKeyword = primaryHeader
    .replace(/[【】]/g, '')
    .replace(/入院|初步|（[^）]*）/g, '')
    .trim()

  // 找到记录里所有章节的位置
  const sectionPattern = /【[^】]+】/g
  const matches: Array<{ index: number; header: string }> = []
  let m: RegExpExecArray | null
  while ((m = sectionPattern.exec(content)) !== null) {
    matches.push({ index: m.index, header: m[0] })
  }

  // 1. 精确匹配
  let targetIdx = matches.findIndex(s => s.header === primaryHeader)
  // 2. 核心关键词模糊匹配
  if (targetIdx === -1 && coreKeyword) {
    targetIdx = matches.findIndex(s => s.header.includes(coreKeyword))
  }

  const header = targetIdx !== -1 ? matches[targetIdx].header : primaryHeader

  // 取消写入（fixText 为空）：只清空章节内容，保留 header
  //（之前是整节删除，导致再次写入时找不到原位置 → 被追加到末尾。Bug 修复 2026-04-25）
  if (!fixText.trim()) {
    if (targetIdx === -1) return content
    const start = matches[targetIdx].index
    const headerEnd = start + matches[targetIdx].header.length
    const end = targetIdx + 1 < matches.length ? matches[targetIdx + 1].index : content.length
    // 保留 header + 一个换行，让再次写入能定位到原位置
    const tail = content.slice(end).replace(/^\s+/, '')
    return content.slice(0, headerEnd) + '\n\n' + (tail ? tail : '')
  }

  // 写入：替换已有章节，或在末尾追加新章节
  if (targetIdx === -1) {
    return content + '\n\n' + header + '\n' + fixText
  }
  const start = matches[targetIdx].index
  const end = targetIdx + 1 < matches.length ? matches[targetIdx + 1].index : content.length
  return content.slice(0, start) + header + '\n' + fixText + '\n' + content.slice(end).trimStart()
}
