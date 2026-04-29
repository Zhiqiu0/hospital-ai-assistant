/**
 * 问诊字段分组测试（store/inquiryFieldGroups.test.ts）
 *
 * 防回归核心：
 *   1. "全集 = Σ 分组" — 加了 InquiryData 字段必须归类到某分组（否则该字段没人能取到）
 *   2. "分组无交集" — 一个字段不能属于两个分组（避免歧义和重复定义）
 *   3. selector 输出字段集严格匹配派生类型 keys
 *   4. 派生类型不能编译期访问到非自己分组的字段（这条由 tsc 保证，不写 runtime 测试）
 */
import { describe, expect, it } from 'vitest'

import { defaultInquiry, InquiryData } from './types'
import {
  ALL_FIELD_GROUPS,
  AUXILIARY_FIELDS,
  COMMON_FIELDS,
  EMERGENCY_FIELDS,
  INPATIENT_ASSESSMENT_FIELDS,
  INPATIENT_DIAGNOSIS_FIELDS,
  INPATIENT_PROFILE_FIELDS,
  META_FIELDS,
  TCM_DIAGNOSIS_FIELDS,
  TCM_FOUR_DIAG_FIELDS,
  TREATMENT_FIELDS,
  VITAL_FIELDS,
  pickEmergencyInquiry,
  pickInpatientInquiry,
  pickOutpatientInquiry,
} from './inquiryFieldGroups'

/** 把所有分组打平成单一字段名集合 */
function flattenGroups(): Set<string> {
  const all = new Set<string>()
  for (const group of ALL_FIELD_GROUPS) {
    for (const key of group) all.add(key)
  }
  return all
}

describe('字段分组完整性 — 全集 = Σ 分组', () => {
  it('所有 InquiryData 字段都必须归类到某个分组', () => {
    const allInquiryFields = new Set(Object.keys(defaultInquiry))
    const groupedFields = flattenGroups()
    const missing = [...allInquiryFields].filter(k => !groupedFields.has(k))
    expect(missing, `这些字段没归类到任何分组：${missing.join(', ')}`).toEqual([])
  })

  it('分组里不能出现 InquiryData 没有的字段', () => {
    const allInquiryFields = new Set(Object.keys(defaultInquiry))
    const groupedFields = flattenGroups()
    const phantom = [...groupedFields].filter(k => !allInquiryFields.has(k))
    expect(phantom, `这些字段名在分组里但 InquiryData 没定义：${phantom.join(', ')}`).toEqual([])
  })

  it('分组之间无字段交集（一个字段不能属于两个分组）', () => {
    const seen = new Map<string, string>()
    const groupNames: Array<[string, readonly string[]]> = [
      ['META', META_FIELDS],
      ['COMMON', COMMON_FIELDS],
      ['VITAL', VITAL_FIELDS],
      ['AUXILIARY', AUXILIARY_FIELDS],
      ['TCM_FOUR_DIAG', TCM_FOUR_DIAG_FIELDS],
      ['TCM_DIAGNOSIS', TCM_DIAGNOSIS_FIELDS],
      ['TREATMENT', TREATMENT_FIELDS],
      ['INPATIENT_PROFILE', INPATIENT_PROFILE_FIELDS],
      ['INPATIENT_ASSESSMENT', INPATIENT_ASSESSMENT_FIELDS],
      ['INPATIENT_DIAGNOSIS', INPATIENT_DIAGNOSIS_FIELDS],
      ['EMERGENCY', EMERGENCY_FIELDS],
    ]
    for (const [name, group] of groupNames) {
      for (const key of group) {
        if (seen.has(key)) {
          throw new Error(`字段 '${key}' 同时属于 ${seen.get(key)} 和 ${name} 两组`)
        }
        seen.set(key, name)
      }
    }
  })
})

describe('selector 行为', () => {
  // 构造一份完整数据用于断言"取出来的子集等于预期 keys"
  const FULL_INQUIRY: InquiryData = {
    ...defaultInquiry,
    chief_complaint: 'cc',
    history_present_illness: 'hp',
    past_history: 'past',
    allergy_history: 'allergy',
    personal_history: 'personal',
    physical_exam: 'pe',
    initial_impression: 'ii',
    temperature: '36.5',
    pulse: '78',
    respiration: '18',
    bp_systolic: '120',
    bp_diastolic: '80',
    spo2: '98',
    height: '170',
    weight: '60',
    auxiliary_exam: 'aux',
    marital_history: 'mar',
    menstrual_history: 'men',
    family_history: 'fam',
    history_informant: 'inf',
    current_medications: 'cm',
    rehabilitation_assessment: 'ra',
    religion_belief: 'rb',
    pain_assessment: 'pa',
    vte_risk: 'vte',
    nutrition_assessment: 'na',
    psychology_assessment: 'psy',
    admission_diagnosis: 'ad',
    tcm_inspection: 'ti',
    tcm_auscultation: 'tau',
    tongue_coating: 'tc',
    pulse_condition: 'pc',
    western_diagnosis: 'wd',
    tcm_disease_diagnosis: 'tdd',
    tcm_syndrome_diagnosis: 'tsd',
    treatment_method: 'tm',
    treatment_plan: 'tp',
    followup_advice: 'fa',
    precautions: 'prec',
    observation_notes: 'on',
    patient_disposition: 'pd',
    visit_time: 'vt',
    onset_time: 'ot',
  }

  it('pickOutpatientInquiry 含中医四诊但不含住院/急诊字段', () => {
    const out = pickOutpatientInquiry(FULL_INQUIRY)
    const keys = Object.keys(out)
    // 应有：中医四诊
    expect(keys).toContain('tongue_coating')
    expect(keys).toContain('tcm_inspection')
    // 应有：治疗意见
    expect(keys).toContain('treatment_method')
    expect(keys).toContain('followup_advice')
    // 不应有：住院专属
    expect(keys).not.toContain('pain_assessment')
    expect(keys).not.toContain('admission_diagnosis')
    // 不应有：急诊专属
    expect(keys).not.toContain('observation_notes')
    expect(keys).not.toContain('patient_disposition')
  })

  it('pickEmergencyInquiry 含急诊去向但不含中医/住院专属', () => {
    const out = pickEmergencyInquiry(FULL_INQUIRY)
    const keys = Object.keys(out)
    expect(keys).toContain('observation_notes')
    expect(keys).toContain('patient_disposition')
    expect(keys).toContain('treatment_plan') // 急诊处置共用 treatment_plan
    // 不应有：中医四诊
    expect(keys).not.toContain('tongue_coating')
    expect(keys).not.toContain('pulse_condition')
    // 不应有：住院评估
    expect(keys).not.toContain('pain_assessment')
    expect(keys).not.toContain('vte_risk')
  })

  it('pickInpatientInquiry 含住院字段但不含中医/急诊专属', () => {
    const out = pickInpatientInquiry(FULL_INQUIRY)
    const keys = Object.keys(out)
    expect(keys).toContain('pain_assessment')
    expect(keys).toContain('admission_diagnosis')
    expect(keys).toContain('marital_history')
    expect(keys).toContain('current_medications')
    // 不应有：中医四诊（住院记录里中医四诊不属于住院档案）
    expect(keys).not.toContain('tongue_coating')
    // 不应有：急诊专属
    expect(keys).not.toContain('observation_notes')
  })

  it('selector 不丢值（取出的字段值跟原 inquiry 一致）', () => {
    const out = pickOutpatientInquiry(FULL_INQUIRY)
    expect(out.chief_complaint).toBe('cc')
    expect(out.tongue_coating).toBe('tc')
    expect(out.treatment_method).toBe('tm')
  })
})
