/**
 * 病历章节/子行写入核心（components/workbench/recordSectionWriter.ts）
 *
 * 2026-06-11 从 qcFieldMaps.ts 拆出，内容零改动。
 * 含：冒号归一化、行级写入、中医诊断合并行拆合、章节级写入（含复合段
 * 结构化合并保护）。快照/撤销/定位逻辑在 recordFieldState.ts。
 */
import { COMPOUND_SECTION_PREFIXES, mergeCompoundSectionBody } from './compoundSectionWriter'
import { FIELD_TO_SECTION, FIELD_TO_LINE_PREFIX } from './qcFieldConstants'
import { FIELD_NAME_LABEL, NON_WRITABLE_FIELDS } from './qcFieldMeta'

/**
 * 把字符串里的英文冒号统一成中文冒号，便于跨格式匹配。
 *
 * 解决场景：
 *   prompt 模板里写的是 "T:__℃"（英文冒号），但 LLM 实际输出可能是
 *   "T：36.5°C"（中文冒号）或两者混用。前缀匹配时归一化两端，
 *   保证 "T:"、"T："、"T :" 都能命中"T:"前缀。
 */
export function normalizeColon(s: string): string {
  return s.replace(/:/g, '：')
}

/**
 * 在指定章节内"行级"替换/插入。
 *
 * 行为：
 *   - 章节存在 + 前缀行存在  → 按 mode 替换该行
 *       mode='value'      ：替换前缀后的内容（保留前缀）
 *       mode='whole_line' ：整行换成 fix_text（fix_text 自带前缀）
 *   - 章节存在 + 前缀行不存在 → 在章节末尾插入新行
 *   - 章节不存在               → 兜底：在病历末尾追加新章节 + 单行内容
 *   - 取消写入（fixText 为空） + 行存在 → 行内容回滚到 "[未填写，需补充]"
 *   - 取消写入 + 行不存在               → 不动
 */
function writeLineInSection(
  content: string,
  sectionHeader: string,
  linePrefix: string,
  fixText: string,
  mode: 'value' | 'whole_line' = 'value'
): string {
  // 1. 找所有章节位置
  const sectionPattern = /【[^】]+】/g
  const matches: Array<{ index: number; header: string }> = []
  let m: RegExpExecArray | null
  while ((m = sectionPattern.exec(content)) !== null) {
    matches.push({ index: m.index, header: m[0] })
  }
  const sectionIdx = matches.findIndex(s => s.header === sectionHeader)

  // 工具：fix_text 为空时的回滚值（占位符或保留章节模板）
  const placeholder = '[未填写，需补充]'
  const trimmedFix = fixText.trim()

  // 2. 章节不存在 → 治本（2026-05-19）：不再兜底追加新章节
  //
  // 旧实现把"映射缺失/章节没渲染"的 fix 文本悄悄写到病历末尾创建错误章节，
  // 是治疗意见/中医诊断/舌脉反复 bug 的根因。
  // 现在改成返回原 content，由调用方（QCIssuePanel）检测到"没变化"弹提示。
  if (sectionIdx === -1) {
    return content
  }

  // 3. 章节范围内做行级处理
  const sectionStart = matches[sectionIdx].index
  const sectionEnd =
    sectionIdx + 1 < matches.length ? matches[sectionIdx + 1].index : content.length
  const sectionText = content.slice(sectionStart, sectionEnd)
  const lines = sectionText.split('\n')

  // 行匹配统一走"归一化冒号 + trim 后 startsWith"，兼容中英文冒号 + 行首空格
  const normPrefix = normalizeColon(linePrefix)
  const writeValue = trimmedFix || placeholder

  let replaced = false
  const newLines = lines.map(line => {
    if (normalizeColon(line.trim()).startsWith(normPrefix)) {
      replaced = true
      return mode === 'whole_line' ? writeValue : linePrefix + writeValue
    }
    return line
  })

  if (replaced) {
    return content.slice(0, sectionStart) + newLines.join('\n') + content.slice(sectionEnd)
  }

  // 4. 没找到前缀行：取消写入则不动；否则在章节末尾插入新行
  if (!trimmedFix) return content

  // 移除章节末尾空行后插入新行
  while (newLines.length > 1 && !newLines[newLines.length - 1].trim()) {
    newLines.pop()
  }
  newLines.push(mode === 'whole_line' ? trimmedFix : linePrefix + writeValue)
  // 章节之间保留空行
  return (
    content.slice(0, sectionStart) +
    newLines.join('\n') +
    '\n' +
    content.slice(sectionEnd).trimStart()
  )
}

/**
 * 中医诊断合并行 split / merge 工具——与后端
 * `_split_tcm_diagnosis` (completeness_rules.py) +
 * `_merge_tcm_diagnosis`  (record_renderer.py) 完全对齐：
 *
 *   "X — Y"  → disease=X  syndrome=Y
 *   "X(Y)"   → disease=X  syndrome=Y
 *   "X"      → disease=X  syndrome=""
 *
 * 在前端复刻这套拆/合逻辑是为了治本一个生产 bug（2026-05-02）：
 *   tcm_disease_diagnosis 与 tcm_syndrome_diagnosis 共用同一个【中医诊断】合并行，
 *   QC「逐条修复」按字段写回时整段章节替换 → 冲掉另一半 → 再次质控仍报缺。
 *   修法：写入前从合并行拆出另一半，merge 后再写整行。
 */
const TCM_DIAG_PLACEHOLDER = '[未填写，需补充]'

export function splitTcmDiagnosis(merged: string): { disease: string; syndrome: string } {
  const text = (merged || '').trim()
  if (!text || text === TCM_DIAG_PLACEHOLDER) return { disease: '', syndrome: '' }
  // X — Y / X – Y / X——Y（em / en / ASCII dash 都接受，与后端一致）
  let m = text.match(/^(.+?)\s*[—–-]+\s*(.+)$/)
  if (m) {
    const d = m[1].trim()
    const s = m[2].trim()
    return {
      disease: d === TCM_DIAG_PLACEHOLDER ? '' : d,
      syndrome: s === TCM_DIAG_PLACEHOLDER ? '' : s,
    }
  }
  // X（Y） / X(Y)
  m = text.match(/^(.+?)\s*[（(]\s*(.+?)\s*[）)]\s*$/)
  if (m) return { disease: m[1].trim(), syndrome: m[2].trim() }
  // 单值 → 全部视作疾病诊断（与后端 _split_tcm_diagnosis 一致）
  return { disease: text, syndrome: '' }
}

export function mergeTcmDiagnosis(disease: string, syndrome: string): string {
  const hasD = !!disease && disease !== TCM_DIAG_PLACEHOLDER
  const hasS = !!syndrome && syndrome !== TCM_DIAG_PLACEHOLDER
  if (hasD && hasS) return `${disease} — ${syndrome}`
  if (hasD) return disease
  if (hasS) return `${TCM_DIAG_PLACEHOLDER} — ${syndrome}`
  return TCM_DIAG_PLACEHOLDER
}

/** 读取病历当前【中医诊断】合并行内容；若无独立章节则尝试从【诊断】里"中医诊断：xxx"行抽。 */
function readTcmDiagnosisBody(content: string): string {
  const idxIndep = content.indexOf('【中医诊断】')
  if (idxIndep !== -1) {
    const after = content.slice(idxIndep + '【中医诊断】'.length)
    const next = after.match(/【[^】]+】/)
    return after.slice(0, next ? next.index! : after.length).trim()
  }
  const idxDiag = content.indexOf('【诊断】')
  if (idxDiag !== -1) {
    const after = content.slice(idxDiag + '【诊断】'.length)
    const next = after.match(/【[^】]+】/)
    const body = after.slice(0, next ? next.index! : after.length)
    const m = body.match(/中医诊断[:：]\s*([^\n]+)/)
    if (m) return m[1].trim()
  }
  return ''
}

/**
 * 将修复文本写入病历对应章节（找到 header 则替换，找不到则追加）
 *
 * 字段分 3 类处理（按优先级）：
 *   1. 命中 FIELD_TO_LINE_PREFIX → 走行级替换（中医四诊、专项评估 7 项）
 *   2. mapped === ''             → **明确跳过**（全文类规则，如 content / onset_time）
 *   3. mapped === undefined      → **fallback 追加**（未映射字段用 fieldName/中文标签当章节名）
 *   4. 其他                      → 正常章节定位（精确匹配 → 模糊匹配 → 末尾追加）
 *
 * 中医诊断特殊预处理：
 *   tcm_disease_diagnosis / tcm_syndrome_diagnosis 共用【中医诊断】合并行，单独写入
 *   某一项时必须保留另一项，否则会冲掉。先 split 再 merge 后再走章节写入。
 */
export function writeSectionToRecord(content: string, fieldName: string, fixText: string): string {
  // 治本短路（2026-05-19）：不可写入正文的字段（如患者档案、就诊时间、中医四诊集合）
  // 直接返回原 content。调用方（QCIssuePanel）应在调用前就拦截并显示
  // NON_WRITABLE_HINTS 文案；这里是兜底安全网，防止误调用。
  if (NON_WRITABLE_FIELDS.has(fieldName)) {
    return content
  }

  // 中医诊断合并行：先读现有 → 拆 → 用新值替换对应一项 → 合并 → 后续按整段写入
  if (fieldName === 'tcm_disease_diagnosis' || fieldName === 'tcm_syndrome_diagnosis') {
    const existing = readTcmDiagnosisBody(content)
    const { disease, syndrome } = splitTcmDiagnosis(existing)
    const trimmed = (fixText || '').trim()
    fixText =
      fieldName === 'tcm_disease_diagnosis'
        ? mergeTcmDiagnosis(trimmed, syndrome)
        : mergeTcmDiagnosis(disease, trimmed)
  }

  // 优先级 1：行级写入（中医四诊 / 专项评估子项 / 生命体征）
  const lineConfig = FIELD_TO_LINE_PREFIX[fieldName]
  if (lineConfig) {
    const lineResult = writeLineInSection(
      content,
      lineConfig.section,
      lineConfig.prefix,
      fixText,
      lineConfig.mode || 'value'
    )
    // 2026-06-11 治本：行级目标章节不存在时（如住院"日常病程记录"没有
    // 【治疗意见及措施】，但"注意事项"是独立章节），不再静默放弃，
    // 而是继续往下走章节级定位——同一字段在不同病历类型里粒度不同，
    // 单一行级映射覆盖不了所有模板。写入成功（内容有变化）则直接返回。
    if (lineResult !== content) {
      return lineResult
    }
  }

  const mapped = FIELD_TO_SECTION[fieldName]

  // 明确跳过的字段（全文类）—— 保持原行为
  if (mapped === '') return content

  // 未映射字段：fallback 用 FIELD_NAME_LABEL 或 fieldName 本身当章节标题追加
  // 这样即使漏了映射，内容不会丢，医生至少能在病历末尾看到一条"【XXX】"章节
  const primaryHeader = mapped ?? `【${FIELD_NAME_LABEL[fieldName] || fieldName}】`

  // 从章节标题提取核心关键词（去掉「入院」「初步」「（入院前）」等修饰成分）
  const coreKeyword = primaryHeader
    .replace(/[【】]/g, '')
    .replace(/入院|初步|（[^）]*）/g, '')
    .trim()

  // 找到记录里所有章节的位置
  const sectionPattern = /【[^】]+】/g
  const matches: Array<{ index: number; header: string }> = []
  let m: RegExpExecArray | null
  while ((m = sectionPattern.exec(content)) !== null) {
    matches.push({ index: m.index, header: m[0] })
  }

  // 1. 精确匹配
  let targetIdx = matches.findIndex(s => s.header === primaryHeader)
  // 2. 核心关键词模糊匹配
  if (targetIdx === -1 && coreKeyword) {
    targetIdx = matches.findIndex(s => s.header.includes(coreKeyword))
  }

  const header = targetIdx !== -1 ? matches[targetIdx].header : primaryHeader

  // 取消写入（fixText 为空）：只清空章节内容，保留 header
  // 不能整节删除：那样再次写入时找不到原位置，会被追加到文末
  if (!fixText.trim()) {
    if (targetIdx === -1) return content
    const start = matches[targetIdx].index
    const headerEnd = start + matches[targetIdx].header.length
    const end = targetIdx + 1 < matches.length ? matches[targetIdx + 1].index : content.length
    // 复合段保护（2026-06-11）：清空复合段时只清自由文本，受保护子行
    // （望诊/舌脉/中西医诊断等医生可能已填的行）原样保留，防止回滚时丢数据
    const clearPrefixes = COMPOUND_SECTION_PREFIXES[matches[targetIdx].header]
    if (clearPrefixes) {
      const oldBody = content.slice(headerEnd, end)
      const keptBody = mergeCompoundSectionBody(oldBody, '[未填写，需补充]', clearPrefixes)
      const tail = content.slice(end).replace(/^\s+/, '')
      return content.slice(0, headerEnd) + '\n' + keptBody + '\n\n' + (tail ? tail : '')
    }
    // 保留 header + 一个换行，让再次写入能定位到原位置
    const tail = content.slice(end).replace(/^\s+/, '')
    return content.slice(0, headerEnd) + '\n\n' + (tail ? tail : '')
  }

  // 写入：替换已有章节
  //
  // 治本（2026-05-19）：原"章节不存在 → 兜底追加到病历末尾"是反复 bug 的根因——
  // 映射缺失/拼写错误时悄悄追加错误章节，掩盖问题。改成返回原内容，
  // 调用方（QCIssuePanel）的"nextContent === recordContent"检测会触发，
  // 给医生弹"未能定位到章节"提示，让映射 bug 在交付前暴露。
  if (targetIdx === -1) {
    return content
  }
  const start = matches[targetIdx].index
  const end = targetIdx + 1 < matches.length ? matches[targetIdx + 1].index : content.length

  // 复合段保护（2026-06-11 治本）：【体格检查】【诊断】【治疗意见及措施】这类
  // 含受保护子行（望诊/舌脉/中西医诊断等）的段，章节级写入改走结构化合并——
  // 只更新修复文本明确给出的子行与自由文本，其余子行（医生已填内容）原样保留。
  // 否则整段替换会把医生手填的切诊·舌象/脉象等数据冲掉（E2E 实测复现的 P0 bug）。
  const protectedPrefixes = COMPOUND_SECTION_PREFIXES[header]
  if (protectedPrefixes) {
    const oldBody = content.slice(start + header.length, end)
    const mergedBody = mergeCompoundSectionBody(oldBody, fixText, protectedPrefixes)
    return (
      content.slice(0, start) + header + '\n' + mergedBody + '\n\n' + content.slice(end).trimStart()
    )
  }

  return content.slice(0, start) + header + '\n' + fixText + '\n' + content.slice(end).trimStart()
}
