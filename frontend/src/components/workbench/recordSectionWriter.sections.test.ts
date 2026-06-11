/**
 * recordSectionWriter 章节级与合并段子行写入契约测试
 *
 * 2026-06-11 自 qcFieldMaps.test.ts（787 行超标）按被测模块拆分而来，测试内容零改动。
 * 本文件覆盖 writeSectionToRecord 的章节级写入路径：
 *   - 章节级字段整段替换（主诉等）+ 未映射字段/缺失章节不兜底追加（治本回归）
 *   - 治疗意见及措施 4 子行 / 诊断 2 子行（合并章节下行级写入）
 *   - NON_WRITABLE 字段短路（必须返回原内容）
 */
import { describe, expect, test } from 'vitest'
import { writeSectionToRecord } from './qcFieldMaps'

// ─── 样本病历 fixtures（基于 LLM 实际输出格式，与 prompt 契约一致）──────────

/** 门诊病历样本（生命体征 + 中医四诊都在【体格检查】下作为子行） */
const SAMPLE_OUTPATIENT_RECORD = `就诊时间：2026-04-29 03:16  病发时间：2026-04-29 00:00

【主诉】
头痛3天

【现病史】
患者于3天前出现头痛，为搏动性，部位位于前额部及后枕部，伴恶心呕吐。

【既往史】
糖尿病病史。

【过敏史】
否认药物及食物过敏史。

【个人史】
[未填写，需补充]

【体格检查】
T: 37°C
望诊：[未填写，需补充]
闻诊：[未填写，需补充]
切诊·舌象：[未填写，需补充]
切诊·脉象：[未填写，需补充]

【辅助检查】
暂无

【诊断】
感冒相关性头痛

【治疗意见及措施】
治则治法：[未填写，需补充]
处理意见：[未填写，需补充]
复诊建议：[未填写，需补充]`

// ─── 通用断言工具 ────────────────────────────────────────────────────────

/** 计算 record 里出现指定章节标题的次数 */
function countSection(record: string, header: string): number {
  return (
    record.match(
      new RegExp(
        header.replace(/[【】]/g, m => '\\' + m),
        'g'
      )
    ) || []
  ).length
}

// ─── 章节级写入仍然正常（回归测试）────────────────────────────────────

describe('writeSectionToRecord — 章节级字段（不受改动影响）', () => {
  test('chief_complaint 替换【主诉】章节内容', () => {
    const result = writeSectionToRecord(SAMPLE_OUTPATIENT_RECORD, 'chief_complaint', '头晕 1 周')
    expect(result).toContain('【主诉】\n头晕 1 周')
    expect(countSection(result, '【主诉】')).toBe(1)
    // 旧内容被替换
    expect(result).not.toContain('头痛3天')
  })

  test('content 字段（全文类规则）静默跳过', () => {
    const result = writeSectionToRecord(SAMPLE_OUTPATIENT_RECORD, 'content', '任何内容')
    expect(result).toBe(SAMPLE_OUTPATIENT_RECORD)
  })

  test('治本：未映射字段不再兜底追加，返回原内容', () => {
    // 2026-05-19 治本：旧实现"未映射字段 fallback 追加新章节"是反复 bug 的根因
    // （治疗意见、中医诊断合并行映射不对时悄悄追加错误章节）。
    // 新行为：返回原 content，调用方通过"内容没变"检测来提示用户。
    const result = writeSectionToRecord(SAMPLE_OUTPATIENT_RECORD, 'unknown_field', '某段内容')
    expect(result).toBe(SAMPLE_OUTPATIENT_RECORD)
  })

  test('治本：映射到不存在的章节也不兜底追加', () => {
    // 模拟门诊渲染器没有【月经史】章节，但规则 target_field=既往史 走章节级
    // 如果章节不在病历里（例如医生删了），不应该兜底追加，应该返回原内容
    const sampleNoSection = `【主诉】
头痛`
    const result = writeSectionToRecord(sampleNoSection, 'past_history', '高血压')
    // 【既往史】在 sampleNoSection 里不存在 → 不应兜底追加
    expect(result).toBe(sampleNoSection)
  })
})

// ─── 治本（2026-05-19）：治疗意见 4 子行 + 诊断 2 子行 ─────────────────

describe('writeSectionToRecord — 治疗意见及措施子行（合并章节下行级写入）', () => {
  const SAMPLE_WITH_TREATMENT = `【主诉】
头痛

【诊断】
中医诊断：[未填写，需补充]
西医诊断：[未填写，需补充]

【治疗意见及措施】
治则治法：[未填写，需补充]
处理意见：[未填写，需补充]
复诊建议：[未填写，需补充]`

  test('治则治法：写入【治疗意见及措施】子行，不另起独立章节', () => {
    const result = writeSectionToRecord(SAMPLE_WITH_TREATMENT, '治则治法', '疏风清热，利咽止咳')
    expect(result).toContain('治则治法：疏风清热，利咽止咳')
    // 不应另起独立的【治则治法】章节
    expect(countSection(result, '【治则治法】')).toBe(0)
    // 不应另起重复的【治疗意见及措施】章节（这是用户报的 bug）
    expect(countSection(result, '【治疗意见及措施】')).toBe(1)
    // 其他子行的占位符保留
    expect(result).toContain('处理意见：[未填写，需补充]')
    expect(result).toContain('复诊建议：[未填写，需补充]')
  })

  test('处理意见：写入子行不冲掉其他子行（用户报的核心 bug）', () => {
    const result = writeSectionToRecord(SAMPLE_WITH_TREATMENT, '处理意见', '蓝芩口服液 10ml tid')
    expect(result).toContain('处理意见：蓝芩口服液 10ml tid')
    expect(result).toContain('治则治法：[未填写，需补充]') // 不能冲掉
    expect(result).toContain('复诊建议：[未填写，需补充]') // 不能冲掉
    expect(countSection(result, '【治疗意见及措施】')).toBe(1)
  })

  test('复诊建议：同上', () => {
    const result = writeSectionToRecord(SAMPLE_WITH_TREATMENT, '复诊建议', '3 天后复诊')
    expect(result).toContain('复诊建议：3 天后复诊')
    expect(result).toContain('治则治法：[未填写，需补充]')
    expect(result).toContain('处理意见：[未填写，需补充]')
  })

  test('注意事项：子行不存在时插入新行（不创建新章节）', () => {
    // SAMPLE_WITH_TREATMENT 没有"注意事项："行；写入时应该在【治疗意见及措施】末尾插入
    const result = writeSectionToRecord(SAMPLE_WITH_TREATMENT, '注意事项', '清淡饮食')
    expect(result).toContain('注意事项：清淡饮食')
    // 还是只有 1 个【治疗意见及措施】章节
    expect(countSection(result, '【治疗意见及措施】')).toBe(1)
    // 不应另起【注意事项】独立章节
    expect(countSection(result, '【注意事项】')).toBe(0)
  })

  test('治疗意见 3 项交错写入互不冲突', () => {
    let r = SAMPLE_WITH_TREATMENT
    r = writeSectionToRecord(r, '治则治法', '疏风清热')
    r = writeSectionToRecord(r, '处理意见', '蓝芩口服液')
    r = writeSectionToRecord(r, '复诊建议', '3 天后复诊')
    expect(r).toContain('治则治法：疏风清热')
    expect(r).toContain('处理意见：蓝芩口服液')
    expect(r).toContain('复诊建议：3 天后复诊')
    expect(countSection(r, '【治疗意见及措施】')).toBe(1)
  })
})

describe('writeSectionToRecord — 诊断子行（【诊断】下中医/西医行）', () => {
  const SAMPLE_WITH_DIAGNOSIS = `【主诉】
头痛

【诊断】
中医诊断：[未填写，需补充]
西医诊断：[未填写，需补充]`

  test('西医诊断：写入【诊断】子行', () => {
    const result = writeSectionToRecord(SAMPLE_WITH_DIAGNOSIS, '西医诊断', '急性咽炎')
    expect(result).toContain('西医诊断：急性咽炎')
    expect(countSection(result, '【诊断】')).toBe(1)
    expect(countSection(result, '【西医诊断】')).toBe(0)
    expect(result).toContain('中医诊断：[未填写，需补充]') // 不能冲掉
  })

  test('中医诊断：合并行整体替换', () => {
    const result = writeSectionToRecord(SAMPLE_WITH_DIAGNOSIS, '中医诊断', '喉痹 — 风热犯肺证')
    expect(result).toContain('中医诊断：喉痹 — 风热犯肺证')
    expect(countSection(result, '【诊断】')).toBe(1)
    expect(result).toContain('西医诊断：[未填写，需补充]') // 不能冲掉
  })
})

// ─── 治本（2026-05-19）：NON_WRITABLE 短路 ────────────────────────────

describe('NON_WRITABLE_FIELDS 短路（不可写字段必须返回原内容）', () => {
  test('__patient_basic_info__ 不写入正文', () => {
    const result = writeSectionToRecord(SAMPLE_OUTPATIENT_RECORD, '__patient_basic_info__', '张三')
    expect(result).toBe(SAMPLE_OUTPATIENT_RECORD)
  })

  test('__visit_time__ 不写入正文', () => {
    const result = writeSectionToRecord(
      SAMPLE_OUTPATIENT_RECORD,
      '__visit_time__',
      '2026-05-19 08:00'
    )
    expect(result).toBe(SAMPLE_OUTPATIENT_RECORD)
  })

  test('__tcm_four_diagnoses__ 不写入正文', () => {
    const result = writeSectionToRecord(
      SAMPLE_OUTPATIENT_RECORD,
      '__tcm_four_diagnoses__',
      '舌淡红'
    )
    expect(result).toBe(SAMPLE_OUTPATIENT_RECORD)
  })
})
