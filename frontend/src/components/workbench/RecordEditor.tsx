/**
 * 病历编辑器组件（components/workbench/RecordEditor.tsx）
 *
 * 业务逻辑：hooks/useRecordEditor.ts（生成 / 润色 / 质控 / 补全 / 出具签发）
 * 子组件：recordEditor/RecordEditorToolbar.tsx（顶部工具栏）
 *         recordEditor/RecordEditorStatusBar.tsx（busy / final / draft 三态状态条）
 *
 * 本主文件只负责组合：状态从 hook 取出 → 透传给两个子组件 + 渲染 TextArea + 出具签发 Modal。
 */
import { useEffect, useRef } from 'react'
import { Input, Modal } from 'antd'
import type { TextAreaRef } from 'antd/es/input/TextArea'
import FinalRecordModal from './FinalRecordModal'
import PreviousRecordPanel from './PreviousRecordPanel'
import AiWritePanel, { AI_WRITE_JUMP_EVENT, type AiWriteJumpDetail } from './AiWritePanel'
import RecordEditorToolbar from './recordEditor/RecordEditorToolbar'
import RecordEditorStatusBar from './recordEditor/RecordEditorStatusBar'
import { locateFieldInRecord } from './qcFieldMaps'
import { useRecordEditor } from '@/hooks/useRecordEditor'
import { useAutoSaveDraft } from '@/hooks/useAutoSaveDraft'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useAiWrittenFieldsStore } from '@/store/aiWrittenFieldsStore'

const { TextArea } = Input

export default function RecordEditor() {
  const previousRecordContent = useActiveEncounterStore(s => s.previousRecordContent)
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const {
    recordContent,
    setRecordContent,
    recordType,
    setRecordType,
    isGenerating,
    isPolishing,
    isQCing,
    isQCStale,
    isFinal,
    finalizedAt,
    qcIssues,
    qcPass,
    gradeScore,
    currentPatient,
    finalModalOpen,
    setFinalModalOpen,
    isSupplementing,
    isBusy,
    busyText,
    handleGenerate,
    handlePolish,
    handleQC,
    handleSupplement,
  } = useRecordEditor()

  // 5 秒防抖 auto-save——医生输入到一半浏览器崩溃 / 网络中断 / logout 都不丢
  // 失败自动入 IndexedDB 队列，下次成功时补发；多设备冲突走乐观锁返 409 提示
  useAutoSaveDraft({
    encounterId: currentEncounterId,
    recordType,
    recordContent,
    isFinal,
  })

  // ── AI 写入字段池：跳转 + 点击/编辑触发 removeField ──────────────
  // 治本路线（2026-05-24）：逐条修复 / 批量补全写入病历后，把字段名加进
  // useAiWrittenFieldsStore，顶部 AiWritePanel 显示 chip。
  // 消失条件三选一：点 chip → 跳转后医生点该行触发 removeField（光标落入）；
  // 编辑该行 → onChange diff 出涉及行字段 → removeField；签发完成 → clear。
  const textareaRef = useRef<TextAreaRef>(null)
  // 上一次的 recordContent，用来在 onChange 时 diff 出修改的字符 index，
  // 反查涉及的字段名移除。用 ref 是为了在 onChange 闭包里拿到最新前值
  // 而不触发组件 re-render。
  const prevContentRef = useRef(recordContent)
  useEffect(() => {
    prevContentRef.current = recordContent
  }, [recordContent])

  // 监听 AiWritePanel 派发的 jump 事件：定位 + setSelectionRange + focus
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<AiWriteJumpDetail>).detail
      if (!detail?.fieldName) return
      const loc = locateFieldInRecord(prevContentRef.current, detail.fieldName)
      if (!loc) return
      const ta = textareaRef.current?.resizableTextArea?.textArea
      if (!ta) return
      ta.focus()
      ta.setSelectionRange(loc.start, loc.end)
      // setSelectionRange 不一定自动滚动到可视区——手动滚一下
      // （计算 selectionStart 行号 × lineHeight 太脆弱，简单粗暴 scrollIntoView）
      try {
        const lineHeight = parseFloat(getComputedStyle(ta).lineHeight) || 28
        const linesBefore = prevContentRef.current.slice(0, loc.start).split('\n').length - 1
        ta.scrollTop = Math.max(0, linesBefore * lineHeight - ta.clientHeight / 2)
      } catch {
        // 滚动失败不影响功能，忽略
      }
    }
    window.addEventListener(AI_WRITE_JUMP_EVENT, handler)
    return () => window.removeEventListener(AI_WRITE_JUMP_EVENT, handler)
  }, [])

  // 计算光标当前所在行覆盖了哪些 AI 写入字段（用于 onClick 时清除高亮）
  const removeFieldsAtCursor = (cursorPos: number) => {
    const fields = useAiWrittenFieldsStore.getState().fields
    if (fields.length === 0) return
    const content = prevContentRef.current
    // 计算光标所在行起止
    const lineStart = content.lastIndexOf('\n', cursorPos - 1) + 1
    const lineEndIdx = content.indexOf('\n', cursorPos)
    const lineEnd = lineEndIdx === -1 ? content.length : lineEndIdx
    // 哪些 field 的定位落在该行区间内 → remove
    for (const field of fields) {
      const loc = locateFieldInRecord(content, field)
      if (loc && loc.start >= lineStart && loc.start <= lineEnd) {
        useAiWrittenFieldsStore.getState().removeField(field)
      }
    }
  }

  // 签发前拦截：如果还有 AI 写入未确认的字段，弹 confirm 让医生明确确认
  // 治本路线（2026-05-24）：合规要求"AI 编造内容签发前必须医生确认"，
  // 把"看到了高亮 chip"升级到"明确签字确认"这一步。
  const handleOpenFinalModal = (open: boolean) => {
    if (!open) {
      setFinalModalOpen(false)
      return
    }
    const fields = useAiWrittenFieldsStore.getState().fields
    if (fields.length === 0) {
      setFinalModalOpen(true)
      return
    }
    Modal.confirm({
      title: `还有 ${fields.length} 处 AI 补全未确认`,
      content: (
        <div>
          <div style={{ marginBottom: 8 }}>以下字段是本次 AI 补全写入，医生尚未点击或修改：</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
            {fields.map(f => (
              <span
                key={f}
                style={{
                  padding: '2px 8px',
                  background: '#fffbe6',
                  border: '1px solid #ffd666',
                  borderRadius: 10,
                  fontSize: 12,
                  color: '#874d00',
                }}
              >
                {f}
              </span>
            ))}
          </div>
          <div style={{ color: '#874d00', fontSize: 12 }}>
            请确认这些内容已审核无误。点"一并接受并签发"将清空提示并继续签发流程。
          </div>
        </div>
      ),
      okText: '一并接受并签发',
      cancelText: '我再看看',
      width: 480,
      onOk: () => {
        useAiWrittenFieldsStore.getState().clear()
        setFinalModalOpen(true)
      },
    })
  }

  // 编辑触发：diff 出哪些字段所在行被改了 → remove
  const handleContentChange = (next: string) => {
    const fields = useAiWrittenFieldsStore.getState().fields
    if (fields.length > 0) {
      const prev = prevContentRef.current
      for (const field of fields) {
        const oldLoc = locateFieldInRecord(prev, field)
        const newLoc = locateFieldInRecord(next, field)
        // 老位置那一行在新内容里如果对应内容不一样 → 该字段被改了
        if (oldLoc) {
          const oldLine = prev.slice(
            prev.lastIndexOf('\n', oldLoc.start - 1) + 1,
            prev.indexOf('\n', oldLoc.start) === -1 ? prev.length : prev.indexOf('\n', oldLoc.start)
          )
          // 如果新位置找不到 → 字段行被删 → 清掉
          if (!newLoc) {
            useAiWrittenFieldsStore.getState().removeField(field)
            continue
          }
          const newLine = next.slice(
            next.lastIndexOf('\n', newLoc.start - 1) + 1,
            next.indexOf('\n', newLoc.start) === -1 ? next.length : next.indexOf('\n', newLoc.start)
          )
          if (oldLine !== newLine) {
            useAiWrittenFieldsStore.getState().removeField(field)
          }
        }
      }
    }
    setRecordContent(next)
  }

  return (
    <div
      style={{
        height: '100%',
        background: 'var(--surface)',
        borderRadius: 12,
        border: '1px solid var(--border)',
        boxShadow: 'var(--shadow-sm)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <RecordEditorToolbar
        recordContent={recordContent}
        recordType={recordType}
        setRecordType={setRecordType}
        isFinal={isFinal}
        finalizedAt={finalizedAt}
        isBusy={isBusy}
        isGenerating={isGenerating}
        isPolishing={isPolishing}
        isQCing={isQCing}
        isQCStale={isQCStale}
        isSupplementing={isSupplementing}
        qcIssues={qcIssues}
        qcPass={qcPass}
        gradeScore={gradeScore}
        currentPatient={currentPatient}
        handleGenerate={handleGenerate}
        handlePolish={handlePolish}
        handleQC={handleQC}
        handleSupplement={handleSupplement}
        setFinalModalOpen={handleOpenFinalModal}
      />

      <RecordEditorStatusBar
        isBusy={isBusy}
        busyText={busyText}
        isFinal={isFinal}
        finalizedAt={finalizedAt}
        recordContent={recordContent}
        recordType={recordType}
        currentPatient={currentPatient}
      />

      {/* 复诊时展示上次病历参考卡片 */}
      {previousRecordContent && <PreviousRecordPanel content={previousRecordContent} />}

      {/* AI 写入清单面板：fields 非空时显示 chip 列表 + × */}
      <AiWritePanel />

      <TextArea
        ref={textareaRef}
        value={recordContent}
        onChange={e => handleContentChange(e.target.value)}
        onClick={e => removeFieldsAtCursor((e.target as HTMLTextAreaElement).selectionStart || 0)}
        onKeyUp={e => {
          // 方向键移动光标也应该触发"医生看过这行"
          if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) {
            removeFieldsAtCursor((e.target as HTMLTextAreaElement).selectionStart || 0)
          }
        }}
        readOnly={isFinal}
        placeholder="填写左侧问诊信息后，点击「一键生成」自动生成病历草稿，或直接在此输入..."
        style={{
          flex: 1,
          fontSize: 14,
          lineHeight: 2.0,
          resize: 'none',
          border: 'none',
          outline: 'none',
          padding: '12px 16px',
          color: 'var(--text-1)',
          background: isFinal ? 'var(--surface-2)' : 'var(--surface)',
        }}
        variant="borderless"
      />

      <FinalRecordModal open={finalModalOpen} onCancel={() => setFinalModalOpen(false)} />
    </div>
  )
}
