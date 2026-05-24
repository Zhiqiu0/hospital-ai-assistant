/**
 * qcFieldMaps 契约测试（Audit Round 4 增加）
 *
 * 这是"消费者侧"契约测试 —— 假设 LLM 按 OUTPATIENT_GENERATE_PROMPT /
 * ADMISSION_NOTE_PROMPT 的格式输出病历，验证 writeSectionToRecord 在所有
 * 字段写入路径下都能正确定位。
 *
 * 与"生产者侧"契约（backend/tests/test_prompt_contract.py）成对：
 *   - 后端测试：保证 prompt 字符串里包含本测试假设的章节标题/子行前缀
 *   - 本测试：保证给定符合契约的样本病历，前端写入逻辑符合预期
 *
 * 关键防回归点：
 *   1. 中医四诊（望/闻/舌/脉）写入【体格检查】子行，不另起独立章节
 *   2. 专项评估 7 项写入【专项评估】子行，不互相覆盖
 *   3. 重复写入同一字段不产生重复章节
 *   4. 取消写入回滚到 "[未填写，需补充]"，保留行结构
 */
import { describe, expect, test } from 'vitest'
import {
  FIELD_TO_LINE_PREFIX,
  FIELD_TO_SECTION,
  NON_WRITABLE_FIELDS,
  NON_WRITABLE_HINTS,
  restoreFieldState,
  snapshotFieldState,
  writeSectionToRecord,
} from './qcFieldMaps'

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

/** 住院入院记录样本（专项评估 7 项作为子行） */
const SAMPLE_ADMISSION_RECORD = `【主诉】
胸痛 2 小时

【现病史】
患者 2 小时前突发胸痛...

【专项评估】
· 当前用药：[未填写，需补充]
· 疼痛评估（NRS评分）：[未填写，需补充]
· 康复需求：[未填写，需补充]
· 心理状态：[未填写，需补充]
· 营养风险：[未填写，需补充]
· VTE风险：[未填写，需补充]
· 宗教信仰/饮食禁忌：[未填写，需补充]

【体格检查】
T:36.5℃ P:78次/分

【入院诊断】
急性心肌梗死`

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

// ─── 中医四诊：4 字段 × 3 场景 = 12 用例 ────────────────────────────────

describe('writeSectionToRecord — 中医四诊（在【体格检查】子行）', () => {
  const fourDiagnoses: Array<{ field: string; cnAlias: string; prefix: string; sample: string }> = [
    {
      field: 'tcm_inspection',
      cnAlias: '望诊',
      prefix: '望诊：',
      sample: '神清，面色红润',
    },
    {
      field: 'tcm_auscultation',
      cnAlias: '闻诊',
      prefix: '闻诊：',
      sample: '语声清晰，无异常气味',
    },
    { field: 'tongue_coating', cnAlias: '舌象', prefix: '切诊·舌象：', sample: '舌淡红，苔薄白' },
    {
      field: 'pulse_condition',
      cnAlias: '脉象',
      prefix: '切诊·脉象：',
      sample: '脉象平和，节律规整',
    },
  ]

  for (const { field, cnAlias, prefix, sample } of fourDiagnoses) {
    test(`${field}：写入【体格检查】子行，不另起独立章节`, () => {
      const result = writeSectionToRecord(SAMPLE_OUTPATIENT_RECORD, field, sample)
      // 不应该出现独立章节
      expect(countSection(result, '【望诊】')).toBe(0)
      expect(countSection(result, '【闻诊】')).toBe(0)
      expect(countSection(result, '【舌象】')).toBe(0)
      expect(countSection(result, '【脉象】')).toBe(0)
      // 应该写到子行
      expect(result).toContain(prefix + sample)
      // 【体格检查】仍然只有一个
      expect(countSection(result, '【体格检查】')).toBe(1)
    })

    test(`${field}：中文别名 "${cnAlias}" 行为一致`, () => {
      const result = writeSectionToRecord(SAMPLE_OUTPATIENT_RECORD, cnAlias, sample)
      expect(result).toContain(prefix + sample)
      expect(countSection(result, '【体格检查】')).toBe(1)
    })

    test(`${field}：重复写入不产生重复章节`, () => {
      let result = writeSectionToRecord(SAMPLE_OUTPATIENT_RECORD, field, sample)
      result = writeSectionToRecord(result, field, sample + '（修正）')
      expect(result).toContain(prefix + sample + '（修正）')
      expect(countSection(result, '【体格检查】')).toBe(1)
    })

    test(`${field}：取消写入（fixText 为空）行回滚到 [未填写，需补充]`, () => {
      const written = writeSectionToRecord(SAMPLE_OUTPATIENT_RECORD, field, sample)
      const reverted = writeSectionToRecord(written, field, '')
      expect(reverted).toContain(prefix + '[未填写，需补充]')
      expect(reverted).not.toContain(prefix + sample)
    })
  }
})

// ─── 住院专项评估：7 字段 × 3 场景 = 21 用例 ────────────────────────────

describe('writeSectionToRecord — 住院专项评估（【专项评估】子行）', () => {
  const assessments: Array<{ field: string; cnAlias: string; prefix: string; sample: string }> = [
    { field: 'pain_assessment', cnAlias: '疼痛评估', prefix: '· 疼痛评估', sample: '：3分' },
    { field: 'vte_risk', cnAlias: 'VTE风险评估', prefix: '· VTE风险', sample: '：低危' },
    {
      field: 'nutrition_assessment',
      cnAlias: '营养评估',
      prefix: '· 营养风险',
      sample: '：无明显风险',
    },
    { field: 'psychology_assessment', cnAlias: '心理评估', prefix: '· 心理状态', sample: '：稳定' },
    {
      field: 'rehabilitation_assessment',
      cnAlias: '康复评估',
      prefix: '· 康复需求',
      sample: '：暂无',
    },
    { field: 'current_medications', cnAlias: '当前用药', prefix: '· 当前用药', sample: '：无' },
    {
      field: 'religion_belief',
      cnAlias: '宗教信仰',
      prefix: '· 宗教信仰',
      sample: '/饮食禁忌：无',
    },
  ]

  for (const { field, cnAlias, prefix, sample } of assessments) {
    test(`${field}：写入【专项评估】子行，不另起独立章节`, () => {
      const result = writeSectionToRecord(SAMPLE_ADMISSION_RECORD, field, sample)
      // 不应有独立的【疼痛评估】等章节
      expect(countSection(result, `【${cnAlias}】`)).toBe(0)
      // 子行应被替换（子行原本"· 疼痛评估（NRS评分）：[未填写]"，sample 一般是 "：3分"）
      // 用前缀 + sample 拼出来的子串应该出现一次
      expect(result).toContain(prefix)
      expect(result).toContain(sample.replace(/^：/, '：').replace(/^\//, '/'))
      expect(countSection(result, '【专项评估】')).toBe(1)
    })

    test(`${field}：中文别名 "${cnAlias}" 行为一致`, () => {
      const result = writeSectionToRecord(SAMPLE_ADMISSION_RECORD, cnAlias, sample)
      expect(countSection(result, '【专项评估】')).toBe(1)
      expect(countSection(result, `【${cnAlias}】`)).toBe(0)
    })

    test(`${field}：重复写入不产生重复章节`, () => {
      let result = writeSectionToRecord(SAMPLE_ADMISSION_RECORD, field, sample)
      result = writeSectionToRecord(result, field, sample + '（修正）')
      expect(countSection(result, '【专项评估】')).toBe(1)
      expect(countSection(result, `【${cnAlias}】`)).toBe(0)
    })
  }

  test('写入多个评估字段不互相覆盖', () => {
    let result = SAMPLE_ADMISSION_RECORD
    result = writeSectionToRecord(result, 'pain_assessment', '：3分')
    result = writeSectionToRecord(result, 'vte_risk', '：低危')
    result = writeSectionToRecord(result, 'nutrition_assessment', '：无')
    expect(result).toContain('· 疼痛评估：3分')
    expect(result).toContain('· VTE风险：低危')
    expect(result).toContain('· 营养风险：无')
    expect(countSection(result, '【专项评估】')).toBe(1)
  })
})

// ─── 生命体征（行级 / whole_line 模式）─────────────────────────────────

describe('writeSectionToRecord — 生命体征（physical_exam_vitals 行级整行替换）', () => {
  const VITALS_TEXT = 'T: 36.5°C P: 78次/分 R: 18次/分 BP: 120/80mmHg'

  test('physical_exam_vitals 整行替换原 T: 起头的行，不另起独立章节', () => {
    const result = writeSectionToRecord(
      SAMPLE_OUTPATIENT_RECORD,
      'physical_exam_vitals',
      VITALS_TEXT
    )
    expect(result).toContain(VITALS_TEXT)
    // 旧的"T: 37°C"行应被替换掉
    expect(result).not.toContain('T: 37°C')
    // 不应另起【体格检查】章节
    expect(countSection(result, '【体格检查】')).toBe(1)
    // 不应另起【生命体征】章节
    expect(countSection(result, '【生命体征】')).toBe(0)
  })

  test('中文别名"生命体征"行为一致', () => {
    const result = writeSectionToRecord(SAMPLE_OUTPATIENT_RECORD, '生命体征', VITALS_TEXT)
    expect(result).toContain(VITALS_TEXT)
    expect(countSection(result, '【体格检查】')).toBe(1)
  })

  test('中文冒号"T："行也能被命中', () => {
    // 模拟 LLM 输出中文冒号
    const recordWithChineseColon = SAMPLE_OUTPATIENT_RECORD.replace('T: 37°C', 'T： 37°C')
    const result = writeSectionToRecord(recordWithChineseColon, 'physical_exam_vitals', VITALS_TEXT)
    expect(result).toContain(VITALS_TEXT)
    expect(result).not.toContain('T： 37°C')
  })

  test('重复写入不产生重复章节也不重复行', () => {
    let result = writeSectionToRecord(SAMPLE_OUTPATIENT_RECORD, 'physical_exam_vitals', VITALS_TEXT)
    result = writeSectionToRecord(result, 'physical_exam_vitals', VITALS_TEXT + ' 修正')
    expect(result).toContain(VITALS_TEXT + ' 修正')
    expect(countSection(result, '【体格检查】')).toBe(1)
    // 旧值不残留
    expect((result.match(/T: 36\.5°C/g) || []).length).toBe(1)
  })
})

// ─── 顺序敏感性回归（用户报告的 bug：先后顺序不应影响结果）─────────────

describe('writeSectionToRecord — 同段多字段顺序无关性（治本回归测试）', () => {
  const VITALS = 'T: 36.5°C P: 78次/分 R: 18次/分 BP: 120/80mmHg'
  const TONGUE = '舌淡红，苔薄白'

  test('先生命体征后舌象：两者都在', () => {
    let r = SAMPLE_OUTPATIENT_RECORD
    r = writeSectionToRecord(r, 'physical_exam_vitals', VITALS)
    r = writeSectionToRecord(r, 'tongue_coating', TONGUE)
    expect(r).toContain(VITALS)
    expect(r).toContain('切诊·舌象：' + TONGUE)
    expect(countSection(r, '【体格检查】')).toBe(1)
  })

  test('先舌象后生命体征：两者都在（用户报告 bug 的反例）', () => {
    let r = SAMPLE_OUTPATIENT_RECORD
    r = writeSectionToRecord(r, 'tongue_coating', TONGUE)
    r = writeSectionToRecord(r, 'physical_exam_vitals', VITALS)
    expect(r).toContain(VITALS)
    expect(r).toContain('切诊·舌象：' + TONGUE)
    expect(countSection(r, '【体格检查】')).toBe(1)
  })

  test('per-field 三态撤销：原本不存在的行 → 写入 → 取消应删除该行（不留占位符）', () => {
    // 模拟 LLM 生成精简版（不含切诊·舌象 / 切诊·脉象 行）
    const sample = `【主诉】
头痛

【体格检查】
T:36.5℃ P:78次/分
望诊：神清

【辅助检查】
暂无`
    // 写入前快照：'absent'（行不存在）
    const snap = snapshotFieldState(sample, 'tongue_coating')
    expect(snap.state).toBe('absent')

    // 写入舌象
    const written = writeSectionToRecord(sample, 'tongue_coating', '舌淡红苔薄白')
    expect(written).toContain('切诊·舌象：舌淡红苔薄白')

    // 撤销：按快照还原 → 应删除整行，不留占位符
    const restored = restoreFieldState(written, 'tongue_coating', snap)
    expect(restored).not.toContain('切诊·舌象：') // 行整个消失
    expect(restored).not.toContain('[未填写，需补充]') // 不会留占位符
    // 其他内容保持原样
    expect(restored).toContain('望诊：神清')
    expect(restored).toContain('T:36.5℃ P:78次/分')
  })

  test('per-field 三态撤销：原本是占位符 → 写入 → 取消应回到占位符', () => {
    const sample = `【主诉】
头痛

【体格检查】
T:36.5℃
望诊：[未填写，需补充]
切诊·舌象：[未填写，需补充]`
    const snap = snapshotFieldState(sample, 'tongue_coating')
    expect(snap.state).toBe('placeholder')

    const written = writeSectionToRecord(sample, 'tongue_coating', '舌淡红')
    const restored = restoreFieldState(written, 'tongue_coating', snap)
    expect(restored).toContain('切诊·舌象：[未填写，需补充]')
  })

  test('per-field 三态撤销：原本是医生手填值 → 写入 → 取消应还原原值', () => {
    const sample = `【主诉】
头痛

【体格检查】
T:36.5℃
切诊·舌象：医生手填的内容`
    const snap = snapshotFieldState(sample, 'tongue_coating')
    expect(snap.state).toBe('value')
    expect(snap.value).toContain('医生手填的内容')

    const written = writeSectionToRecord(sample, 'tongue_coating', 'AI 覆盖的内容')
    expect(written).toContain('AI 覆盖的内容')

    const restored = restoreFieldState(written, 'tongue_coating', snap)
    expect(restored).toContain('医生手填的内容')
    expect(restored).not.toContain('AI 覆盖的内容')
  })

  test('交错写入再取消其中一项：被取消的字段回滚，其他字段保留（用户报告 bug）', () => {
    // 复现用户报告的场景：先写望诊→再写闻诊→取消望诊
    // 期望：望诊回到 [未填写]，闻诊保留
    let r = SAMPLE_OUTPATIENT_RECORD
    r = writeSectionToRecord(r, 'tcm_inspection', '神清面红')
    r = writeSectionToRecord(r, 'tcm_auscultation', '语声清晰')
    expect(r).toContain('望诊：神清面红')
    expect(r).toContain('闻诊：语声清晰')

    // 取消望诊（fixText=''）
    r = writeSectionToRecord(r, 'tcm_inspection', '')
    expect(r).toContain('望诊：[未填写，需补充]') // 望诊已回滚
    expect(r).toContain('闻诊：语声清晰') // 闻诊保留 ←★
  })

  test('生命体征 + 中医四诊全部子项混合写入，互不冲突', () => {
    let r = SAMPLE_OUTPATIENT_RECORD
    r = writeSectionToRecord(r, 'tongue_coating', TONGUE)
    r = writeSectionToRecord(r, 'physical_exam_vitals', VITALS)
    r = writeSectionToRecord(r, 'pulse_condition', '脉象平和')
    r = writeSectionToRecord(r, 'tcm_inspection', '神清面色红润')
    r = writeSectionToRecord(r, 'tcm_auscultation', '语声清晰')
    expect(r).toContain(VITALS)
    expect(r).toContain('切诊·舌象：' + TONGUE)
    expect(r).toContain('切诊·脉象：脉象平和')
    expect(r).toContain('望诊：神清面色红润')
    expect(r).toContain('闻诊：语声清晰')
    expect(countSection(r, '【体格检查】')).toBe(1)
  })
})

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
    const result = writeSectionToRecord(
      SAMPLE_WITH_TREATMENT,
      '处理意见',
      '蓝芩口服液 10ml tid'
    )
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
    const result = writeSectionToRecord(SAMPLE_OUTPATIENT_RECORD, '__visit_time__', '2026-05-19 08:00')
    expect(result).toBe(SAMPLE_OUTPATIENT_RECORD)
  })

  test('__tcm_four_diagnoses__ 不写入正文', () => {
    const result = writeSectionToRecord(SAMPLE_OUTPATIENT_RECORD, '__tcm_four_diagnoses__', '舌淡红')
    expect(result).toBe(SAMPLE_OUTPATIENT_RECORD)
  })
})

// ─── 治本（2026-05-19）：L2 前后端契约 ─────────────────────────────────

describe('L2 契约：与后端 _writable_fields.py 同步', () => {
  // ⚠️ 这份列表必须跟 backend/app/services/qc_engine/_writable_fields.py 同步！
  // 改后端 WRITABLE_FIELDS 时记得改这里，否则该测试会挂。
  const BACKEND_WRITABLE_FIELDS = [
    // 门急诊 + 住院共用（章节级）
    '主诉',
    '现病史',
    '既往史',
    '过敏史',
    '个人史',
    '辅助检查',
    '月经史',
    '患者去向',
    '体格检查',
    // 门急诊（行级 / 合并章节子行）
    '治则治法',
    '处理意见',
    '复诊建议',
    '注意事项',
    '中医诊断',
    '西医诊断',
    '生命体征',
    // 中医四诊（2026-05-24 拆出单字段；旧设计错标 NON_WRITABLE）
    '望诊',
    '闻诊',
    '舌象',
    '脉象',
    // 住院·入院记录新增（章节级）
    '婚育史',
    '家族史',
    '入院诊断',
    // 住院·专项评估 7 项（2026-05-24 拆出单字段；旧设计错标 NON_WRITABLE）
    '当前用药',
    '疼痛评估',
    '康复评估',
    '心理评估',
    '营养评估',
    'VTE风险评估',
    '宗教信仰',
    // 住院·首次病程记录
    '病例特点',
    '拟诊讨论',
    '诊疗计划',
    // 住院·出院记录
    '入院情况',
    '诊疗经过',
    '出院情况',
    '出院诊断',
    '出院医嘱',
    // 住院·围手术期
    '手术指征',
    '拟施手术名称及方式',
    '病情分析及术后恢复情况评估',
    '手术经过',
  ]

  // 2026-05-24 治本：__tcm_four_diagnoses__ / __special_assessment__ 已从 NON_WRITABLE
  // 移到 WRITABLE 拆字段（详见上方 BACKEND_WRITABLE_FIELDS）。
  const BACKEND_NON_WRITABLE_FIELDS = [
    '__patient_basic_info__',
    '__visit_time__',
  ]

  test('每个后端 WRITABLE_FIELDS 都能在前端 FIELD_TO_LINE_PREFIX 或 FIELD_TO_SECTION 找到', () => {
    const missing: string[] = []
    for (const field of BACKEND_WRITABLE_FIELDS) {
      const hasLine = field in FIELD_TO_LINE_PREFIX
      const hasSection = field in FIELD_TO_SECTION
      if (!hasLine && !hasSection) missing.push(field)
    }
    expect(missing, `以下字段未在前端注册：${missing.join(', ')}`).toEqual([])
  })

  test('每个后端 NON_WRITABLE_FIELDS 都在前端 NON_WRITABLE_FIELDS 集合', () => {
    const missing: string[] = []
    for (const field of BACKEND_NON_WRITABLE_FIELDS) {
      if (!NON_WRITABLE_FIELDS.has(field)) missing.push(field)
    }
    expect(missing, `以下不可写字段未在前端注册：${missing.join(', ')}`).toEqual([])
  })

  test('每个 NON_WRITABLE 字段都有 UI 引导文案', () => {
    for (const field of NON_WRITABLE_FIELDS) {
      expect(NON_WRITABLE_HINTS[field], `${field} 缺 UI 文案`).toBeTruthy()
    }
  })

  test('WRITABLE 实际可写：调用 writeSectionToRecord 必须改变 content（除非已被占位符匹配上）', () => {
    // 完整渲染样本：包含所有可写字段在病历里（门急诊 + 住院全字段）
    const fullSample = `就诊时间：2026-05-19 10:00

【主诉】
[未填写，需补充]

【现病史】
[未填写，需补充]

【既往史】
[未填写，需补充]

【过敏史】
[未填写，需补充]

【个人史】
[未填写，需补充]

【月经史】
[未填写，需补充]

【婚育史】
[未填写，需补充]

【家族史】
[未填写，需补充]

【体格检查】
T:36.5℃ P:78次/分
望诊：[未填写，需补充]
闻诊：[未填写，需补充]
切诊·舌象：[未填写，需补充]
切诊·脉象：[未填写，需补充]

【专项评估】
· 当前用药：[未填写，需补充]
· 疼痛评估：[未填写，需补充]
· 康复需求：[未填写，需补充]
· 心理状态：[未填写，需补充]
· 营养风险：[未填写，需补充]
· VTE风险：[未填写，需补充]
· 宗教信仰：[未填写，需补充]

【辅助检查】
[未填写，需补充]

【诊断】
中医诊断：[未填写，需补充]
西医诊断：[未填写，需补充]

【入院诊断】
[未填写，需补充]

【治疗意见及措施】
治则治法：[未填写，需补充]
处理意见：[未填写，需补充]
复诊建议：[未填写，需补充]
注意事项：[未填写，需补充]

【患者去向】
[未填写，需补充]

【病例特点】
[未填写，需补充]

【拟诊讨论】
[未填写，需补充]

【诊疗计划】
[未填写，需补充]

【入院情况】
[未填写，需补充]

【诊疗经过】
[未填写，需补充]

【出院情况】
[未填写，需补充]

【出院诊断】
[未填写，需补充]

【出院医嘱】
[未填写，需补充]

【手术指征】
[未填写，需补充]

【拟施手术名称及方式】
[未填写，需补充]

【手术经过】
[未填写，需补充]

【病情分析及术后恢复情况评估】
[未填写，需补充]`

    const cannotWrite: string[] = []
    for (const field of BACKEND_WRITABLE_FIELDS) {
      // 生命体征是 whole_line 模式，fix_text 要自带 T:/P: 前缀
      const fixText = field === '生命体征' ? 'T:37.0℃ P:80次/分' : '测试内容'
      const result = writeSectionToRecord(fullSample, field, fixText)
      if (result === fullSample) cannotWrite.push(field)
    }
    expect(
      cannotWrite,
      `以下字段在完整样本里也写不进去（说明前端映射有问题）：${cannotWrite.join(', ')}`
    ).toEqual([])
  })
})

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
