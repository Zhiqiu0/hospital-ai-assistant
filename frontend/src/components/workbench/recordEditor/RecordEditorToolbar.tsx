/**
 * 病历编辑器顶部工具栏（components/workbench/recordEditor/RecordEditorToolbar.tsx）
 *
 * 从 RecordEditor.tsx 拆出（Audit Round 4 M6）：原文件 341 行，工具栏占 ~160 行。
 * 字段众多（病历类型选择、生成/润色/质控/补全/出具/导出 5 个核心按钮 + 已签发标签），
 * 每个按钮都依赖外部 hook 状态——抽出来后 props 较多但语义清晰，主组件只剩"组合"职责。
 *
 * 2026-06-11 Round 5 拆分：原文件 471 行超 300 行规范，按职责拆为同目录 3 个文件——
 *   - RecordEditorToolbarTypeSelect.tsx：左侧标题 + 已签发徽章 + 病历类型选择
 *   - RecordEditorToolbarActions.tsx：右侧动作按钮组（生成/润色/质控/补全/出具/导出）
 * 对外 API（默认导出组件名 + props 接口）完全不变，消费方零改动。
 * （原「HIS 自动填入」控件模式按钮 + collectFillFields.ts 已随 UI 自动化方案退休删除。）
 */
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import RecordEditorToolbarTypeSelect from './RecordEditorToolbarTypeSelect'
import RecordEditorToolbarActions, { type QCBadge } from './RecordEditorToolbarActions'
import type { Patient } from '@/domain/medical'

interface RecordEditorToolbarProps {
  /** 病历正文内容（决定按钮可用态 / 导出与 HIS 填入的数据源） */
  recordContent: string
  /** 当前病历类型（recordStore，导出 Word 时决定文档模板） */
  recordType: string
  /** 切换病历类型回调（住院端下拉切换时触发） */
  setRecordType: (value: string) => void
  /** 病历是否已签发（签发后显示徽章，编辑类按钮禁用） */
  isFinal: boolean
  /** 签发时间（徽章文案 / 导出 Word 写入病案首页） */
  finalizedAt: string | null
  /** 任一 AI 任务进行中（互斥锁，所有按钮统一禁用） */
  isBusy: boolean
  /** 一键生成进行中 */
  isGenerating: boolean
  /** 润色进行中 */
  isPolishing: boolean
  /** AI 质控进行中 */
  isQCing: boolean
  /** 质控结果已过期（病历改动后置 true，质控按钮变橙提示重新质控） */
  isQCStale: boolean
  /** 补全缺失项进行中 */
  isSupplementing: boolean
  /** 质控问题列表（非空且未签发时显示"补全缺失项"按钮） */
  qcIssues: unknown[]
  /** 结构检查是否通过（false 时拦截"出具最终病历"并弹窗提示） */
  qcPass: boolean | null
  /** 质控评分徽章（出具按钮文案 / 拦截弹窗里展示分数） */
  gradeScore: QCBadge | null
  /** 用完整 Patient（含病案首页字段），导出 Word 时一并写入顶部首页 */
  currentPatient: Patient | null
  /** 一键生成回调 */
  handleGenerate: () => void
  /** 润色回调 */
  handlePolish: () => void
  /** AI 质控回调 */
  handleQC: () => void
  /** 补全缺失项回调 */
  handleSupplement: () => void
  /** 打开"出具最终病历"确认弹窗 */
  setFinalModalOpen: (open: boolean) => void
}

export default function RecordEditorToolbar(props: RecordEditorToolbarProps) {
  const {
    recordContent,
    recordType,
    setRecordType,
    isFinal,
    finalizedAt,
    isBusy,
    isGenerating,
    isPolishing,
    isQCing,
    isQCStale,
    isSupplementing,
    qcIssues,
    qcPass,
    gradeScore,
    currentPatient,
    handleGenerate,
    handlePolish,
    handleQC,
    handleSupplement,
    setFinalModalOpen,
  } = props

  // 当前接诊类型：左侧决定病历类型选项范围，右侧导出 Word 拼病案首页时用
  const visitType = useActiveEncounterStore(s => s.visitType)

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 14px',
        borderBottom: '1px solid var(--border-subtle)',
        background: 'var(--surface-2)',
        flexShrink: 0,
        gap: 8,
      }}
    >
      {/* 左侧：标题 + 已签发徽章 + 病历类型选择 */}
      <RecordEditorToolbarTypeSelect
        recordType={recordType}
        setRecordType={setRecordType}
        isFinal={isFinal}
        finalizedAt={finalizedAt}
        visitType={visitType}
      />

      {/* 右侧：生成 / 润色 / 质控 / 补全 / 出具 / 导出 + HIS 自动填入 */}
      <RecordEditorToolbarActions
        recordContent={recordContent}
        recordType={recordType}
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
        visitType={visitType}
        handleGenerate={handleGenerate}
        handlePolish={handlePolish}
        handleQC={handleQC}
        handleSupplement={handleSupplement}
        setFinalModalOpen={setFinalModalOpen}
      />
    </div>
  )
}
