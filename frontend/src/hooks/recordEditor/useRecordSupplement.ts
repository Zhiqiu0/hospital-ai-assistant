/**
 * AI 批量补全动作（hooks/recordEditor/useRecordSupplement.ts）
 *
 * 职责：病历"AI 补全"动作编排——
 *   - 调 /quick-supplement 拿 LLM 一次性返回的 {field_name, value} 列表
 *   - 用 writeSectionToRecord 行级写入（不整段重画，不覆盖医生现场修改）
 *   - 标记 AI 写入字段（aiWrittenFieldsStore）+ 自动重新质控（复用 handleQC）
 *   - isSupplementing 局部 loading 状态也由本 hook 持有
 *
 * 拆分来源：2026-06-11 Round 5 从 hooks/useRecordEditor.ts（约 500 行）拆出，
 * 纯搬家不改逻辑。
 */
import { useState } from 'react'
import { message } from '@/services/messageBridge'
import { useRecordStore } from '@/store/recordStore'
import { useQCStore } from '@/store/qcStore'
import { writeSectionToRecord } from '@/components/workbench/qcFieldMaps'
import { useAiWrittenFieldsStore } from '@/store/aiWrittenFieldsStore'
import type { RecordEditorShared } from './useRecordEditorShared'

export function useRecordSupplement(
  shared: RecordEditorShared,
  /** 补全写入后自动重新质控的入口（由 useRecordQC 提供，门面注入） */
  handleQC: (contentOverride?: string) => Promise<void>
) {
  const { token, buildRecordTaskPayload } = shared
  const { recordContent, setRecordContent } = useRecordStore()
  const { qcIssues } = useQCStore()
  const [isSupplementing, setIsSupplementing] = useState(false)

  const handleSupplement = async () => {
    /**
     * 批量补全（治本路线 2026-05-24）
     *
     * 流程：调 /quick-supplement 拿到 LLM 一次返回的 N 个 {field_name, value}
     *        → 循环用 writeSectionToRecord 行级写入（不是整段重画）
     *        → 把写入的字段名 push 到 aiWrittenFieldsStore（顶部 chip + gutter 高亮）
     *        → 自动重新质控
     *
     * 关键区别于旧实现：
     *   - 不再用 SSE 流式 + renderer 整段重画 → 不会覆盖医生现场修改
     *   - 跟"逐条修复 写入病历"走完全相同的 writeSectionToRecord 写入路径
     *   - LLM 没数据可生成的字段（QC_FIX prompt 鼓励基于上下文推断）也会给值
     */
    if (!qcIssues.length) {
      message.warning('请先执行 AI 质控')
      return
    }
    setIsSupplementing(true)
    const original = recordContent

    try {
      const res = await fetch('/api/v1/ai/quick-supplement', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          ...buildRecordTaskPayload(original),
          qc_issues: qcIssues,
        }),
      })
      if (!res.ok) {
        message.error(`补全失败：HTTP ${res.status}`)
        return
      }
      const data = await res.json()
      if (data.error) {
        message.error(`补全失败：${data.error}`)
        return
      }
      const items: { field_name: string; value: string }[] = data.items || []
      if (items.length === 0) {
        message.warning('AI 未能给出建议，可点击单条「逐条修复」试试')
        return
      }

      // 行级写入 + 标记 AI 写入字段（顺序写入，每次基于上次结果再写下一条）
      let newContent = original
      const writtenFields: string[] = []
      for (const it of items) {
        const before = newContent
        newContent = writeSectionToRecord(newContent, it.field_name, it.value)
        if (newContent !== before) {
          writtenFields.push(it.field_name)
        }
      }
      setRecordContent(newContent)
      useAiWrittenFieldsStore.getState().addFields(writtenFields)

      message.success(`已补全 ${writtenFields.length} 项，正在重新质控...`)
      setIsSupplementing(false)
      await handleQC(newContent)
      return
    } catch (e) {
      const err = e as { name?: string; message?: string }
      if (err?.name === 'AbortError') return
      setRecordContent(original)
      message.error('补全失败，请重试')
    } finally {
      setIsSupplementing(false)
    }
  }

  return { isSupplementing, handleSupplement }
}
