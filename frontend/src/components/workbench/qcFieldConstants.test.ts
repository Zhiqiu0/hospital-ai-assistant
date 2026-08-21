/**
 * qcFieldConstants 字段映射常量表自检测试
 *
 * 2026-06-11 自 qcFieldMaps.test.ts（787 行超标）按被测模块拆分而来，测试内容零改动。
 * 本文件覆盖 FIELD_TO_LINE_PREFIX 常量表的完整性自检：
 * 英文键齐全 / whole_line 模式标记 / 中英文别名一一对应。
 */
import { describe, expect, it, test } from 'vitest'
import { FIELD_TO_LINE_PREFIX } from './qcFieldMaps'
import { supplementableIssues } from './qcFieldConstants'

// ─── 契约一致性自检：确保 FIELD_TO_LINE_PREFIX 表完整 ────────────────

describe('FIELD_TO_LINE_PREFIX 自检', () => {
  test('12 个英文键全部存在（含 physical_exam_vitals）', () => {
    const expected = [
      'physical_exam_vitals',
      'tcm_inspection',
      'tcm_auscultation',
      'tongue_coating',
      'pulse_condition',
      'pain_assessment',
      'vte_risk',
      'nutrition_assessment',
      'psychology_assessment',
      'rehabilitation_assessment',
      'current_medications',
      'religion_belief',
    ]
    for (const key of expected) {
      expect(FIELD_TO_LINE_PREFIX[key]).toBeDefined()
    }
  })

  test('physical_exam_vitals 必须用 whole_line 模式（fix_text 自带 T:/P:/R:/BP: 前缀）', () => {
    expect(FIELD_TO_LINE_PREFIX.physical_exam_vitals.mode).toBe('whole_line')
    expect(FIELD_TO_LINE_PREFIX.生命体征.mode).toBe('whole_line')
  })

  test('每个英文键都有对应中文别名（防止 LLM 返回中文 fieldName 时漏匹配）', () => {
    const aliases: Record<string, string> = {
      physical_exam_vitals: '生命体征',
      tcm_inspection: '望诊',
      tcm_auscultation: '闻诊',
      tongue_coating: '舌象',
      pulse_condition: '脉象',
      pain_assessment: '疼痛评估',
      vte_risk: 'VTE风险评估',
      nutrition_assessment: '营养评估',
      psychology_assessment: '心理评估',
      rehabilitation_assessment: '康复评估',
      current_medications: '当前用药',
      religion_belief: '宗教信仰',
    }
    for (const [en, cn] of Object.entries(aliases)) {
      expect(FIELD_TO_LINE_PREFIX[cn]).toEqual(FIELD_TO_LINE_PREFIX[en])
    }
  })
})

describe('supplementableIssues 补全范围收口（2026-08-22 终验实锤）', () => {
  it('剔除 LLM 建议/医保风险/首页提示，只留法定扣分项', () => {
    const issues = [
      { source: 'rule', issue_type: 'rubric', field_name: '注意事项' },
      { source: 'llm', issue_type: 'quality', field_name: '治疗意见及措施' },
      { source: 'rule', issue_type: 'insurance', field_name: '用药' },
      { source: 'rule', issue_type: 'frontpage_hint', field_name: '出院诊断' },
    ]
    const out = supplementableIssues(issues)
    expect(out).toHaveLength(1)
    expect(out[0].field_name).toBe('注意事项')
  })
})
