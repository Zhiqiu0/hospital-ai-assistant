/**
 * recordSections.ts 反解逻辑测试。
 *
 * 重点锁定 2026-08-20 第三轮走查发现的 bug：
 * 【体格检查】段落首行是体征行（后端 normalize_vitals_line 保证以 "T:" 起头），
 * 反解写回 inquiry.physical_exam 时必须滤掉——体温/脉搏/血压属于独立体征字段，
 * 不滤会把整行数值串进体格检查文本造成重复（生产 PUT 请求体实锤）。
 */
import { describe, expect, it } from 'vitest'
import { parseGeneratedSectionsToInquiry } from './recordSections'

describe('parseGeneratedSectionsToInquiry', () => {
  it('体格检查反解：滤掉 T: 体征行与望闻切诊行，只保留普通体检文字', () => {
    const content = [
      '【主诉】',
      '头晕 3 天',
      '【体格检查】',
      'T:36.4℃ P:82次/分 R:18次/分 BP:158/96mmHg',
      '望诊：面色如常',
      '闻诊：语声清晰',
      '切诊·舌象：舌淡红，苔薄白',
      '切诊·脉象：脉弦',
      '其余阳性体征：血压偏高，双肺呼吸音清',
      '【诊断】',
      '眩晕病',
    ].join('\n')
    const result = parseGeneratedSectionsToInquiry(content)
    expect(result.chief_complaint).toBe('头晕 3 天')
    // 体征行、四诊行都不进 physical_exam，只留"其余阳性体征"的内容
    expect(result.physical_exam).toBe('血压偏高，双肺呼吸音清')
    expect(result.physical_exam).not.toContain('T:')
    expect(result.physical_exam).not.toContain('mmHg')
  })

  it('体格检查反解：急诊缺体温的归一行（T:[未测] 起头）同样被滤掉', () => {
    const content = [
      '【体格检查】',
      'T:[未测] P:92次/分 BP:128/78mmHg',
      '左手食指指腹裂伤约2cm，渗血',
    ].join('\n')
    const result = parseGeneratedSectionsToInquiry(content)
    expect(result.physical_exam).toBe('左手食指指腹裂伤约2cm，渗血')
  })
})
