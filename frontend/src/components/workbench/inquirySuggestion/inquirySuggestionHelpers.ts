/**
 * 问诊建议纯逻辑辅助（inquirySuggestion/inquirySuggestionHelpers.ts）
 * 从 InquirySuggestionTab 抽出：拉取追问建议 + 「追问补充」章节组装/回写。
 * 均为无副作用纯函数（fetchInquirySuggestions 仅发请求，不碰组件状态）。
 */
import { InquirySuggestion as Suggestion } from '@/store/types'
import api from '@/services/api'

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
