/**
 * 病历章节解析工具（utils/recordSections.ts）
 *
 * 用途：
 *   AI 生成 / 润色后，对 markdown 风格的病历文本（用【主诉】/【现病史】等
 *   标题分段）做两件事：
 *     1. 章节守卫：提取所有章节用于"润色后比对"，发现 LLM 误删章节时还原
 *     2. 反向同步：把生成结果按章节解析回左侧问诊字段，确保左右一致
 *
 * 抽出来的原因：useRecordEditor.ts 主要是 AI 工作流编排，把字符串解析放回
 * 工具层，hook 主体更聚焦。
 */

/**
 * 提取病历所有章节，返回 Map<标题, 完整段落文本>。
 * 标题形如 `【主诉】`，段落到下一个 `【` 或文末为止。
 */
export function extractSections(text: string): Map<string, string> {
  const map = new Map<string, string>()
  const pattern = /【[^】]+】/g
  const matches: Array<{ header: string; index: number }> = []
  let m: RegExpExecArray | null
  while ((m = pattern.exec(text)) !== null) {
    matches.push({ header: m[0], index: m.index })
  }
  for (let i = 0; i < matches.length; i++) {
    const start = matches[i].index
    const end = i + 1 < matches.length ? matches[i + 1].index : text.length
    map.set(matches[i].header, text.slice(start, end).trimEnd())
  }
  return map
}

/**
 * 把生成的病历内容按章节反解为 inquiry 字段字典。
 *
 * 注意：
 *   既往/过敏/个人/月经史 不写回 inquiry——这些字段属于 PatientProfile，
 *   由 PatientProfileCard 单独维护，避免 AI 单次生成覆盖患者纵向档案。
 *
 *   体格检查段落需要分离"望诊/闻诊/切诊/舌脉象"等中医字段，与"其余阳性体征"
 *   合并写回 physical_exam，避免中医字段串到体检里。
 */
export function parseGeneratedSectionsToInquiry(content: string): Record<string, string> {
  const result: Record<string, string> = {}
  const pattern = /【([^】]+)】[^\S\n]*\n?([\s\S]*?)(?=\n【|$)/g
  let m: RegExpExecArray | null
  while ((m = pattern.exec(content)) !== null) {
    const text = m[2].trim()
    if (!text) continue
    switch (m[1]) {
      case '主诉':
        result.chief_complaint = text
        break
      case '现病史':
        result.history_present_illness = text
        break
      case '体格检查': {
        // 滤掉望/闻/切诊（含舌脉象）行，剩下的部分认为是普通体检文字
        const filteredLines = text.split('\n').filter(line => {
          const trimmed = line.trim()
          return (
            !trimmed.match(/^(望诊|闻诊|切诊[··]?舌象|切诊[··]?脉象|舌象|脉象)[：:]/u) &&
            !trimmed.match(/^其余阳性体征[：:]/u)
          )
        })
        const physicalLine = text.split('\n').find(l => l.trim().match(/^其余阳性体征[：:]/u))
        const physicalContent = physicalLine
          ? physicalLine.replace(/^其余阳性体征[：:]\s*/u, '').trim()
          : ''
        result.physical_exam = [physicalContent, filteredLines.join('\n').trim()]
          .filter(Boolean)
          .join('\n')
          .trim()
        break
      }
      case '辅助检查':
        result.auxiliary_exam = text
        break
      case '初步诊断':
        result.initial_impression = text
        break
    }
  }
  return result
}

/**
 * 章节守卫：对比 original 和 polished，找出被误删的章节并补回到末尾。
 *
 * Returns:
 *   { restored: 还原后的文本; missing: 被误删的章节标题列表 }
 *   missing 为空表示润色完整，无需提示用户
 */
export function restoreMissingSections(
  original: string,
  polished: string
): { restored: string; missing: string[] } {
  const originalSections = extractSections(original)
  const polishedSections = extractSections(polished)
  const missing: string[] = []
  let restored = polished
  for (const [header, sectionText] of originalSections) {
    if (!polishedSections.has(header)) {
      missing.push(header)
      restored = restored.trimEnd() + '\n\n' + sectionText
    }
  }
  return { restored, missing }
}
