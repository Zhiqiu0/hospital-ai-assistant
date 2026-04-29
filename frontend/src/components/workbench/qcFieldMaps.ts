/**
 * QC 字段映射常量 + 记录内容写入工具
 * 供 QCIssuePanel、AISuggestionPanel 等共享使用
 */

/** field_name → 病历中的章节标题（用于定位写入位置）
 *
 * 设计原则：
 *   - 每个 field_name 必须有对应条目，否则 writeSectionToRecord 静默跳过写入
 *   - 专项评估各子项独立成章节，避免写一项覆盖其他子项
 *   - content / onset_time 等非章节字段映射为 ''（跳过写入）
 */
export const FIELD_TO_SECTION: Record<string, string> = {
  // ── 通用必填 ──
  chief_complaint: '【主诉】',
  history_present_illness: '【现病史】',
  past_history: '【既往史】',
  allergy_history: '【过敏史】',
  personal_history: '【个人史】',
  physical_exam: '【体格检查】',
  // physical_exam_vitals 不在这里——它是【体格检查】下的子行（"T:..."），
  // 走 FIELD_TO_LINE_PREFIX 行级写入。否则章节级整段替换会冲掉同段的中医四诊行
  // （2026-04-29 用户报告 bug 的根因）。
  auxiliary_exam: '【辅助检查】',
  onset_time: '', // 时间戳字段，不对应独立章节
  content: '', // 全文类问题，不做章节替换

  // ── 诊断 ──
  initial_diagnosis: '【初步诊断】',
  initial_impression: '【初步诊断】',
  western_diagnosis: '【初步诊断】',
  tcm_diagnosis: '【中医诊断】',
  tcm_syndrome_diagnosis: '【中医诊断】',
  tcm_disease_diagnosis: '【中医诊断】',
  admission_diagnosis: '【入院诊断】',

  // ── 住院通用 ──
  marital_history: '【婚育史】',
  menstrual_history: '【月经史】',
  family_history: '【家族史】',

  // ── 中医四诊 ──
  // 注：望/闻/舌/脉 不写在这里——它们是【体格检查】下的子行，由 FIELD_TO_LINE_PREFIX 处理
  treatment_method: '【治则治法】',

  // ── 治疗意见 & 复诊 ──
  treatment_plan: '【处理意见】',
  followup_advice: '【复诊建议】',
  precautions: '【注意事项】',

  // ── 急诊 ──
  observation_notes: '【留观记录】',
  patient_disposition: '【患者去向】',

  // ── 住院元信息 ──
  history_informant: '【病史陈述者】',

  // ── 住院专项评估 ──
  // 注：以下 7 项是【专项评估】下的子行（"· 疼痛评估：..."），由 FIELD_TO_LINE_PREFIX 处理
  // 不在这里映射成独立章节，否则会跟 LLM 一键生成的格式不一致 → 重复章节

  // ── 中文 field_name 别名（LLM 返回中文键时使用）──
  主诉: '【主诉】',
  现病史: '【现病史】',
  既往史: '【既往史】',
  过敏史: '【过敏史】',
  个人史: '【个人史】',
  '个人史/婚育史/月经史/家族史': '【个人史】',
  婚育史: '【婚育史】',
  月经史: '【月经史】',
  家族史: '【家族史】',
  体格检查: '【体格检查】',
  // 舌象/脉象/望诊/闻诊 走 FIELD_TO_LINE_PREFIX，不在这里映射
  治则治法: '【治则治法】',
  处理意见: '【处理意见】',
  治疗意见及措施: '【处理意见】',
  复诊建议: '【复诊建议】',
  随访建议: '【复诊建议】',
  注意事项: '【注意事项】',
  留观记录: '【留观记录】',
  患者去向: '【患者去向】',
  病史陈述者: '【病史陈述者】',
  初步诊断: '【初步诊断】',
  入院诊断: '【入院诊断】',
  诊断: '【入院诊断】',
  辅助检查: '【辅助检查】',
  '辅助检查（入院前）': '【辅助检查（入院前）】',
  专项评估: '【专项评估】',
  // 疼痛/VTE/营养/心理/康复/用药/宗教 走 FIELD_TO_LINE_PREFIX，不在这里映射
}

/**
 * 章节"子行"写入映射：fieldName → { 所在章节, 行前缀 }
 *
 * 设计背景：
 *   LLM 一键生成时，部分字段不是独立章节，而是**章节内的一行**（如【体格检查】下的
 *   "切诊·舌象：xxx"）。如果走 FIELD_TO_SECTION 章节级写入，会在病历末尾另起独立
 *   【舌象】章节，导致重复 + 视觉割裂——这是 04-17 commit 引入的"配置漂移"bug。
 *
 * 此表统一管理所有"章节子行"字段，writeSectionToRecord 入口优先匹配本表，
 * 命中则走行级替换，不在则退化到章节级逻辑（兜底）。
 *
 * 与后端 prompt 契约一致性：
 *   本表行前缀必须跟 backend/app/services/ai/prompts_generation.py 里
 *   OUTPATIENT_GENERATE_PROMPT / ADMISSION_NOTE_PROMPT 一致。
 *   后端 test_prompt_contract.py 会反向断言 prompt 字符串里包含这些前缀。
 */
export const FIELD_TO_LINE_PREFIX: Record<
  string,
  {
    section: string
    prefix: string
    /**
     * 行替换模式：
     *   'value'（默认）：替换前缀后的内容，保留前缀。
     *     例：「望诊：[未填写]」+ value="神清" → 「望诊：神清」
     *   'whole_line'：fix_text 自带前缀，整行替换为 fix_text。
     *     例：「T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg」整行替换。
     *     用于生命体征——它的内容含多个 T:/P:/R:/BP: 标记，无法用单一前缀切分。
     */
    mode?: 'value' | 'whole_line'
  }
> = {
  // ── 生命体征：在【体格检查】下，整行替换 ──
  // 行匹配锚点 "T:"（按 prompt 契约，体格检查段第一行必须以 T: 起头）。
  // mode='whole_line' 把整行换成 fix_text（fix_text 自带 "T:..." 前缀），
  // 避免章节级整段替换冲掉同段的中医四诊行（2026-04-29 治本 fix）。
  physical_exam_vitals: { section: '【体格检查】', prefix: 'T:', mode: 'whole_line' },
  生命体征: { section: '【体格检查】', prefix: 'T:', mode: 'whole_line' },

  // ── 中医四诊：在【体格检查】下 ──
  tcm_inspection: { section: '【体格检查】', prefix: '望诊：' },
  tcm_auscultation: { section: '【体格检查】', prefix: '闻诊：' },
  tongue_coating: { section: '【体格检查】', prefix: '切诊·舌象：' },
  pulse_condition: { section: '【体格检查】', prefix: '切诊·脉象：' },
  望诊: { section: '【体格检查】', prefix: '望诊：' },
  闻诊: { section: '【体格检查】', prefix: '闻诊：' },
  舌象: { section: '【体格检查】', prefix: '切诊·舌象：' },
  脉象: { section: '【体格检查】', prefix: '切诊·脉象：' },

  // ── 住院专项评估 7 项：在【专项评估】下 ──
  pain_assessment: { section: '【专项评估】', prefix: '· 疼痛评估' },
  vte_risk: { section: '【专项评估】', prefix: '· VTE风险' },
  nutrition_assessment: { section: '【专项评估】', prefix: '· 营养风险' },
  psychology_assessment: { section: '【专项评估】', prefix: '· 心理状态' },
  rehabilitation_assessment: { section: '【专项评估】', prefix: '· 康复需求' },
  current_medications: { section: '【专项评估】', prefix: '· 当前用药' },
  religion_belief: { section: '【专项评估】', prefix: '· 宗教信仰' },
  疼痛评估: { section: '【专项评估】', prefix: '· 疼痛评估' },
  VTE风险评估: { section: '【专项评估】', prefix: '· VTE风险' },
  营养评估: { section: '【专项评估】', prefix: '· 营养风险' },
  心理评估: { section: '【专项评估】', prefix: '· 心理状态' },
  康复评估: { section: '【专项评估】', prefix: '· 康复需求' },
  当前用药: { section: '【专项评估】', prefix: '· 当前用药' },
  宗教信仰: { section: '【专项评估】', prefix: '· 宗教信仰' },
}

/** field_name → 问诊 store 中对应的 key */
export const FIELD_TO_INQUIRY_KEY: Record<string, string> = {
  chief_complaint: 'chief_complaint',
  history_present_illness: 'history_present_illness',
  past_history: 'past_history',
  allergy_history: 'allergy_history',
  personal_history: 'personal_history',
  physical_exam: 'physical_exam',
  initial_diagnosis: 'initial_diagnosis',
  initial_impression: 'initial_impression',
  auxiliary_exam: 'auxiliary_exam',
  marital_history: 'marital_history',
  family_history: 'family_history',
  tcm_inspection: 'tcm_inspection',
  tcm_auscultation: 'tcm_auscultation',
  tongue_coating: 'tongue_coating',
  pulse_condition: 'pulse_condition',
  tcm_disease_diagnosis: 'tcm_disease_diagnosis',
  tcm_syndrome_diagnosis: 'tcm_syndrome_diagnosis',
  treatment_method: 'treatment_method',
  treatment_plan: 'treatment_plan',
  western_diagnosis: 'western_diagnosis',
  followup_advice: 'followup_advice',
  precautions: 'precautions',
  admission_diagnosis: 'admission_diagnosis',
  pain_assessment: 'pain_assessment',
  vte_risk: 'vte_risk',
  nutrition_assessment: 'nutrition_assessment',
  psychology_assessment: 'psychology_assessment',
  rehabilitation_assessment: 'rehabilitation_assessment',
  current_medications: 'current_medications',
  religion_belief: 'religion_belief',
  onset_time: 'onset_time',
  主诉: 'chief_complaint',
  现病史: 'history_present_illness',
  既往史: 'past_history',
  过敏史: 'allergy_history',
  个人史: 'personal_history',
  婚育史: 'marital_history',
  月经史: 'menstrual_history',
  家族史: 'family_history',
  体格检查: 'physical_exam',
  初步诊断: 'initial_diagnosis',
  入院诊断: 'admission_diagnosis',
  诊断: 'initial_diagnosis',
  辅助检查: 'auxiliary_exam',
  中医证候诊断: 'tcm_syndrome_diagnosis',
  中医疾病诊断: 'tcm_disease_diagnosis',
  治则治法: 'treatment_method',
  处理意见: 'treatment_plan',
  舌象: 'tongue_coating',
  脉象: 'pulse_condition',
  疼痛评估: 'pain_assessment',
  VTE风险评估: 'vte_risk',
  营养评估: 'nutrition_assessment',
  心理评估: 'psychology_assessment',
  康复评估: 'rehabilitation_assessment',
  当前用药: 'current_medications',
  用药情况: 'current_medications',
  宗教信仰: 'religion_belief',
  起病时间: 'onset_time',
}

/** field_name（英文键）→ 中文显示标签 */
export const FIELD_NAME_LABEL: Record<string, string> = {
  chief_complaint: '主诉',
  history_present_illness: '现病史',
  past_history: '既往史',
  allergy_history: '过敏史',
  personal_history: '个人史',
  physical_exam: '体格检查',
  initial_diagnosis: '初步诊断',
  initial_impression: '初步诊断',
  auxiliary_exam: '辅助检查',
  marital_history: '婚育史',
  family_history: '家族史',
  tcm_inspection: '望诊',
  tcm_auscultation: '闻诊',
  tongue_coating: '舌象',
  pulse_condition: '脉象',
  tcm_disease_diagnosis: '中医疾病诊断',
  tcm_syndrome_diagnosis: '中医证候诊断',
  treatment_method: '治则治法',
  treatment_plan: '处理意见',
  western_diagnosis: '西医诊断',
  followup_advice: '复诊建议',
  precautions: '注意事项',
  admission_diagnosis: '入院诊断',
  // 急诊 + 住院专项评估（补齐，原表缺失）
  observation_notes: '留观记录',
  patient_disposition: '患者去向',
  history_informant: '病史陈述者',
  pain_assessment: '疼痛评估',
  vte_risk: 'VTE风险评估',
  nutrition_assessment: '营养评估',
  psychology_assessment: '心理评估',
  rehabilitation_assessment: '康复评估',
  current_medications: '当前用药',
  religion_belief: '宗教信仰',
  menstrual_history: '月经史',
}

/**
 * 把字符串里的英文冒号统一成中文冒号，便于跨格式匹配。
 *
 * 解决场景：
 *   prompt 模板里写的是 "T:__℃"（英文冒号），但 LLM 实际输出可能是
 *   "T：36.5°C"（中文冒号）或两者混用。前缀匹配时归一化两端，
 *   保证 "T:"、"T："、"T :" 都能命中"T:"前缀。
 */
function normalizeColon(s: string): string {
  return s.replace(/:/g, '：')
}

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

  // 2. 章节不存在 → 兜底追加新章节（取消写入则不动）
  if (sectionIdx === -1) {
    if (!trimmedFix) return content
    const newLine = mode === 'whole_line' ? trimmedFix : linePrefix + trimmedFix
    return content + '\n\n' + sectionHeader + '\n' + newLine
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
 * 将修复文本写入病历对应章节（找到 header 则替换，找不到则追加）
 *
 * 字段分 3 类处理（按优先级）：
 *   1. 命中 FIELD_TO_LINE_PREFIX → 走行级替换（中医四诊、专项评估 7 项）
 *   2. mapped === ''             → **明确跳过**（全文类规则，如 content / onset_time）
 *   3. mapped === undefined      → **fallback 追加**（未映射字段用 fieldName/中文标签当章节名）
 *   4. 其他                      → 正常章节定位（精确匹配 → 模糊匹配 → 末尾追加）
 */
export function writeSectionToRecord(content: string, fieldName: string, fixText: string): string {
  // 优先级 1：行级写入（中医四诊 / 专项评估子项 / 生命体征）
  const lineConfig = FIELD_TO_LINE_PREFIX[fieldName]
  if (lineConfig) {
    return writeLineInSection(
      content,
      lineConfig.section,
      lineConfig.prefix,
      fixText,
      lineConfig.mode || 'value'
    )
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
    // 保留 header + 一个换行，让再次写入能定位到原位置
    const tail = content.slice(end).replace(/^\s+/, '')
    return content.slice(0, headerEnd) + '\n\n' + (tail ? tail : '')
  }

  // 写入：替换已有章节，或在末尾追加新章节
  if (targetIdx === -1) {
    return content + '\n\n' + header + '\n' + fixText
  }
  const start = matches[targetIdx].index
  const end = targetIdx + 1 < matches.length ? matches[targetIdx + 1].index : content.length
  return content.slice(0, start) + header + '\n' + fixText + '\n' + content.slice(end).trimStart()
}
