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
import { supplementableIssues } from '@/components/workbench/qcFieldConstants'
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
    // 补全范围收口（2026-08-22 终验实锤）：只补**法定扣分项**。
    // LLM 质量建议（source=llm）的 field_name 由模型自命名（如"治疗意见及措施"
    // 复合段大项名），补全后行级写入定位不到子行 → 内容落成段首自由文本、
    // 目标行仍是占位符；医保风险/首页交叉提示是提醒不是缺失，也不该被"补内容"。
    const fixableIssues = supplementableIssues(qcIssues)
    if (!fixableIssues.length) {
      message.info('没有可自动补全的法定缺失项（其余为提示类建议，请人工判断）')
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
          qc_issues: fixableIssues,
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
      //
      // 基线取**回来那一刻的实时正文**而不是发起时的快照（2026-08-14 第六轮审计修复）：
      // 补全是一次批量 LLM 调用，往返数秒到十几秒，而正文编辑器在此期间完全可编辑
      // （只有 isFinal 才 readOnly，补全期间无遮罩）。原先用闭包快照 original 作基线
      // 整段覆盖，医生这十几秒里敲的内容被静默丢弃，随后还被 handleQC 和 5 秒自动
      // 保存固化到库里，医生毫无察觉。useRecordGenerate 早已改用 getState() 取实时值，
      // 补全这条路径没跟上。
      const liveContent = useRecordStore.getState().recordContent
      let newContent = liveContent
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
      // 失败时不要把正文回退成发起时的快照——那同样会抹掉医生这段时间的编辑。
      // 补全没写入任何内容，正文保持现状即可。
      message.error('补全失败，请重试')
    } finally {
      setIsSupplementing(false)
    }
  }

  return { isSupplementing, handleSupplement }
}
