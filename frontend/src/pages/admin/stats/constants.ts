/**
 * 统计页常量映射（admin/stats/constants.ts）
 *
 * 抽出来供 4 个 Tab 共用，避免 StatsPage 容器膨胀。
 */

export const TASK_TYPE_MAP: Record<string, string> = {
  generate: '病历生成',
  polish: '病历润色',
  qc: 'AI质控',
  inquiry: '追问建议',
  exam: '检查建议',
  // 诊断建议（旧的 AI 诊断建议链路，分类汇总时仍会出现）；漏了会直接显示英文 raw 值
  diagnosis: '诊断建议',
  // 2026-08-29 补全：这三类实际在写库（见 log_ai_task 各调用点），此前
  // 看板硬编码 5 类导致它们整类不可见
  exam_suggestion: '检查建议(旧)',
  inquiry_suggestion: '追问建议(旧)',
  supplement_batch: '批量补全',
  // 历史数据里的旧任务类型（2026-08-30 收尾轮生产实况核对补）：现行代码已
  // 不再产生，但 ai_tasks 里存量仍在，改全量渲染后会以英文原文出现在看板上
  qc_scan: 'AI质控(旧)',
}

export const RISK_COLOR: Record<string, string> = {
  high: 'red',
  medium: 'orange',
  low: 'blue',
}

export const RISK_LABEL: Record<string, string> = {
  high: '高风险',
  medium: '中风险',
  low: '低风险',
}

export const ISSUE_TYPE_LABEL: Record<string, string> = {
  completeness: '完整性缺失',
  format: '格式不规范',
  logic: '逻辑问题',
  insurance: '医保风险',
  normality: '规范性',
  consistency: '一致性',
  // QC 引擎在某些规则上回填的是 'quality'（综合质量类别，老规则遗留），
  // 漏掉这个映射会让"质控分析"tab 直接显示英文 raw 值。
  quality: '质量类',
  // 法定评分规则扣分（task_logger 对 source='rule' 的兜底桶）——主力类别，
  // 2026-08-29 补：此前看板硬编码三类，这一类整体不可见
  rubric: '评分规则扣分',
  // 历史 issue_type（2026-08-30 收尾轮生产实况核对补）：现行代码不再产生，
  // 存量 qc_issues 里仍有，全量渲染后会显示英文原文
  logic_consistency: '逻辑一致性',
  standardization: '规范性(旧)',
}

/**
 * field_name → 中文显示标签
 *
 * 用于统计页"高频问题字段 Top 10"和未来的字段维度报表。
 * 与 components/workbench/qcFieldMaps.ts 的 FIELD_TO_SECTION 同源——那个表是写入
 * 用（field_name → 病历章节标题），这个表是显示用（field_name → 纯中文名）。
 * 漏掉一个字段会导致统计页直接显示英文 raw 值，破坏专业感。
 */
export const FIELD_NAME_LABEL: Record<string, string> = {
  chief_complaint: '主诉',
  history_present_illness: '现病史',
  past_history: '既往史',
  allergy_history: '过敏史',
  personal_history: '个人史',
  physical_exam: '体格检查',
  physical_exam_vitals: '生命体征',
  auxiliary_exam: '辅助检查',
  onset_time: '发病时间',
  content: '病历内容',
  initial_diagnosis: '初步诊断',
  initial_impression: '初步印象',
  western_diagnosis: '西医诊断',
  tcm_diagnosis: '中医诊断',
  tcm_syndrome_diagnosis: '中医证候诊断',
  tcm_disease_diagnosis: '中医疾病诊断',
  admission_diagnosis: '入院诊断',
  marital_history: '婚育史',
  menstrual_history: '月经史',
  family_history: '家族史',
  treatment_method: '治则治法',
  treatment_plan: '处理意见',
  followup_advice: '复诊建议',
  precautions: '注意事项',
  observation_notes: '留观记录',
  patient_disposition: '患者去向',
  history_informant: '病史陈述者',
  tcm_inspection: '望诊',
  tcm_auscultation: '闻诊',
  tongue_coating: '舌象',
  pulse_condition: '脉象',
  pain_assessment: '疼痛评估',
  vte_risk: 'VTE风险评估',
  nutrition_assessment: '营养评估',
  psychology_assessment: '心理评估',
  rehabilitation_assessment: '康复需求评估',
  current_medications: '当前用药',
  religion_belief: '宗教信仰',
}
