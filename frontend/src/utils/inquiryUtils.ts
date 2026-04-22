/**
 * 问诊/病历工具函数（utils/inquiryUtils.ts）
 *
 * 提取自 useInquiryPanel 和 useInpatientInquiryPanel 的共享纯函数，
 * 两个 hook 都依赖这里，避免重复维护。
 */
import { message } from 'antd'
import { writeSectionToRecord, FIELD_TO_SECTION } from '@/components/workbench/qcFieldMaps'

/**
 * 生命体征文本合并：将新测量值合并或前插到体格检查第一行。
 * 若第一行已是体征行（以 T:/P:/BP: 等开头），则按指标 key 合并；否则前插。
 */
export function mergeVitalText(current: string, vitalText: string): string {
  const lines = current.split('\n')
  const firstLine = lines[0] || ''
  const isVitalLine = /^(T:|P:|R:|BP:|SpO|身高:|体重:)/.test(firstLine)
  let mergedLine: string
  if (isVitalLine) {
    const getKey = (s: string) => s.split(':')[0]
    const existingParts = firstLine.split(/\s{2,}/).filter(Boolean)
    const newParts = vitalText.split(/\s{2,}/).filter(Boolean)
    const result = [...existingParts]
    for (const part of newParts) {
      const key = getKey(part)
      const idx = result.findIndex(p => getKey(p) === key)
      if (idx >= 0) result[idx] = part
      else result.push(part)
    }
    mergedLine = result.join('  ')
  } else {
    mergedLine = vitalText
  }
  return isVitalLine
    ? [mergedLine, ...lines.slice(1)].join('\n')
    : mergedLine + (current ? '\n' + current : '')
}

/**
 * 语音追记模式：将结构化字段写入病历对应章节，返回更新后的内容和写入数量。
 * 调用方负责将 updated 同步到 store/state。
 */
export function applyVoicePatchToRecord(
  recordContent: string,
  patch: Record<string, unknown>
): { updated: string; count: number } {
  let updated = recordContent
  let count = 0
  for (const [fieldName, value] of Object.entries(patch)) {
    if (!value || typeof value !== 'string') continue
    if (FIELD_TO_SECTION[fieldName] === undefined || FIELD_TO_SECTION[fieldName] === '') continue
    updated = writeSectionToRecord(updated, fieldName, value)
    count++
  }
  return { updated, count }
}

/**
 * 语音追记模式外层包装：调用 applyVoicePatchToRecord 并显示 message 提示。
 */
export function applyVoiceToRecordWithFeedback(
  recordContent: string,
  patch: Record<string, unknown>,
  setRecordContent: (v: string) => void
): void {
  const { updated, count } = applyVoicePatchToRecord(recordContent, patch)
  if (count > 0) {
    setRecordContent(updated)
    message.success(`语音内容已插入病历 ${count} 个章节`)
  } else {
    message.warning('未识别到可写入病历的字段，请检查语音内容')
  }
}
