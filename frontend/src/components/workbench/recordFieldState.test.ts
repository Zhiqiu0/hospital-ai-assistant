/**
 * recordFieldState 写入前快照 / 撤销还原契约测试
 *
 * 2026-06-11 自 qcFieldMaps.test.ts（787 行超标）按被测模块拆分而来，测试内容零改动。
 * 本文件覆盖 snapshotFieldState / restoreFieldState 的 per-field 三态撤销：
 *   - absent      行原本不存在 → 撤销应删除整行（不留占位符）
 *   - placeholder 行原本是占位符 → 撤销应回到占位符
 *   - value       行原本是医生手填值 → 撤销应还原原值
 */
import { describe, expect, test } from 'vitest'
import {
  extractFieldPreview,
  restoreFieldState,
  snapshotFieldState,
  writeSectionToRecord,
} from './qcFieldMaps'

describe('snapshotFieldState / restoreFieldState — per-field 三态撤销', () => {
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
})

describe('extractFieldPreview — 签发确认弹窗内容摘要', () => {
  const sample = `【主诉】
反复头痛3天，加重1天

【体格检查】
T:36.5℃ P:78次/分
望诊：神清，面色红润
切诊·舌象：舌淡红苔薄白

【辅助检查】
暂无`

  test('行级字段：取该行值并去掉前缀', () => {
    expect(extractFieldPreview(sample, 'tongue_coating')).toBe('舌淡红苔薄白')
  })

  test('章节级字段：取标题后首个非空行', () => {
    expect(extractFieldPreview(sample, 'chief_complaint')).toBe('反复头痛3天，加重1天')
  })

  test('超长内容截断加省略号', () => {
    const long = `【主诉】\n${'很长的主诉内容'.repeat(20)}`
    const preview = extractFieldPreview(long, 'chief_complaint')
    expect(preview).toHaveLength(61) // 60 字 + 省略号
    expect(preview!.endsWith('…')).toBe(true)
  })

  test('定位失败返回 null（弹窗退回只显字段名）', () => {
    expect(extractFieldPreview('【别的章节】\n内容', 'tongue_coating')).toBeNull()
    expect(extractFieldPreview(sample, '完全未映射的字段')).toBeNull()
  })
})
