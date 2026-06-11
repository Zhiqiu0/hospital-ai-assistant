/**
 * 复合段结构化合并写入器（2026-06-11 治本）
 *
 * 背景 bug：AI 批量补全 / QC 逐条修复对"父段"（如【体格检查】）做章节级写入时，
 * writeSectionToRecord 原本是**整段替换**——会把段内医生已填写的子行
 * （望诊/闻诊/切诊·舌象/切诊·脉象等）一起冲掉，造成医生录入数据丢失。
 *
 * 根因：QC 问题列表天然混合两种粒度——规则引擎产出子字段级问题（舌象/脉象），
 * LLM 质量建议产出父段级问题（体格检查/诊断）。两种粒度的修复文本都会走
 * writeSectionToRecord，父段整段替换与子行行级写入互相破坏。
 *
 * 治本方案：对已知的"复合段"，章节级写入不再整段替换，而是**结构化合并**：
 *   1. 把修复文本拆成"子行（带已知前缀）"和"自由文本（无前缀）"两类；
 *   2. 子行 → 只替换段内同前缀的行，其余子行原样保留；
 *   3. 自由文本 → 只替换段内原有的自由文本行（通常是段首的一般描述/占位符），
 *      不触碰任何带前缀的子行。
 *
 * 该函数是纯文本函数，不依赖 qcFieldMaps，由 writeSectionToRecord 在
 * 命中 COMPOUND_SECTION_PREFIXES 时调用。
 */

/** 复合段 → 段内受保护的子行前缀清单（与 record_renderer 模板布局对齐） */
export const COMPOUND_SECTION_PREFIXES: Record<string, string[]> = {
  '【体格检查】': ['T:', '望诊：', '闻诊：', '切诊·舌象：', '切诊·脉象：', '其余阳性体征：'],
  '【诊断】': ['中医诊断：', '西医诊断：'],
  '【治疗意见及措施】': ['治则治法：', '处理意见：', '复诊建议：', '注意事项：'],
}

/** 中英文冒号归一化（与 qcFieldMaps.normalizeColon 行为一致，独立实现避免循环依赖） */
function normColon(text: string): string {
  return text.replace(/:/g, '：')
}

/** 判断一行文本命中哪个前缀；未命中返回 null */
function matchPrefix(line: string, prefixes: string[]): string | null {
  const norm = normColon(line.trim())
  for (const p of prefixes) {
    if (norm.startsWith(normColon(p))) return p
  }
  return null
}

/**
 * 把修复文本拆成逻辑行：
 *   - 先按换行拆；
 *   - 再把"一行里塞了多个子前缀"的情况按 ；/; 二次拆开
 *     （LLM 常输出"中医诊断：X；西医诊断：Y"这种合并行）。
 */
function splitFixLines(fixText: string, prefixes: string[]): string[] {
  const out: string[] = []
  for (const rawLine of fixText.split('\n')) {
    const line = rawLine.trim()
    if (!line) continue
    // 统计该行包含几个前缀；≥2 个时按分号拆段，让每个前缀独立成行
    const hits = prefixes.filter(p => normColon(line).includes(normColon(p)))
    if (hits.length >= 2) {
      for (const seg of line.split(/[；;]/)) {
        const s = seg.trim()
        if (s) out.push(s)
      }
    } else {
      out.push(line)
    }
  }
  return out
}

/**
 * 复合段结构化合并：用 fixText 更新 oldBody（段 header 之后、下一段之前的正文），
 * 返回新的段正文。保证：fixText 没提到的受保护子行**原样保留**。
 *
 * @param oldBody  当前段正文（不含 header）
 * @param fixText  修复/补全文本（可能含子行，也可能是纯自由文本）
 * @param prefixes 该段受保护的子行前缀
 */
export function mergeCompoundSectionBody(
  oldBody: string,
  fixText: string,
  prefixes: string[]
): string {
  const fixLines = splitFixLines(fixText, prefixes)

  // 新文本按前缀归类：prefix → 完整行；无前缀的归入自由文本
  const newByPrefix = new Map<string, string>()
  const newFree: string[] = []
  for (const line of fixLines) {
    const p = matchPrefix(line, prefixes)
    if (p) {
      // 同前缀重复时保留首个（与后端 _validate_items 去重规则一致）
      if (!newByPrefix.has(p)) newByPrefix.set(p, line)
    } else {
      newFree.push(line)
    }
  }

  const oldLines = oldBody.split('\n').filter(l => l.trim() !== '')
  const result: string[] = []
  const consumed = new Set<string>()
  let freeWritten = false

  for (const oldLine of oldLines) {
    const p = matchPrefix(oldLine, prefixes)
    if (p) {
      // 受保护子行：新文本提供了同前缀行则替换，否则原样保留（核心保证）
      if (newByPrefix.has(p) && !consumed.has(p)) {
        result.push(newByPrefix.get(p)!)
        consumed.add(p)
      } else {
        result.push(oldLine)
      }
    } else {
      // 自由文本行：有新自由文本则整体替换（只替换一次），没有则保留
      if (newFree.length > 0) {
        if (!freeWritten) {
          result.push(...newFree)
          freeWritten = true
        }
        // 已替换过：旧自由文本行丢弃（视为被新文本覆盖）
      } else {
        result.push(oldLine)
      }
    }
  }

  // 新自由文本存在但旧段没有自由文本行 → 插到段首（一般描述习惯在子行之前）
  if (newFree.length > 0 && !freeWritten) {
    result.unshift(...newFree)
  }
  // 新子行在旧段中没有对应行 → 追加到段尾，内容不丢
  for (const [p, line] of newByPrefix) {
    if (!consumed.has(p)) result.push(line)
  }

  return result.join('\n')
}
