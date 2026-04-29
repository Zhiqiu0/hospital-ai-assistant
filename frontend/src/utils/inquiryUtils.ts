/**
 * 问诊/病历工具函数（utils/inquiryUtils.ts）
 *
 * 提取自 useInquiryPanel 和 useInpatientInquiryPanel 的共享纯函数，
 * 两个 hook 都依赖这里，避免重复维护。
 */
import { message } from 'antd'
import {
  writeSectionToRecord,
  FIELD_TO_SECTION,
  FIELD_TO_LINE_PREFIX,
} from '@/components/workbench/qcFieldMaps'

/**
 * 判断字段是否能写入病历（章节级或行级二选一）。
 *
 * 历史踩坑：
 *   原实现只查 FIELD_TO_SECTION，把生命体征/中医四诊等"行级"字段误判为"不可写入"
 *   而被静默跳过——语音 AI 输出 physical_exam_vitals 字段时直接丢弃。
 *   2026-04-29 治本时把 physical_exam_vitals 从 FIELD_TO_SECTION 移到
 *   FIELD_TO_LINE_PREFIX，本判断同步覆盖两表。
 */
function canWriteField(fieldName: string): boolean {
  if (FIELD_TO_LINE_PREFIX[fieldName]) return true
  const mapped = FIELD_TO_SECTION[fieldName]
  return mapped !== undefined && mapped !== ''
}

/**
 * 行级字段（FIELD_TO_LINE_PREFIX）归属的章节名，用于 toast 展示。
 *
 * 行级字段不直接对应独立章节而是写入某章节内的一行（如 physical_exam_vitals 是
 * 【体格检查】下的 "T:..." 行），但医生在 toast 上希望看到"我刚才把哪几段更新了"，
 * 所以这里收口一份归属映射，仅供展示用，不影响实际写入逻辑。
 */
const LINE_FIELD_TO_DISPLAY_SECTION: Record<string, string> = {
  physical_exam_vitals: '【体格检查】',
  望诊: '【体格检查】',
  闻诊: '【体格检查】',
  舌象: '【体格检查】',
  脉象: '【体格检查】',
}

/**
 * 叙述类长字段白名单：续录场景下走 append（追加到章节末尾）而不是 replace（整段替换）。
 *
 * 配套 prompt（VOICE_STRUCTURE_PROMPT_*）的【a 类字段输出策略】——LLM 仅输出 delta，
 * 前端把 delta 追加到原章节内容末尾，让医生的手改原样保留。
 *
 * 不在白名单的字段（主诉/各诊断/评估值/生命体征等"原子字段"）走 replace：
 *   - 这些字段语义上是"原子整体替换"——续录修正诊断时直接覆盖原诊断更合理
 *   - 也包括无明确章节归属的全文类字段（content / onset_time 等，本就跳过写入）
 */
const APPEND_NARRATIVE_FIELDS = new Set<string>([
  'history_present_illness',
  'past_history',
  'personal_history',
  'marital_history',
  'menstrual_history',
  'family_history',
  'allergy_history',
  'current_medications',
  'auxiliary_exam',
  'physical_exam',
])

/**
 * 取病历某章节当前的内容文本（不含 header），用于 append 前判断章节是否已有有效内容。
 *
 * 简单实现：找到章节标题位置 → 截取到下一个章节标题（或文末） → 去除首尾空白。
 */
function getSectionBody(content: string, sectionHeader: string): string {
  const idx = content.indexOf(sectionHeader)
  if (idx === -1) return ''
  const after = content.slice(idx + sectionHeader.length)
  const nextMatch = after.match(/【[^】]+】/)
  const end = nextMatch ? nextMatch.index! : after.length
  return after.slice(0, end).trim()
}

/** 章节内容是否仅占位符（[未填写...] / [待补充...]）—— 这种情况应走 replace 而非 append。 */
function isPlaceholderBody(body: string): boolean {
  if (!body) return true
  return /^\[(未填写|待补充|未提及)[，,]?\s*[^[\]]*\]$/.test(body)
}

function fieldToDisplaySection(fieldName: string): string | null {
  const mapped = FIELD_TO_SECTION[fieldName]
  if (mapped) return mapped
  if (LINE_FIELD_TO_DISPLAY_SECTION[fieldName]) return LINE_FIELD_TO_DISPLAY_SECTION[fieldName]
  // 命中 LINE_PREFIX 但未在上面归属表 → 归到【专项评估】（住院评估子项落这里）
  if (FIELD_TO_LINE_PREFIX[fieldName]) return '【专项评估】'
  return null
}

/**
 * 生命体征行（physical_exam_vitals）格式契约：
 *   T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg SpO2:98% 身高:170cm 体重:65kg
 * 各字段缺失则省略不写（与后端 record_renderer / record_schemas 约定一致）。
 *
 * 续录场景下 LLM 输出 vital_signs 嵌套对象（仅含本次新增子字段），如果直接整行
 * 替换会冲掉病历里已有的 T:/P:/R:/BP: 数值。所以入口要先：
 *   1. 解析病历当前【体格检查】首行 T:... 提取已有数值
 *   2. 与 patch 中新增子字段合并（新值优先）
 *   3. 重新拼成完整 T:/P:/R:/BP: 行
 *   4. 走 physical_exam_vitals 行级写入路径（whole_line 整行替换）
 */
const VITAL_SIGNS_PARSERS: Array<[string, RegExp]> = [
  ['temperature', /T[:：]\s*([\d.]+)/],
  ['pulse', /P[:：]\s*([\d.]+)/],
  ['respiration', /R[:：]\s*([\d.]+)/],
  ['bp_systolic', /BP[:：]\s*([\d.]+)\s*\//],
  ['bp_diastolic', /BP[:：]\s*[\d.]+\s*\/\s*([\d.]+)/],
  ['spo2', /SpO2[:：]\s*([\d.]+)/],
  ['height', /身高[:：]\s*([\d.]+)/],
  ['weight', /体重[:：]\s*([\d.]+)/],
]

export function parseVitalSignsFromRecord(content: string): Record<string, string> {
  const headerIdx = content.indexOf('【体格检查】')
  if (headerIdx === -1) return {}
  const after = content.slice(headerIdx + '【体格检查】'.length)
  const nextSection = after.match(/\n【[^】]+】/)
  const sectionEnd = nextSection ? nextSection.index! : after.length
  const body = after.slice(0, sectionEnd)
  const lines = body
    .split('\n')
    .map(l => l.trim())
    .filter(Boolean)
  const vitalsLine = lines.find(l => /^T[:：]/.test(l)) || ''
  const result: Record<string, string> = {}
  for (const [key, pattern] of VITAL_SIGNS_PARSERS) {
    const m = vitalsLine.match(pattern)
    if (m) result[key] = m[1]
  }
  return result
}

function formatVitalSignsLine(vs: Record<string, string>): string {
  const parts: string[] = []
  if (vs.temperature) parts.push(`T:${vs.temperature}℃`)
  if (vs.pulse) parts.push(`P:${vs.pulse}次/分`)
  if (vs.respiration) parts.push(`R:${vs.respiration}次/分`)
  if (vs.bp_systolic && vs.bp_diastolic) {
    parts.push(`BP:${vs.bp_systolic}/${vs.bp_diastolic}mmHg`)
  }
  if (vs.spo2) parts.push(`SpO2:${vs.spo2}%`)
  if (vs.height) parts.push(`身高:${vs.height}cm`)
  if (vs.weight) parts.push(`体重:${vs.weight}kg`)
  return parts.join(' ')
}

/**
 * 对 patch.vital_signs 嵌套子字段与病历现有 T:/P:/R:/BP: 行做去重——
 * AI 在续录场景下可能重复输出基线已有的子字段值（嵌套字段层级 prompt 增量规则
 * 难以严格约束），前端在数据流上游做兜底过滤：
 *   - 子字段值与现有完全相同 → 剔除（基线已有，无需重复展示/写入）
 *   - 子字段值不同或现有为空 → 保留（真正的修正/新增）
 *   - 全部子字段都被剔除 → 整个 vital_signs 字段从 patch 删除
 * 用于预览卡渲染前对 pendingPatch 做净化，让医生只看到真正变化的字段。
 */
export function dedupeVitalSignsAgainstRecord(
  patch: Record<string, unknown>,
  recordContent: string
): Record<string, unknown> {
  const vs = patch.vital_signs
  if (!vs || typeof vs !== 'object' || Array.isArray(vs)) return patch
  const existing = parseVitalSignsFromRecord(recordContent)
  const filtered: Record<string, string> = {}
  for (const [k, v] of Object.entries(vs as Record<string, unknown>)) {
    const norm = typeof v === 'string' ? v.trim() : typeof v === 'number' ? String(v) : ''
    if (!norm) continue
    if (existing[k] && existing[k] === norm) continue
    filtered[k] = norm
  }
  const { vital_signs: _drop, ...rest } = patch
  if (!Object.keys(filtered).length) return rest
  return { ...rest, vital_signs: filtered }
}

/**
 * 把 patch 里的 vital_signs 嵌套对象解构、合并到 physical_exam_vitals 整行字段。
 * 子字段全空时直接删除嵌套字段，避免下游 typeof 判断把整个对象误当成"非空"。
 */
function mergeVitalSignsIntoPatch(
  patch: Record<string, unknown>,
  recordContent: string
): Record<string, unknown> {
  const vs = patch.vital_signs
  if (!vs || typeof vs !== 'object' || Array.isArray(vs)) return patch
  const incoming: Record<string, string> = {}
  for (const [k, v] of Object.entries(vs as Record<string, unknown>)) {
    if (typeof v === 'string' && v.trim()) incoming[k] = v.trim()
    else if (typeof v === 'number') incoming[k] = String(v)
  }
  // 解构掉 vital_signs 字段（不管有无新值都剔除，避免后续遍历踩到嵌套对象）
  const { vital_signs: _drop, ...rest } = patch
  if (!Object.keys(incoming).length) return rest
  // 合并已有 + 新增，重新拼整行；如果 patch 里也直接给了 physical_exam_vitals 字符串，
  // LLM 显式覆盖意图优先，不再合并
  if (typeof rest.physical_exam_vitals === 'string' && rest.physical_exam_vitals.trim()) {
    return rest
  }
  const existing = parseVitalSignsFromRecord(recordContent)
  const merged = { ...existing, ...incoming }
  return { ...rest, physical_exam_vitals: formatVitalSignsLine(merged) }
}

/**
 * 单字段写入策略（语音追记场景核心逻辑）：
 *   - 叙述类字段 + 章节非空且非占位符 → append（取出原章节正文，拼上 delta，再走 writeSection
 *     整段写回，保证章节边界处理与原行为一致）
 *   - 叙述类字段 + 章节空/占位符 → 退化为 replace（首次写入时不需要追加，直接 replace 即可）
 *   - 原子字段 / 行级字段 / 全文类字段 → replace（沿用 writeSectionToRecord 原行为）
 */
function applyFieldToRecord(content: string, fieldName: string, value: string): string {
  // 非叙述类字段直接走原 replace 路径（含行级字段，writeSectionToRecord 内部会路由）
  if (!APPEND_NARRATIVE_FIELDS.has(fieldName)) {
    return writeSectionToRecord(content, fieldName, value)
  }
  // 叙述类字段：先看章节当前是否已有内容
  const sectionHeader = FIELD_TO_SECTION[fieldName]
  if (!sectionHeader) {
    return writeSectionToRecord(content, fieldName, value)
  }
  const existingBody = getSectionBody(content, sectionHeader)
  if (!existingBody || isPlaceholderBody(existingBody)) {
    // 首次写入或仅占位符 → 直接 replace
    return writeSectionToRecord(content, fieldName, value)
  }
  // 已有正文 → 把 delta 追加到原内容末尾（换行分隔），再整段写回
  // 注：writeSectionToRecord 是整段替换逻辑，所以这里要传"原内容 + delta"的合并文本
  const merged = `${existingBody}\n${value.trim()}`
  return writeSectionToRecord(content, fieldName, merged)
}

/**
 * 语音追记模式：将结构化字段写入病历对应章节，返回更新后的内容、计数与受影响章节。
 * 调用方负责将 updated 同步到 store/state。
 *
 * 字段策略详见 applyFieldToRecord 头注释。sections 用于 toast 展示"刚才改到哪几段"，
 * 便于医生快速定位；已去重并保留首次出现顺序。
 */
export function applyVoicePatchToRecord(
  recordContent: string,
  patch: Record<string, unknown>
): { updated: string; count: number; sections: string[] } {
  // 入口预处理：把嵌套 vital_signs 对象合并到 physical_exam_vitals 行字段
  // 续录补"还发烧 / 体重 N 斤"等生命体征值时此步把它们拼成 T:..P:.. 整行
  const normalizedPatch = mergeVitalSignsIntoPatch(patch, recordContent)
  let updated = recordContent
  let count = 0
  const sections: string[] = []
  for (const [fieldName, value] of Object.entries(normalizedPatch)) {
    if (!value || typeof value !== 'string') continue
    if (!canWriteField(fieldName)) continue
    updated = applyFieldToRecord(updated, fieldName, value)
    count++
    const section = fieldToDisplaySection(fieldName)
    if (section && !sections.includes(section)) sections.push(section)
  }
  return { updated, count, sections }
}

/**
 * 语音追记模式外层包装：调用 applyVoicePatchToRecord 并显示 message 提示。
 *
 * toast 文案优先列出具体章节名（如「已插入【主诉】【现病史】」），让医生立刻知道
 * 改到病历哪几段，而不是只看一个"N 个章节"的数字。章节超过 3 段时折叠为"等 N 段"
 * 避免 toast 过长。
 */
export function applyVoiceToRecordWithFeedback(
  recordContent: string,
  patch: Record<string, unknown>,
  setRecordContent: (v: string) => void
): void {
  const { updated, count, sections } = applyVoicePatchToRecord(recordContent, patch)
  if (count > 0) {
    setRecordContent(updated)
    let detail: string
    if (sections.length === 0) {
      detail = `${count} 处`
    } else if (sections.length <= 3) {
      detail = sections.join('')
    } else {
      detail = `${sections.slice(0, 3).join('')} 等 ${sections.length} 段`
    }
    message.success(`语音内容已插入病历：${detail}`)
  } else {
    message.warning('未识别到可写入病历的字段，请检查语音内容')
  }
}
