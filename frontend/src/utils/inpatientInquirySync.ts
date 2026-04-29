/**
 * 住院问诊面板字段构建 + 病历章节同步（utils/inpatientInquirySync.ts）
 *
 * 抽出来供 useInpatientInquiryPanel 使用，与 utils/inquirySync.ts（门诊版本）一一对应。
 * 原 hook 内联了 buildData / 章节正则替换 / voice patch 铺平 几段纯函数逻辑，
 * 与 AI/state 编排混在一起 —— 抽出后 hook 主体只剩 React 状态/Form/effect 编排。
 *
 * Audit Round 4 M6 拆分。
 */

/**
 * 住院"本次接诊"字段集合（不含 PatientProfile 纵向 8 字段：
 * past/allergy/personal/marital/family/menstrual/current_medications/religion_belief
 * — 这些已迁到 PatientProfileCard 单独 PUT /patients/:id/profile）。
 */
export const INPATIENT_INQUIRY_KEYS = [
  'chief_complaint',
  'history_present_illness',
  'physical_exam',
  'history_informant',
  'rehabilitation_assessment',
  'pain_assessment',
  'vte_risk',
  'nutrition_assessment',
  'psychology_assessment',
  'auxiliary_exam',
  'admission_diagnosis',
  'initial_impression',
] as const

/** 写入病历同步时关心的字段集合（用于"本次哪些字段改了"对比）。 */
export const INPATIENT_CHANGE_TRACK_KEYS: ReadonlyArray<keyof InpatientInquiryData> = [
  'chief_complaint',
  'history_present_illness',
  'physical_exam',
  'history_informant',
  'rehabilitation_assessment',
  'pain_assessment',
  'vte_risk',
  'nutrition_assessment',
  'psychology_assessment',
  'auxiliary_exam',
  'admission_diagnosis',
  'initial_impression',
]

export interface InpatientInquiryData {
  chief_complaint: string
  history_present_illness: string
  physical_exam: string
  initial_impression: string
  history_informant: string
  rehabilitation_assessment: string
  /** NRS 评分以字符串形式入库，前端展示用数字 */
  pain_assessment: string
  vte_risk: string
  nutrition_assessment: string
  psychology_assessment: string
  auxiliary_exam: string
  admission_diagnosis: string
  // 生命体征（结构化独立字段）
  temperature: string
  pulse: string
  respiration: string
  bp_systolic: string
  bp_diastolic: string
  spo2: string
  height: string
  weight: string
}

/**
 * 把 antd Form 的 values 转成扁平 InpatientInquiryData。
 * 关键：admission_diagnosis 同时回填到 initial_impression（兼容旧字段）。
 */
export function buildInpatientInquiryData(values: Record<string, any>): InpatientInquiryData {
  const painScore = values.pain_assessment ?? 0
  return {
    chief_complaint: values.chief_complaint || '',
    history_present_illness: values.history_present_illness || '',
    physical_exam: values.physical_exam || '',
    initial_impression: values.admission_diagnosis || '',
    history_informant: values.history_informant || '',
    rehabilitation_assessment: values.rehabilitation_assessment || '',
    pain_assessment: String(painScore),
    vte_risk: values.vte_risk || '',
    nutrition_assessment: values.nutrition_assessment || '',
    psychology_assessment: values.psychology_assessment || '',
    auxiliary_exam: values.auxiliary_exam || '',
    admission_diagnosis: values.admission_diagnosis || '',
    temperature: values.temperature || '',
    pulse: values.pulse || '',
    respiration: values.respiration || '',
    bp_systolic: values.bp_systolic || '',
    bp_diastolic: values.bp_diastolic || '',
    spo2: values.spo2 || '',
    height: values.height || '',
    weight: values.weight || '',
  }
}

/**
 * 找出本次保存相对原 inquiry 状态发生变化的字段集合（仅 INPATIENT_CHANGE_TRACK_KEYS 内的）。
 * 用于决定"哪些字段触发病历章节同步"，避免未改动的字段也覆盖 AI 已写入内容。
 */
export function diffInpatientChangedFields(
  next: InpatientInquiryData,
  prev: Record<string, any>
): Set<string> {
  const changed = new Set<string>()
  for (const key of INPATIENT_CHANGE_TRACK_KEYS) {
    const nextVal = (next[key] ?? '') as string
    const prevVal = (prev[key] ?? '') as string
    if (nextVal && nextVal !== prevVal) {
      changed.add(key)
    }
  }
  return changed
}

/** 章节级正则替换工具（与 inquirySync 保持一致风格）。 */
const escapeReg = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function replaceSection(content: string, header: string, value: string): string {
  return content.replace(
    new RegExp(`${escapeReg(header)}[^\\S\\n]*\\n?[\\s\\S]*?(?=\\n【|$)`),
    `${header}\n${value}`
  )
}

/**
 * 把已改动的住院字段同步到病历对应章节（正则替换）。
 *
 * 规则：
 *   - 只处理已改的字段（changedFields 集合内）
 *   - 章节存在才替换；章节不存在不新增（避免污染 AI 生成结构）
 *   - profile 8 字段（既往/过敏/个人/婚育/月经/家族/用药/宗教）章节由 PatientProfileCard 维护
 *   - 专项评估（pain/rehab/psychology/nutrition/vte）合并成单条文本，整段替换
 */
export function syncInpatientToRecord(
  recordContent: string,
  data: InpatientInquiryData,
  changedFields: Set<string>
): string {
  if (!recordContent) return recordContent

  const fieldMap: Array<[string, string, string | string[]]> = [
    ['【主诉】', data.chief_complaint, 'chief_complaint'],
    ['【现病史】', data.history_present_illness, 'history_present_illness'],
    ['【体格检查】', data.physical_exam, 'physical_exam'],
    ['【辅助检查（入院前）】', data.auxiliary_exam || '', 'auxiliary_exam'],
    ['【入院诊断】', data.admission_diagnosis || '', ['admission_diagnosis', 'initial_impression']],
  ]

  const assessmentKeys = [
    'pain_assessment',
    'rehabilitation_assessment',
    'psychology_assessment',
    'nutrition_assessment',
    'vte_risk',
  ]
  const assessmentChanged = assessmentKeys.some(k => changedFields.has(k))
  const assessmentText = [
    `· 疼痛评估（NRS评分）：${data.pain_assessment || '0'}分`,
    data.rehabilitation_assessment ? `· 康复需求：${data.rehabilitation_assessment}` : '',
    data.psychology_assessment ? `· 心理状态：${data.psychology_assessment}` : '',
    data.nutrition_assessment ? `· 营养风险：${data.nutrition_assessment}` : '',
    data.vte_risk ? `· VTE风险：${data.vte_risk}` : '',
  ]
    .filter(Boolean)
    .join('\n')

  let updated = recordContent
  for (const [header, value, keys] of fieldMap) {
    const keyArr = Array.isArray(keys) ? keys : [keys]
    if (!keyArr.some(k => changedFields.has(k))) continue
    if (!value || !updated.includes(header)) continue
    updated = replaceSection(updated, header, value)
  }
  if (assessmentChanged && assessmentText && updated.includes('【专项评估】')) {
    updated = replaceSection(updated, '【专项评估】', assessmentText)
  }
  return updated
}

/**
 * 把语音结构化 patch 铺平到 form 顶层字段：vital_signs 子结构展开后不再保留嵌套。
 * 调用方拿到平铺 patch 再走 form.setFieldsValue / setInquiry 流程。
 */
export function flattenVoicePatch(patch: any): Record<string, any> {
  const flattened = { ...patch }
  if (patch?.vital_signs && typeof patch.vital_signs === 'object') {
    Object.assign(flattened, patch.vital_signs)
    delete flattened.vital_signs
  }
  return flattened
}
