/**
 * 问诊/病历工具函数（utils/inquiryUtils.ts）
 *
 * 提取自 useInquiryPanel 和 useInpatientInquiryPanel 的共享纯函数，
 * 两个 hook 都依赖这里，避免重复维护。
 */
import { message } from 'antd'
import { writeSectionToRecord, FIELD_TO_SECTION } from '@/components/workbench/qcFieldMaps'

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
