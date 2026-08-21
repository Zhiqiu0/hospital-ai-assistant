/**
 * 中医诊断合并行 拆分/合并 契约（domain/medical/tcmDiagnosis.ts）
 *
 * 2026-08-21 阶段0 收口：此前这套逻辑在前端有两份实现
 * （recordSectionWriter.ts 的 split/merge + inquirySync.ts 的 buildDiagnosisText），
 * 与后端权威实现（_render_common._merge_tcm_diagnosis / qc_engine.parser._split_tcm_diagnosis）
 * 存在三处漂移，全部是会咬人的真 bug：
 *   1. 前端拆分符正则含半角 '-' —— "COVID-19后咳嗽" 会被误切成 疾病"COVID"+证候"19后咳嗽"，后端不切；
 *   2. 前端拆分优先级是 破折号→括号，后端是 括号→破折号 —— "感冒 — 风寒束表证（兼气虚）"两端拆出不同结果；
 *   3. buildDiagnosisText 缺项占位符用"待明确"，而质控只认"[未填写，需补充]"为未填 —— "待明确"会骗过质控。
 *
 * 现在契约收口到本模块（以后端为权威），对拍用例表在
 * shared/contracts/tcm_diagnosis_cases.json —— 前后端测试读同一份文件，
 * 改契约必须两端测试同时过，单方面改动 CI 必红。
 */

/** 缺项占位符——与后端 record_schemas.PLACEHOLDER 逐字一致，禁用其他变体 */
export const TCM_DIAG_PLACEHOLDER = '[未填写，需补充]'

/**
 * 拆分合并行 → { disease, syndrome }。
 * 优先级：尾部括号 → 全角破折号（——/—/–）→ 单值视为疾病。
 * 半角连字符 '-' 绝不作为拆分符（保护 COVID-19 等含连字符诊断名）。
 */
export function splitTcmDiagnosis(merged: string): { disease: string; syndrome: string } {
  const stripTail = (s: string) => s.trim().replace(/[\s。.]+$/u, '')
  const text = stripTail(merged || '')
  if (!text || text === TCM_DIAG_PLACEHOLDER) return { disease: '', syndrome: '' }

  // 1. 尾部括号格式 "X（Y）" / "X(Y)"（与后端一致：括号优先于破折号）
  let m = text.match(/^(.+?)\s*[（(]\s*(.+?)\s*[)）]\s*$/u)
  if (m) {
    return { disease: stripTail(m[1]), syndrome: stripTail(m[2]) }
  }
  // 2. 全角破折号（顺序：双横 → em-dash → en-dash；不含半角 '-'）
  for (const sep of ['——', '—', '–']) {
    const idx = text.indexOf(sep)
    if (idx !== -1) {
      const d = stripTail(text.slice(0, idx))
      const s = stripTail(text.slice(idx + sep.length))
      return {
        disease: d === TCM_DIAG_PLACEHOLDER ? '' : d,
        syndrome: s === TCM_DIAG_PLACEHOLDER ? '' : s,
      }
    }
  }
  // 3. 单值 → 全部视作疾病诊断，证候留空让质控报缺
  return { disease: text, syndrome: '' }
}

/**
 * 合并 { disease, syndrome } → "X — Y" 合并行。
 * 与后端 _merge_tcm_diagnosis 逐字一致：
 *   两项都填 → "X — Y"；仅疾病 → "X"；仅证候 → "[占位符] — Y"；全空 → 占位符。
 */
export function mergeTcmDiagnosis(disease: string, syndrome: string): string {
  const hasD = !!disease && disease !== TCM_DIAG_PLACEHOLDER
  const hasS = !!syndrome && syndrome !== TCM_DIAG_PLACEHOLDER
  if (hasD && hasS) return `${disease} — ${syndrome}`
  if (hasD) return disease
  if (hasS) return `${TCM_DIAG_PLACEHOLDER} — ${syndrome}`
  return TCM_DIAG_PLACEHOLDER
}
