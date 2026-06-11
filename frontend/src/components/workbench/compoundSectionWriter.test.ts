/**
 * 复合段结构化合并写入器单测
 *
 * 覆盖 2026-06-11 E2E 实测复现的 P0 bug：AI 补全对【体格检查】做章节级写入时，
 * 整段替换冲掉医生手填的切诊·舌象/脉象。此处验证合并语义的全部边界。
 */
import { describe, it, expect } from 'vitest'
import { COMPOUND_SECTION_PREFIXES, mergeCompoundSectionBody } from './compoundSectionWriter'
import { writeSectionToRecord } from './qcFieldMaps'

const EXAM_PREFIXES = COMPOUND_SECTION_PREFIXES['【体格检查】']
const DIAG_PREFIXES = COMPOUND_SECTION_PREFIXES['【诊断】']

describe('mergeCompoundSectionBody — 体格检查段', () => {
  const oldBody = [
    '[未填写，需补充]',
    '望诊：[未填写，需补充]',
    '闻诊：[未填写，需补充]',
    '切诊·舌象：舌淡红，苔薄白',
    '切诊·脉象：脉弦细',
    '其余阳性体征：[未填写，需补充]',
  ].join('\n')

  it('纯自由文本写入：只替换段首一般描述，医生手填的舌象/脉象保留', () => {
    const merged = mergeCompoundSectionBody(
      oldBody,
      '神志清，心肺腹查体未见明显异常。',
      EXAM_PREFIXES
    )
    expect(merged).toContain('神志清，心肺腹查体未见明显异常。')
    expect(merged).toContain('切诊·舌象：舌淡红，苔薄白')
    expect(merged).toContain('切诊·脉象：脉弦细')
    expect(merged).not.toContain('[未填写，需补充]\n望诊') // 旧自由文本占位符被替换
  })

  it('带 T: 行的写入（E2E 复现场景）：vitals 行替换，舌脉保留', () => {
    const fix = 'T: 36.5℃，P: 72次/分，R: 18次/分，BP: 130/85mmHg。'
    const merged = mergeCompoundSectionBody(oldBody, fix, EXAM_PREFIXES)
    expect(merged).toContain('T: 36.5℃')
    expect(merged).toContain('切诊·舌象：舌淡红，苔薄白')
    expect(merged).toContain('切诊·脉象：脉弦细')
    expect(merged).toContain('望诊：[未填写，需补充]') // 没提到的子行原样保留
  })

  it('子行 + 自由文本混合写入：各归各位', () => {
    const fix = '一般情况可。\n望诊：神清，面色略红'
    const merged = mergeCompoundSectionBody(oldBody, fix, EXAM_PREFIXES)
    expect(merged).toContain('一般情况可。')
    expect(merged).toContain('望诊：神清，面色略红')
    expect(merged).toContain('切诊·舌象：舌淡红，苔薄白')
  })

  it('英文冒号子行也能命中前缀（归一化）', () => {
    const merged = mergeCompoundSectionBody(oldBody, '望诊: 神清气爽', EXAM_PREFIXES)
    expect(merged).toContain('望诊: 神清气爽')
    // 不应同时残留旧望诊行
    expect(merged.match(/望诊/g)!.length).toBe(1)
  })

  it('旧段缺某子行、新文本提供 → 追加到段尾不丢失', () => {
    const bodyNoTongue = '望诊：神清'
    const merged = mergeCompoundSectionBody(bodyNoTongue, '切诊·舌象：舌红苔黄', EXAM_PREFIXES)
    expect(merged).toContain('望诊：神清')
    expect(merged).toContain('切诊·舌象：舌红苔黄')
  })
})

describe('mergeCompoundSectionBody — 诊断段合并行拆分', () => {
  it('"中医诊断：X；西医诊断：Y" 合并行按分号拆开各自替换', () => {
    const oldBody = '中医诊断：[未填写，需补充]\n西医诊断：[未填写，需补充]'
    const merged = mergeCompoundSectionBody(
      oldBody,
      '中医诊断：眩晕病（风痰上扰证）；西医诊断：高血压病（待排）',
      DIAG_PREFIXES
    )
    expect(merged).toContain('中医诊断：眩晕病（风痰上扰证）')
    expect(merged).toContain('西医诊断：高血压病（待排）')
    expect(merged).not.toContain('[未填写，需补充]')
  })

  it('只给西医诊断时，已填的中医诊断保留', () => {
    const oldBody = '中医诊断：眩晕病\n西医诊断：[未填写，需补充]'
    const merged = mergeCompoundSectionBody(oldBody, '西医诊断：原发性高血压', DIAG_PREFIXES)
    expect(merged).toContain('中医诊断：眩晕病')
    expect(merged).toContain('西医诊断：原发性高血压')
  })
})

describe('writeSectionToRecord — 复合段集成（P0 回归用例）', () => {
  const record = [
    '【主诉】',
    '反复头晕3天，伴恶心',
    '',
    '【体格检查】',
    '[未填写，需补充]',
    '望诊：[未填写，需补充]',
    '闻诊：[未填写，需补充]',
    '切诊·舌象：舌淡红，苔薄白',
    '切诊·脉象：脉弦细',
    '其余阳性体征：[未填写，需补充]',
    '',
    '【辅助检查】',
    '[未填写，需补充]',
  ].join('\n')

  it('体格检查 章节级补全不再冲掉医生手填的舌象/脉象', () => {
    const next = writeSectionToRecord(
      record,
      '体格检查',
      'T: 36.5℃，P: 72次/分。神志清，心肺腹查体未见明显异常。'
    )
    expect(next).toContain('切诊·舌象：舌淡红，苔薄白')
    expect(next).toContain('切诊·脉象：脉弦细')
    expect(next).toContain('【辅助检查】') // 后续章节完好
  })

  it('清空复合段（回滚路径）也保留受保护子行', () => {
    const next = writeSectionToRecord(record, '体格检查', '')
    expect(next).toContain('切诊·舌象：舌淡红，苔薄白')
    expect(next).toContain('切诊·脉象：脉弦细')
  })

  it('非复合段维持原有整段替换行为', () => {
    const next = writeSectionToRecord(record, 'auxiliary_exam', '血常规未见异常')
    expect(next).toContain('【辅助检查】\n血常规未见异常')
  })
})

describe('writeSectionToRecord — 2026-06-11 映射修复回归', () => {
  const outpatientRecord = [
    '【主诉】',
    '咳嗽2天',
    '',
    '【治疗意见及措施】',
    '治则治法：[未填写，需补充]',
    '处理意见：[未填写，需补充]',
    '复诊建议：3天后复诊',
    '注意事项：[未填写，需补充]',
  ].join('\n')

  it('治疗意见及措施 父段写入落到真实章节且保留医生已填子行（原映射指向不存在的【处理意见】）', () => {
    const next = writeSectionToRecord(
      outpatientRecord,
      '治疗意见及措施',
      '治则治法：疏风散寒；处理意见：口服中药'
    )
    expect(next).toContain('治则治法：疏风散寒')
    expect(next).toContain('处理意见：口服中药')
    expect(next).toContain('复诊建议：3天后复诊') // 医生已填，保留
  })

  it('英文键 treatment_plan 走行级写入【治疗意见及措施】子行', () => {
    const next = writeSectionToRecord(outpatientRecord, 'treatment_plan', '口服抗生素')
    expect(next).toContain('处理意见：口服抗生素')
  })

  it('行级章节缺失时回退章节级：日常病程记录的独立【注意事项】能写入', () => {
    const courseRecord = '【患者病情记录】\n病情平稳\n\n【注意事项】\n[未填写，需补充]'
    const next = writeSectionToRecord(courseRecord, '注意事项', '低盐饮食，监测血压')
    expect(next).toContain('【注意事项】\n低盐饮食，监测血压')
  })
})
