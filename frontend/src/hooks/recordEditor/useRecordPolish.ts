/**
 * AI 润色动作（hooks/recordEditor/useRecordPolish.ts）
 *
 * 职责：病历"AI 润色"动作编排——
 *   - 摘出【追问补充】区块保护（不参与 LLM 润色，完成后原样拼回末尾）
 *   - SSE 流式润色 + type=error 事件处理（失败回滚原内容）
 *
 * 拆分来源：2026-06-11 Round 5 从 hooks/useRecordEditor.ts（约 500 行）拆出，
 * 纯搬家不改逻辑。
 */
import { message } from '@/services/messageBridge'
import { useRecordStore } from '@/store/recordStore'
import type { RecordEditorShared } from './useRecordEditorShared'

export function useRecordPolish(shared: RecordEditorShared) {
  const { runSSE, buildRecordTaskPayload } = shared
  const { recordContent, setRecordContent, setPolishing } = useRecordStore()

  const handlePolish = async () => {
    if (!recordContent.trim()) {
      message.warning('病历内容为空，无法润色')
      return
    }
    setPolishing(true)
    const original = recordContent

    // 【追问补充】区块在新架构下仍由前端独立维护——它是医生勾选的"问：答"对
    // 不参与 LLM 润色（防止被合并成自然语言导致勾选数据丢失），润色完原样拼回末尾
    const supplementMarker = '【追问补充】'
    const supplementIdx = original.indexOf(supplementMarker)
    const contentForPolish =
      supplementIdx === -1 ? original : original.slice(0, supplementIdx).trimEnd()
    const supplementSection = supplementIdx === -1 ? '' : original.slice(supplementIdx).trimEnd()

    setRecordContent('')
    let gotError = false
    try {
      await runSSE('/api/v1/ai/quick-polish', buildRecordTaskPayload(contentForPolish), {
        onChunk: text => setRecordContent(useRecordStore.getState().recordContent + text),
        onEvent: (raw: unknown) => {
          // 后端 JSON 路线下任何异常都通过 type=error 事件返回（不再抛 SSE 异常）
          const obj = (raw || {}) as { type?: string; message?: string }
          if (obj.type === 'error') {
            gotError = true
            message.error(`润色失败：${obj.message || '请重试'}`)
          }
        },
      })
      // 后端 renderer 已保证章节唯一，不再需要 restoreMissingSections 守卫
      // 只把保护下来的【追问补充】区块原样拼回末尾即可
      if (gotError) {
        // LLM 失败时不破坏原内容
        setRecordContent(original)
        return
      }
      const polished = useRecordStore.getState().recordContent
      if (supplementSection) {
        setRecordContent(polished.trimEnd() + '\n\n' + supplementSection)
      }
    } catch (e) {
      if ((e as { name?: string })?.name !== 'AbortError') {
        message.error('润色失败，请重试')
        setRecordContent(original)
      }
    } finally {
      setPolishing(false)
    }
  }

  return { handlePolish }
}
