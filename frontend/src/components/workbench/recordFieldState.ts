/**
 * 病历字段状态：写入前快照 / 精准撤销 / 光标定位（components/workbench/recordFieldState.ts）
 *
 * 2026-06-11 从 qcFieldMaps.ts 拆出，内容零改动。
 * 依赖 recordSectionWriter 的写入函数做撤销回写。
 */
import { FIELD_TO_SECTION, FIELD_TO_LINE_PREFIX } from './qcFieldConstants'
import { FIELD_NAME_LABEL } from './qcFieldMeta'
import { writeSectionToRecord, normalizeColon } from './recordSectionWriter'

/**
 * 字段级"写入前快照"——记录该字段在写入前的真实状态，供精准撤销用。
 *
 * 三种状态：
 *   - 'absent'      ：该字段对应的行 / 章节内容**不存在**（LLM 生成的精简版没生成）
 *   - 'placeholder' ：行 / 章节存在但内容是 "[未填写，需补充]"
 *   - 'value'       ：行 / 章节存在且有具体内容（医生之前手填的）
 *
 * 撤销语义：
 *   - 'absent'      → 删除该行 / 清空章节（恢复成"原本就没"）
 *   - 'placeholder' → 写回占位符（用户原本就看到占位符，撤销后还看到占位符）
 *   - 'value'       → 写回原值（用户手写过的内容不能丢）
 */
export interface FieldSnapshot {
  state: 'absent' | 'placeholder' | 'value'
  /** state='value' 时存原内容；其他状态忽略 */
  value?: string
}

const PLACEHOLDER_TEXT = '[未填写，需补充]'

/**
 * 读取指定字段在病历里的当前状态——给"写入前快照"用。
 *
 * 行级字段（FIELD_TO_LINE_PREFIX）：找前缀匹配的行
 * 章节级字段（FIELD_TO_SECTION）：找对应章节的内容
 */
export function snapshotFieldState(content: string, fieldName: string): FieldSnapshot {
  // 行级字段
  const lineConfig = FIELD_TO_LINE_PREFIX[fieldName]
  if (lineConfig) {
    const normPrefix = normalizeColon(lineConfig.prefix)
    const lines = content.split('\n')
    for (const line of lines) {
      if (normalizeColon(line.trim()).startsWith(normPrefix)) {
        // 取出"前缀后的值部分"
        const afterPrefix = line
          .trim()
          .substring(
            line.trim().indexOf(lineConfig.prefix.replace(/[:：]/g, '')) + lineConfig.prefix.length
          )
          .trim()
        // mode='whole_line' 时整行就是值（如 "T:36.5℃ P:78..."）
        const value = lineConfig.mode === 'whole_line' ? line.trim() : afterPrefix
        if (!value || value === PLACEHOLDER_TEXT) {
          return { state: 'placeholder' }
        }
        return { state: 'value', value: line } // 存整行便于精确还原
      }
    }
    return { state: 'absent' }
  }

  // 章节级字段
  const mapped = FIELD_TO_SECTION[fieldName]
  if (mapped === undefined || mapped === '') {
    return { state: 'absent' } // 全文类 / 未映射，撤销时不做特殊处理
  }
  const sectionPattern = /【[^】]+】/g
  const matches: Array<{ index: number; header: string }> = []
  let m: RegExpExecArray | null
  while ((m = sectionPattern.exec(content)) !== null) {
    matches.push({ index: m.index, header: m[0] })
  }
  const idx = matches.findIndex(s => s.header === mapped)
  if (idx === -1) return { state: 'absent' }
  const start = matches[idx].index + matches[idx].header.length
  const end = idx + 1 < matches.length ? matches[idx + 1].index : content.length
  const body = content.slice(start, end).trim()
  if (!body || body === PLACEHOLDER_TEXT) return { state: 'placeholder' }
  return { state: 'value', value: body }
}

/**
 * 按字段快照还原内容——撤销 QC 写入时调用。
 *
 * 行级字段（FIELD_TO_LINE_PREFIX）：
 *   - 'absent'      → 删除该行
 *   - 'placeholder' → 行内容置为占位符
 *   - 'value'       → 把原行写回（含前缀）
 *
 * 章节级字段：
 *   - 'absent'      → 章节内容清空（保留 header）
 *   - 'placeholder' → 章节内容置为占位符
 *   - 'value'       → 章节内容写回原值
 */
export function restoreFieldState(
  content: string,
  fieldName: string,
  snapshot: FieldSnapshot
): string {
  const lineConfig = FIELD_TO_LINE_PREFIX[fieldName]
  if (lineConfig) {
    return restoreLineFromSnapshot(
      content,
      lineConfig.section,
      lineConfig.prefix,
      snapshot,
      lineConfig.mode || 'value'
    )
  }
  // 章节级：用 writeSectionToRecord 逻辑回滚
  if (snapshot.state === 'value' && snapshot.value !== undefined) {
    return writeSectionToRecord(content, fieldName, snapshot.value)
  }
  // absent / placeholder 都用空串走 writeSectionToRecord，效果是清空章节内容（保留 header）
  return writeSectionToRecord(content, fieldName, '')
}

/** 行级字段的快照还原（含"删除整行"分支）。 */
function restoreLineFromSnapshot(
  content: string,
  sectionHeader: string,
  linePrefix: string,
  snapshot: FieldSnapshot,
  mode: 'value' | 'whole_line'
): string {
  const sectionPattern = /【[^】]+】/g
  const matches: Array<{ index: number; header: string }> = []
  let m: RegExpExecArray | null
  while ((m = sectionPattern.exec(content)) !== null) {
    matches.push({ index: m.index, header: m[0] })
  }
  const sectionIdx = matches.findIndex(s => s.header === sectionHeader)
  if (sectionIdx === -1) return content // 章节都不在了，撤销也没意义

  const sectionStart = matches[sectionIdx].index
  const sectionEnd =
    sectionIdx + 1 < matches.length ? matches[sectionIdx + 1].index : content.length
  const sectionText = content.slice(sectionStart, sectionEnd)
  const lines = sectionText.split('\n')
  const normPrefix = normalizeColon(linePrefix)

  // 找当前行
  const lineIdx = lines.findIndex(line => normalizeColon(line.trim()).startsWith(normPrefix))

  if (snapshot.state === 'absent') {
    // 删除该行（写入前根本没这行）
    if (lineIdx === -1) return content // 已经没了，nothing to do
    const newLines = lines.filter((_, i) => i !== lineIdx)
    return content.slice(0, sectionStart) + newLines.join('\n') + content.slice(sectionEnd)
  }

  // 'placeholder' 或 'value'：替换 / 插入该行
  const restoredLine =
    snapshot.state === 'value' && snapshot.value !== undefined
      ? snapshot.value
      : mode === 'whole_line'
        ? PLACEHOLDER_TEXT
        : `${linePrefix}${PLACEHOLDER_TEXT}`

  if (lineIdx !== -1) {
    const newLines = [...lines]
    newLines[lineIdx] = restoredLine
    return content.slice(0, sectionStart) + newLines.join('\n') + content.slice(sectionEnd)
  }
  // 该行不存在却要还原成 placeholder/value——通常不会走到（snapshot.state='absent' 才会缺行）
  // 防御性兜底：在章节末尾插入
  const newLines = [...lines]
  while (newLines.length > 1 && !newLines[newLines.length - 1].trim()) newLines.pop()
  newLines.push(restoredLine)
  return (
    content.slice(0, sectionStart) +
    newLines.join('\n') +
    '\n' +
    content.slice(sectionEnd).trimStart()
  )
}

/**
 * 定位字段在病历正文中的字符位置（用于 AI 写入字段池的 chip 跳转）
 *
 * 行级字段 → 找该行 prefix 在 content 中的 index
 * 章节级字段 → 找 section header 的 index
 * 未映射字段 → 返回 null
 *
 * Returns:
 *   { start, end }：选区起止字符 index，调用方用 textarea.setSelectionRange
 *                    + textarea.focus 把光标定位到该行。
 *   null：找不到（字段未映射 / prefix 不在 content 里）。
 */
export function locateFieldInRecord(
  content: string,
  fieldName: string
): { start: number; end: number } | null {
  // 1. 行级：找 prefix
  const lineConfig = FIELD_TO_LINE_PREFIX[fieldName]
  if (lineConfig) {
    // 先把冒号归一化（content 和 prefix 可能用中/英文冒号）
    const normalizedContent = normalizeColon(content)
    const normalizedPrefix = normalizeColon(lineConfig.prefix)
    const idx = normalizedContent.indexOf(normalizedPrefix)
    if (idx >= 0) {
      // 找该行结束位置（下一个换行）
      const lineEnd = normalizedContent.indexOf('\n', idx)
      return {
        start: idx,
        end: lineEnd === -1 ? content.length : lineEnd,
      }
    }
    // prefix 找不到 → 退回 section header 兜底
    if (lineConfig.section) {
      const sectionIdx = content.indexOf(lineConfig.section)
      if (sectionIdx >= 0) {
        return { start: sectionIdx, end: sectionIdx + lineConfig.section.length }
      }
    }
    return null
  }

  // 2. 章节级：找 section header
  const mapped = FIELD_TO_SECTION[fieldName]
  if (mapped) {
    const idx = content.indexOf(mapped)
    if (idx >= 0) {
      return { start: idx, end: idx + mapped.length }
    }
  }

  // 3. fallback：尝试 fieldName 本身作 header
  const fallbackHeader = `【${FIELD_NAME_LABEL[fieldName] || fieldName}】`
  const idx = content.indexOf(fallbackHeader)
  if (idx >= 0) {
    return { start: idx, end: idx + fallbackHeader.length }
  }
  return null
}
