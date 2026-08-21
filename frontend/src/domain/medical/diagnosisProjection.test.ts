/**
 * 诊断条目→文本投影 契约对拍测试（2026-08-21 阶段1b）。
 * 用例表 shared/contracts/diagnosis_projection_cases.json——后端读同一份。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { renderDiagnosisProjection, composeDiagnosisItems } from './diagnosisProjection'
import type { DiagnosisEntry } from '@/store/diagnosisEntriesStore'

interface Case {
  note: string
  entries: DiagnosisEntry[]
  western_diagnosis: string
  tcm_disease_diagnosis: string
  tcm_syndrome_diagnosis: string
  admission_diagnosis: string
}

const cases = JSON.parse(
  readFileSync(
    resolve(__dirname, '../../../../shared/contracts/diagnosis_projection_cases.json'),
    'utf-8'
  )
).cases as Case[]

describe('诊断投影契约（与后端对拍同一份 JSON）', () => {
  it.each(cases.map(c => [c.note, c] as const))('%s', (_note, c) => {
    expect(renderDiagnosisProjection(c.entries)).toEqual({
      western_diagnosis: c.western_diagnosis,
      tcm_disease_diagnosis: c.tcm_disease_diagnosis,
      tcm_syndrome_diagnosis: c.tcm_syndrome_diagnosis,
      admission_diagnosis: c.admission_diagnosis,
    })
  })
})

describe('composeDiagnosisItems 保存前合成', () => {
  it('西医条目为空而表单文本非空时整段作一条（AI 生成/复诊带入的初始化桥）', () => {
    const items = composeDiagnosisItems([], {
      western: '急性上呼吸道感染',
      tcmDisease: '感冒',
      tcmSyndrome: '风寒束表证',
    })
    expect(items).toHaveLength(3)
    const western = items.find(i => i.category === 'western')!
    expect(western.name).toBe('急性上呼吸道感染')
    expect(western.is_primary).toBe(true)
  })

  it('西医条目非空时以条目为准，忽略表单西医文本（条目是权威）', () => {
    const entries: DiagnosisEntry[] = [
      { category: 'western', name: '高血压病', is_primary: true, sort_order: 0 },
      { category: 'western', name: '高脂血症', is_primary: false, sort_order: 1 },
    ]
    const items = composeDiagnosisItems(entries, { western: '旧文本不该被采用' })
    expect(items.filter(i => i.category === 'western')).toHaveLength(2)
  })

  it('无任何主诊断时自动补：西医优先（与后端规则一致）', () => {
    const items = composeDiagnosisItems(
      [{ category: 'western', name: '湿疹', is_primary: false, sort_order: 0 }],
      { tcmDisease: '湿疮' }
    )
    expect(items.find(i => i.is_primary)!.name).toBe('湿疹')
  })
})
