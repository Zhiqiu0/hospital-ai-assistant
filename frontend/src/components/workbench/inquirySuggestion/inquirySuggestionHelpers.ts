/**
 * 问诊建议纯逻辑辅助（inquirySuggestion/inquirySuggestionHelpers.ts）
 * 从 InquirySuggestionTab 抽出：拉取追问建议 + 「追问补充」章节组装/回写。
 * 均为无副作用纯函数（fetchInquirySuggestions 仅发请求，不碰组件状态）。
 */
import { InquirySuggestion as Suggestion } from '@/store/types'
import api from '@/services/api'
import { writeSectionToRecord } from '../qcFieldMaps'

/**
 * 后端 /ai/inquiry-suggestions 返回的单条建议形状：
 * 字段与 Suggestion 一致但缺 id / selectedOptions（前端补齐）。
 */
interface RawInquirySuggestion {
  text: string
  priority: 'high' | 'medium' | 'low'
  is_red_flag: boolean
  category: string
  options?: string[]
}

export async function fetchInquirySuggestions(
  chiefComplaint: string,
  history: string,
  initialImpression: string,
  encounterId?: string | null
): Promise<Suggestion[]> {
  const data = (await api.post('/ai/inquiry-suggestions', {
    chief_complaint: chiefComplaint,
    history_present_illness: history,
    initial_impression: initialImpression,
    encounter_id: encounterId || undefined,
  })) as { suggestions?: RawInquirySuggestion[]; degraded?: boolean }
  // degraded=true 表示后端 AI 调用失败兜底返回空，不是"真的没有建议"——
  // 抛错让调用方走失败提示，避免医生误以为已无可追问（2026-06-11）
  if (data.degraded) {
    throw new Error('AI 服务暂时不可用，请稍后重试')
  }
  return (data.suggestions || []).map((s, idx) => ({
    ...s,
    id: `${Date.now()}-${idx}`,
    options: s.options || [],
    selectedOptions: [],
  }))
}

export function buildSupplementSection(items: Suggestion[]): string {
  const lines = items
    .filter(s => s.selectedOptions.length > 0)
    .map(s => `${s.text.replace(/[？?]$/, '')}：${s.selectedOptions.join('、')}`)
  if (!lines.length) return ''
  return '【追问补充】\n' + lines.join('\n')
}

export function updateRecordWithSupplement(content: string, newSection: string): string {
  const marker = '【追问补充】'
  const idx = content.indexOf(marker)
  if (newSection === '') return idx === -1 ? content : content.slice(0, idx).trimEnd()
  if (idx === -1) return content ? content.trimEnd() + '\n\n' + newSection : newSection
  return content.slice(0, idx).trimEnd() + '\n\n' + newSection
}

/**
 * 把诊断建议写入（value 非空）或撤回（value 为空）病历正文。
 *
 * 正文已有「西医诊断：」子行（门急诊【诊断】、住院【入院诊断】的规范格式）时只改这一行。
 * 此前还会先按「初步诊断」做一次章节级写入，结果在同一章节里多出一行不带类别的同名诊断
 * （2026-11-27 联调实测）：签发核对列表出现两条相同诊断，回写给 HIS 的也是重复的两条。
 * 没有该子行的旧格式/手写正文才退回章节级写入。
 */
export function applyDiagnosisToRecord(content: string, value: string): string {
  if (!content.includes('西医诊断：')) {
    return writeSectionToRecord(content, 'initial_impression', value)
  }
  // 用函数形式替换：诊断名里的 $ 等字符不会被当成替换占位符
  const line = value ? `西医诊断：${value}` : '西医诊断：[未填写，需补充]'
  return content.replace(/西医诊断：[^\n]*/g, () => line)
}
