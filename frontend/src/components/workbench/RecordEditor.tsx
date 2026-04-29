/**
 * 病历编辑器组件（components/workbench/RecordEditor.tsx）
 *
 * 业务逻辑：hooks/useRecordEditor.ts（生成 / 润色 / 质控 / 补全 / 出具签发）
 * 子组件：recordEditor/RecordEditorToolbar.tsx（顶部工具栏）
 *         recordEditor/RecordEditorStatusBar.tsx（busy / final / draft 三态状态条）
 *
 * 本主文件只负责组合：状态从 hook 取出 → 透传给两个子组件 + 渲染 TextArea + 出具签发 Modal。
 */
import { Input } from 'antd'
import FinalRecordModal from './FinalRecordModal'
import PreviousRecordPanel from './PreviousRecordPanel'
import RecordEditorToolbar from './recordEditor/RecordEditorToolbar'
import RecordEditorStatusBar from './recordEditor/RecordEditorStatusBar'
import { useRecordEditor } from '@/hooks/useRecordEditor'
import { useAutoSaveDraft } from '@/hooks/useAutoSaveDraft'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'

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
        setFinalModalOpen={setFinalModalOpen}
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

      <TextArea
        value={recordContent}
        onChange={e => setRecordContent(e.target.value)}
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
