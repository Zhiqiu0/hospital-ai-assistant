/**
 * HIS 自动填入字段收集工具（components/workbench/recordEditor/collectFillFields.ts）
 *
 * 2026-06-11 Round 5 拆分：从 RecordEditorToolbar.tsx 抽出（原文件 471 行超 300 行规范）。
 * 纯函数、无 React 依赖：AutoFillButton 点击时收集当前问诊 + 病历内容，
 * 打包成桌面 Agent /fill 入参。逻辑原样搬家，未做任何改动。
 *
 * 数据来源:
 *   - intake.* (生命体征/身高体重): 从 inquiryStore 取(医生原始填的数字)
 *   - record.*: 从 recordContent 正文按【XX】标题拆出各 section
 *     原因:AI 一键生成 / 补全后的病历内容只在 recordContent 里,inquiry
 *     store 不会同步,直接从 inquiry 取的话大部分 section 是空的。
 *
 * 注意:defaultInquiry 数值字段默认是 '' 空字符串,不是 null。
 */
import type { InquiryData } from '@/store/types'
import type { FillRequest } from '@/services/desktopAgent'

/** Agent /fill 的 fields 数组类型（与 desktopAgent 的 FillRequest 对齐） */
export type FillFields = FillRequest['fields']

/**
 * 收集可填入 HIS 的字段列表
 * @param inquiry 当前问诊数据（来自 inquiryStore）
 * @param recordContent 病历正文（来自编辑器）
 */
export function collectFillFields(inquiry: InquiryData, recordContent: string): FillFields {
  const fields: Array<{
    section: 'intake' | 'record' | 'diagnosis'
    field_key: string
    value: unknown
  }> = []
  const nonEmpty = (v: unknown): boolean => {
    if (v == null) return false
    return String(v).trim() !== ''
  }

  // ── intake: 从 inquiry store 取生命体征 / 体格检查关键字段 ─────────
  if (nonEmpty(inquiry.temperature))
    fields.push({ section: 'intake', field_key: 'temperature', value: inquiry.temperature })
  if (nonEmpty(inquiry.pulse))
    fields.push({ section: 'intake', field_key: 'heart_rate', value: inquiry.pulse })
  if (nonEmpty(inquiry.respiration))
    fields.push({ section: 'intake', field_key: 'respiration', value: inquiry.respiration })
  if (nonEmpty(inquiry.bp_systolic) && nonEmpty(inquiry.bp_diastolic)) {
    fields.push({
      section: 'intake',
      field_key: 'blood_pressure',
      value: `${inquiry.bp_systolic}/${inquiry.bp_diastolic}`,
    })
  }
  if (nonEmpty(inquiry.spo2))
    fields.push({ section: 'intake', field_key: 'spo2', value: inquiry.spo2 })
  if (nonEmpty(inquiry.height))
    fields.push({ section: 'intake', field_key: 'height', value: inquiry.height })
  if (nonEmpty(inquiry.weight))
    fields.push({ section: 'intake', field_key: 'weight', value: inquiry.weight })

  // ── record: 解析 recordContent 的【XX】章节,跟 jinsuanpan_map.yaml
  //   record_page.fields 的 label_name 对齐(中文标题 = field_key) ─────
  // 标题清单覆盖 backend/app/services/ai/record_renderer.py 全部
  // _section("【XXX】", ...) 输出 (门诊 + 急诊 + 住院三种形态全包)
  const sectionTitles = [
    // 病史类
    '主诉',
    '现病史',
    '既往史',
    '过敏史',
    '个人史',
    '家族史',
    '婚育史',
    '月经史',
    '病史陈述者',
    // 评估 / 检查
    '专项评估',
    '体格检查',
    '辅助检查',
    '辅助检查(入院前)',
    // 诊断
    '诊断',
    '入院诊断',
    '中医诊断',
    '西医诊断',
    // 治疗意见(门诊主标题)
    '治疗意见及措施',
    // 治疗意见的子项(医生现场也可能加成独立标题,兼容)
    '治则治法',
    '处理意见',
    '复诊建议',
    '注意事项',
    // 急诊专属
    '急诊处置',
    '急诊留观记录',
    '患者去向',
    // 追问补充
    '追问补充',
  ]
  // 复合段:HIS 没有这些"父标题"独立字段,内部各子项才是真字段
  //   【治疗意见及措施】 行内: 治则治法:.. 处理意见:.. 复诊建议:.. 注意事项:..
  //   【诊断】 行内: 中医诊断:.. 西医诊断:..
  //   【体格检查】 行内: 望诊:.. 闻诊:.. 切诊·舌象:.. 切诊·脉象:..
  // 子项 key 跟 backend/app/services/ai/record_renderer.py 的输出标签对齐,
  // 不要加别名(如"舌象"vs"切诊·舌象")避免同段被两个 key 重复匹配。
  // 最终能写入 HIS 哪些字段、要不要合并,由 Agent 按 jinsuanpan_map.yaml 决定。
  const COMPOUND_SECTIONS: Record<string, string[]> = {
    治疗意见及措施: ['治则治法', '处理意见', '复诊建议', '注意事项'],
    诊断: ['中医诊断', '西医诊断', '中医疾病诊断', '中医证候诊断'],
    体格检查: ['望诊', '闻诊', '切诊·舌象', '切诊·脉象'],
  }

  // 把一段复合内容里的"标签:..."子项拆出来推送
  const pushCompoundSubfields = (section: string, body: string) => {
    const subKeys = COMPOUND_SECTIONS[section]
    let matched = false
    for (const subKey of subKeys) {
      // 匹配"标签:内容" 或 "标签:内容\n标签2:内容2"
      // 用非贪婪匹配,内容直到下一个已知子标签或段尾
      const escaped = subKey.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const re = new RegExp(
        `${escaped}[:：]\\s*([\\s\\S]*?)(?=\\n\\s*(?:${subKeys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})[:：]|$)`
      )
      const m = body.match(re)
      if (m) {
        const value = m[1].trim()
        if (value && !/^\[未填写[,，]?\s*需补充\]?$/.test(value) && value !== '暂无') {
          fields.push({ section: 'record', field_key: subKey, value })
          matched = true
        }
      }
    }
    // 没找到任何子项就把整段当一个字段(兜底,真生产 Agent 写不进会转剪贴板)
    if (!matched) {
      fields.push({ section: 'record', field_key: section, value: body })
    }
  }

  // 拆分:遇到 【标题】 行就切一段;两个 标题 之间的内容归前一个标题
  // 兼容【X】和【 X】(空格)两种,以及【主 诉】这种空格分隔
  if (nonEmpty(recordContent)) {
    const lines = recordContent.split(/\r?\n/)
    let currentSection: string | null = null
    let buf: string[] = []
    const flush = () => {
      if (currentSection && buf.length) {
        const value = buf.join('\n').trim()
        // 跳过占位符 / 空段(避免把"[未填写,需补充]"也填进 HIS)
        if (value && !/^\[未填写[,，]?\s*需补充\]?$/.test(value) && value !== '暂无') {
          if (COMPOUND_SECTIONS[currentSection]) {
            // 复合段: HIS 没父标题字段,继续拆成子字段推
            pushCompoundSubfields(currentSection, value)
          } else {
            fields.push({ section: 'record', field_key: currentSection, value })
          }
        }
      }
      buf = []
    }
    for (const line of lines) {
      // 匹配【标题】行,允许标题里有空格,如【主 诉】
      const m = line.match(/^\s*【\s*([^】]+?)\s*】\s*$/)
      if (m) {
        flush()
        // 标题里的空格去掉,以便和 sectionTitles 匹配(主 诉 → 主诉)
        const title = m[1].replace(/\s+/g, '')
        // 只采纳已知标题,避免医生自定义的奇怪段污染填入
        currentSection = sectionTitles.includes(title) ? title : null
      } else if (currentSection) {
        buf.push(line)
      }
    }
    flush()
  }
  return fields
}
