/**
 * inquiryUtils.test.ts
 * 覆盖体征文本合并的三种核心场景：空值/首行非体征/首行已是体征
 */
import { describe, it, expect } from 'vitest'
import { mergeVitalText } from './inquiryUtils'

describe('mergeVitalText', () => {
  it('原文为空时直接返回新体征文本', () => {
    expect(mergeVitalText('', 'T:36.5  P:80')).toBe('T:36.5  P:80')
  })

  it('首行不是体征行时前插，保留原有内容', () => {
    const current = '患者神志清\n查体配合'
    const result = mergeVitalText(current, 'T:36.5  P:80')
    expect(result.startsWith('T:36.5  P:80\n')).toBe(true)
    expect(result).toContain('患者神志清')
  })

  it('首行已是体征行时按 key 合并，同 key 替换，新 key 追加', () => {
    const current = 'T:36.5  P:80\n查体配合'
    const result = mergeVitalText(current, 'P:90  BP:120/80')
    const firstLine = result.split('\n')[0]
    // P 被替换
    expect(firstLine).toContain('P:90')
    expect(firstLine).not.toContain('P:80')
    // 原有 T 保留
    expect(firstLine).toContain('T:36.5')
    // 新 BP 追加
    expect(firstLine).toContain('BP:120/80')
    // 第二行原内容保留
    expect(result).toContain('查体配合')
  })
})
