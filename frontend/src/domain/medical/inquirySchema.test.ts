/**
 * inquirySchema.test.ts
 * 验证按场景 / 性别 / 中医 过滤字段的正确性
 */
import { describe, it, expect } from 'vitest'
import { getInquiryGroups, getPatientOwnedFieldKeys } from './inquirySchema'

describe('getInquiryGroups', () => {
  it('门诊场景不包含急诊附加分组', () => {
    const groups = getInquiryGroups('outpatient')
    expect(groups.find(g => g.key === 'emergency_only')).toBeUndefined()
  })

  it('急诊场景包含急诊附加分组', () => {
    const groups = getInquiryGroups('emergency')
    expect(groups.find(g => g.key === 'emergency_only')).toBeDefined()
  })

  it('档案分组不再含月经史字段（地基重构：移到接诊问诊侧）', () => {
    // 月经史是时变信息（每月都变），跟主诉/生命体征一类，每次接诊重填。
    // 不属于纵向档案；男性女性都不应在档案里出现。
    const groupsMale = getInquiryGroups('inpatient', { patientGender: 'male' })
    const groupsFemale = getInquiryGroups('inpatient', { patientGender: 'female' })
    expect(
      groupsMale.find(g => g.key === 'patient_profile')?.fields.find(f => f.key === 'menstrual_history')
    ).toBeUndefined()
    expect(
      groupsFemale.find(g => g.key === 'patient_profile')?.fields.find(f => f.key === 'menstrual_history')
    ).toBeUndefined()
  })

  it('非中医场景中医四诊分组被过滤掉', () => {
    const groups = getInquiryGroups('outpatient', { isTcm: false })
    expect(groups.find(g => g.key === 'tcm')).toBeUndefined()
  })

  it('中医场景显示中医四诊分组', () => {
    const groups = getInquiryGroups('outpatient', { isTcm: true })
    const tcm = groups.find(g => g.key === 'tcm')
    expect(tcm).toBeDefined()
    expect(tcm?.fields.length).toBe(4)
  })
})

describe('getPatientOwnedFieldKeys', () => {
  it('只返回 owner=patient 的字段', () => {
    const keys = getPatientOwnedFieldKeys()
    expect(keys).toContain('allergy_history')
    expect(keys).toContain('past_history')
    // 现病史是 encounter 级别，不应在患者档案里
    expect(keys).not.toContain('history_present_illness')
    expect(keys).not.toContain('chief_complaint')
  })
})
