/**
 * 中医诊断合并行 拆/合 契约对拍测试（2026-08-21 阶段0 收口）。
 *
 * 用例表在 shared/contracts/tcm_diagnosis_cases.json——后端
 * backend/tests/test_tcm_diagnosis_contract.py 读同一份文件。
 * 改契约只改 JSON，哪端实现没跟上哪端的 CI 红。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { splitTcmDiagnosis, mergeTcmDiagnosis } from './tcmDiagnosis'

interface SplitCase {
  input: string
  disease: string
  syndrome: string
  note: string
}
interface MergeCase {
  disease: string
  syndrome: string
  merged: string
  note: string
}

const cases = JSON.parse(
  readFileSync(resolve(__dirname, '../../../../shared/contracts/tcm_diagnosis_cases.json'), 'utf-8')
) as { split_cases: SplitCase[]; merge_cases: MergeCase[] }

describe('中医诊断合并行契约（与后端对拍同一份 JSON）', () => {
  it.each(cases.split_cases.map(c => [c.note, c] as const))('拆分：%s', (_note, c) => {
    expect(splitTcmDiagnosis(c.input)).toEqual({ disease: c.disease, syndrome: c.syndrome })
  })

  it.each(cases.merge_cases.map(c => [c.note, c] as const))('合并：%s', (_note, c) => {
    expect(mergeTcmDiagnosis(c.disease, c.syndrome)).toBe(c.merged)
  })
})
