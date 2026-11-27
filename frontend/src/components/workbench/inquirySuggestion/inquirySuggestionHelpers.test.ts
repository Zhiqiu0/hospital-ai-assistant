/** 诊断建议写入正文的回归用例：规范格式下只改「西医诊断：」子行，不再多出一行无类别的重复诊断。 */
import { describe, expect, it } from 'vitest'
import { applyDiagnosisToRecord } from './inquirySuggestionHelpers'

const RECORD = [
  '【主诉】',
  '头痛3天',
  '',
  '【诊断】',
  '中医诊断：感冒 — 风寒束表证',
  '西医诊断：[未填写，需补充]',
  '',
  '【治疗意见及措施】',
  '治则治法：疏风散寒',
].join('\n')

describe('applyDiagnosisToRecord', () => {
  it('规范格式：只替换西医诊断行，诊断章节不新增无类别行', () => {
    const out = applyDiagnosisToRecord(RECORD, '急性上呼吸道感染')
    expect(out).toContain('西医诊断：急性上呼吸道感染')
    // 诊断名在全文只出现一次（联调实测的重复行就是它出现了两次）
    expect(out.split('急性上呼吸道感染').length - 1).toBe(1)
    // 其余行原样保留
    expect(out).toContain('中医诊断：感冒 — 风寒束表证')
    expect(out).toContain('治则治法：疏风散寒')
  })

  it('撤回写入：恢复为占位符', () => {
    const written = applyDiagnosisToRecord(RECORD, '急性上呼吸道感染')
    expect(applyDiagnosisToRecord(written, '')).toBe(RECORD)
  })

  it('诊断名含 $ 等特殊字符时按字面写入', () => {
    expect(applyDiagnosisToRecord(RECORD, 'A$&B')).toContain('西医诊断：A$&B')
  })

  it('没有西医诊断子行的旧格式：退回章节级写入', () => {
    const legacy = '【主诉】\n头痛3天\n\n【初步诊断】\n[未填写，需补充]'
    const out = applyDiagnosisToRecord(legacy, '偏头痛')
    expect(out).toContain('【初步诊断】')
    expect(out).toContain('偏头痛')
  })
})
