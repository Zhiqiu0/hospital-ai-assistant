/**
 * 诊断条目 → 文本投影（domain/medical/diagnosisProjection.ts，2026-08-21 阶段1b）
 *
 * 与后端 diagnosis_service.render_diagnosis_projection 逐字对齐（对拍用例表：
 * shared/contracts/diagnosis_projection_cases.json，两端测试读同一份文件）。
 * 后端投影是权威（PUT 后写库）；前端这份用于保存前的本地即时回填——医生点
 * 保存的瞬间表单/病历同步区就能看到最新文本，不必等一次网络往返。
 */
import { mergeTcmDiagnosis, splitTcmDiagnosis } from './tcmDiagnosis'
import type { DiagnosisEntry } from '@/store/diagnosisEntriesStore'

export interface DiagnosisProjection {
  western_diagnosis: string
  tcm_disease_diagnosis: string
  tcm_syndrome_diagnosis: string
  admission_diagnosis: string
}

/** 条目列表 → 旧文本字段投影（西医多条编号串接、主诊断首位；住院合成行） */
export function renderDiagnosisProjection(entries: DiagnosisEntry[]): DiagnosisProjection {
  const western = entries
    .filter(e => e.category === 'western')
    .sort((a, b) => Number(b.is_primary) - Number(a.is_primary) || a.sort_order - b.sort_order)
  const tcmD = entries.find(e => e.category === 'tcm_disease')
  const tcmS = entries.find(e => e.category === 'tcm_syndrome')

  let westernText = ''
  if (western.length > 1) {
    westernText = western.map((e, i) => `${i + 1}.${e.name}`).join('；')
  } else if (western.length === 1) {
    westernText = western[0].name
  }

  const admissionParts: string[] = []
  if (tcmD || tcmS) {
    admissionParts.push(`中医诊断：${mergeTcmDiagnosis(tcmD?.name || '', tcmS?.name || '')}`)
  }
  if (westernText) admissionParts.push(`西医诊断：${westernText}`)

  return {
    western_diagnosis: westernText,
    tcm_disease_diagnosis: tcmD?.name || '',
    tcm_syndrome_diagnosis: tcmS?.name || '',
    admission_diagnosis: admissionParts.join('\n'),
  }
}

/**
 * 住院入院诊断文本 → 表单三字段（初始化桥的反向解析，2026-08-21 阶段1b）。
 * 解析投影合成行格式（"中医诊断：X — Y" / "西医诊断：..."），兼容医生手写
 * 的无前缀文本（整段归西医）。仅在条目为空时用于初始化，绝不覆盖已有条目。
 */
export function parseAdmissionDiagnosisText(text: string): {
  western: string
  tcmDisease: string
  tcmSyndrome: string
} {
  const out = { western: '', tcmDisease: '', tcmSyndrome: '' }
  const plain: string[] = []
  for (const raw of (text || '').split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const tcm = line.match(/^中医诊断[：:]\s*(.*)$/u)
    if (tcm) {
      const { disease, syndrome } = splitTcmDiagnosis(tcm[1])
      out.tcmDisease = disease
      out.tcmSyndrome = syndrome
      continue
    }
    const western = line.match(/^西医诊断[：:]\s*(.*)$/u)
    if (western) {
      out.western = western[1].trim()
      continue
    }
    plain.push(line)
  }
  // 无前缀行（医生手写编号清单等）归西医——与病案首页"主要/其他诊断"语义一致
  if (!out.western && plain.length > 0) out.western = plain.join('；')
  return out
}

/**
 * 保存前合成完整条目列表：西医条目（store）+ 中医病/证（表单文本各至多一条）。
 * 文本→条目的"初始化桥"也在这里：西医条目为空而表单西医文本非空时
 * （AI 生成回填 / 复诊带入 / 旧数据），整段作一条——医生可在编辑器里再拆分。
 */
export function composeDiagnosisItems(
  westernEntries: DiagnosisEntry[],
  formTexts: { western?: string; tcmDisease?: string; tcmSyndrome?: string }
): DiagnosisEntry[] {
  let western = westernEntries.filter(e => e.name.trim())
  const westernText = (formTexts.western || '').trim()
  if (western.length === 0 && westernText) {
    western = [{ category: 'western', name: westernText, is_primary: false, sort_order: 0 }]
  }
  const items: DiagnosisEntry[] = [...western]
  const tcmD = (formTexts.tcmDisease || '').trim()
  const tcmS = (formTexts.tcmSyndrome || '').trim()
  if (tcmD) items.push({ category: 'tcm_disease', name: tcmD, is_primary: false, sort_order: 0 })
  if (tcmS) items.push({ category: 'tcm_syndrome', name: tcmS, is_primary: false, sort_order: 0 })
  // 主诊断兜底与后端一致（西医优先）；后端也会再校验一遍，这里补齐是为了
  // 本地投影/展示即时正确
  if (items.length > 0 && !items.some(i => i.is_primary)) {
    const fallback = items.find(i => i.category === 'western') || items[0]
    fallback.is_primary = true
  }
  return items
}
