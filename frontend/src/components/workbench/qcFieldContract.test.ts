/**
 * QC 字段 L2 前后端契约测试
 *
 * 2026-06-11 自 qcFieldMaps.test.ts（787 行超标）按被测模块拆分而来，测试内容零改动。
 * 本 describe 横跨 qcFieldConstants（FIELD_TO_LINE_PREFIX / FIELD_TO_SECTION）、
 * qcFieldMeta（NON_WRITABLE_FIELDS / NON_WRITABLE_HINTS）、
 * recordSectionWriter（writeSectionToRecord）三个模块，且共享同一份
 * BACKEND_WRITABLE_FIELDS 列表，因此单独成文件不再按模块拆开。
 *
 * 与"生产者侧"契约（backend/app/services/qc_engine/_writable_fields.py）成对，
 * 改后端 WRITABLE_FIELDS 时必须同步改这里。
 */
import { describe, expect, test } from 'vitest'
import {
  FIELD_TO_LINE_PREFIX,
  FIELD_TO_SECTION,
  NON_WRITABLE_FIELDS,
  NON_WRITABLE_HINTS,
  writeSectionToRecord,
} from './qcFieldMaps'

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
  const BACKEND_NON_WRITABLE_FIELDS = ['__patient_basic_info__', '__visit_time__']

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
