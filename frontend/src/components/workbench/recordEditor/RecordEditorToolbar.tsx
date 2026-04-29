/**
 * 病历编辑器顶部工具栏（components/workbench/recordEditor/RecordEditorToolbar.tsx）
 *
 * 从 RecordEditor.tsx 拆出（Audit Round 4 M6）：原文件 341 行，工具栏占 ~160 行。
 * 字段众多（病历类型选择、生成/润色/质控/补全/出具/导出 5 个核心按钮 + 已签发标签），
 * 每个按钮都依赖外部 hook 状态——抽出来后 props 较多但语义清晰，主组件只剩"组合"职责。
 */
import { Button, Modal, Select, Space, Tag, Typography } from 'antd'
import {
  EditOutlined,
  FileDoneOutlined,
  FileWordOutlined,
  MedicineBoxOutlined,
  SafetyOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { exportWordDoc } from '@/utils/recordExport'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'

const { Text } = Typography

/** 门诊病历选项（门诊端 / 急诊端共用——急诊会在生成时按 visit_type_detail 自动切到急诊 prompt） */
const OUTPATIENT_RECORD_OPTIONS = [{ value: 'outpatient', label: '门诊病历' }]

/** 住院病历选项（仅住院端可见） */
const INPATIENT_RECORD_OPTIONS = [
  { value: 'admission_note', label: '入院记录' },
  { value: 'first_course_record', label: '首次病程' },
  { value: 'course_record', label: '日常病程' },
  { value: 'senior_round', label: '上级查房' },
  { value: 'pre_op_summary', label: '术前小结' },
  { value: 'op_record', label: '手术记录' },
  { value: 'post_op_record', label: '术后病程' },
  { value: 'discharge_record', label: '出院记录' },
]

interface QCBadge {
  grade_score?: number | null
}

interface RecordEditorToolbarProps {
  recordContent: string
  recordType: string
  setRecordType: (value: string) => void
  isFinal: boolean
  finalizedAt: string | null
  isBusy: boolean
  isGenerating: boolean
  isPolishing: boolean
  isQCing: boolean
  isQCStale: boolean
  isSupplementing: boolean
  qcIssues: unknown[]
  qcPass: boolean | null
  gradeScore: QCBadge | null
  currentPatient: any
  handleGenerate: () => void
  handlePolish: () => void
  handleQC: () => void
  handleSupplement: () => void
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

  // 按当前接诊的 visit_type 决定下拉框该出哪些病历类型——
  // 门诊 / 急诊医生只看到"门诊病历"；住院端只看到 8 项住院病历类型。
  // 之前模块级常量把所有类型都暴露，门诊医生能选"入院记录"是设计 bug。
  const visitType = useActiveEncounterStore(s => s.visitType)
  const recordTypeOptions =
    visitType === 'inpatient' ? INPATIENT_RECORD_OPTIONS : OUTPATIENT_RECORD_OPTIONS

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
      <Space size={8} style={{ flexShrink: 0 }}>
        <Text
          style={{
            fontSize: 13,
            fontWeight: 700,
            color: 'var(--text-1)',
            letterSpacing: '-0.2px',
          }}
        >
          病历草稿
        </Text>
        {isFinal && finalizedAt && (
          <Tag color="success" style={{ margin: 0 }}>
            已签发 · {finalizedAt}
          </Tag>
        )}
        {/*
         * 门诊端只有一种病历类型（中医门诊；急诊由 visit_type_detail 自动切，
         * 不暴露给下拉），没必要给"假下拉"——退化成静态 Tag。
         * 住院端 8 种类型才需要真下拉切换。
         */}
        {visitType === 'inpatient' ? (
          <Select
            value={recordType}
            onChange={setRecordType}
            size="small"
            style={{ width: 120 }}
            options={recordTypeOptions}
          />
        ) : (
          <Tag style={{ margin: 0, fontSize: 12 }}>门诊病历</Tag>
        )}
      </Space>

      <Space size={4}>
        <Button
          icon={<ThunderboltOutlined />}
          type="primary"
          size="small"
          loading={isGenerating}
          onClick={handleGenerate}
          disabled={isFinal || !!recordContent.trim() || isBusy}
          style={{
            borderRadius: 8,
            fontWeight: 600,
            fontSize: 13,
            height: 30,
            paddingInline: 14,
            ...(isFinal || recordContent.trim()
              ? {}
              : {
                  background: 'linear-gradient(135deg, #1d4ed8, #3b82f6)',
                  border: 'none',
                  boxShadow: '0 2px 8px rgba(37,99,235,0.35)',
                }),
          }}
        >
          一键生成
        </Button>

        <Button
          icon={<EditOutlined />}
          size="small"
          loading={isPolishing}
          onClick={handlePolish}
          disabled={isFinal || !recordContent.trim() || isBusy}
          style={{ borderRadius: 8, fontSize: 12, height: 30 }}
        >
          润色
        </Button>

        <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 2px' }} />

        <Button
          icon={<SafetyOutlined />}
          size="small"
          loading={isQCing}
          onClick={() => handleQC()}
          disabled={isFinal || isBusy}
          style={{
            borderRadius: 8,
            fontSize: 12,
            height: 30,
            // 病历改动后变为橙色提示重新质控
            ...(isFinal
              ? {}
              : isQCStale
                ? { color: '#d97706', borderColor: '#fcd34d', background: '#fffbeb' }
                : { color: '#dc2626', borderColor: '#fca5a5', background: '#fff5f5' }),
          }}
        >
          {isQCStale ? '重新质控' : 'AI质控'}
        </Button>

        {qcIssues.length > 0 && !isFinal && (
          <Button
            icon={<MedicineBoxOutlined />}
            size="small"
            loading={isSupplementing}
            disabled={isBusy}
            onClick={handleSupplement}
            style={{
              borderRadius: 8,
              fontSize: 12,
              height: 30,
              color: '#92400e',
              borderColor: '#fcd34d',
              background: '#fffbeb',
            }}
          >
            补全缺失项
          </Button>
        )}

        <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 2px' }} />

        <Button
          icon={qcPass === false ? <StopOutlined /> : <FileDoneOutlined />}
          size="small"
          disabled={!recordContent.trim() || isBusy}
          onClick={() => {
            if (qcPass === false) {
              Modal.warning({
                title: `结构检查未通过，无法提交${gradeScore?.grade_score != null ? `（当前 ${gradeScore.grade_score} 分）` : ''}`,
                content:
                  '请修复右侧质控提示中标注「必须修复」的所有结构性问题后重新质控，通过后方可出具正式病历。',
                okText: '知道了，去修改',
                width: 460,
              })
              return
            }
            setFinalModalOpen(true)
          }}
          style={{
            borderRadius: 8,
            fontSize: 12,
            height: 30,
            color: qcPass === false ? '#dc2626' : '#065f46',
            borderColor: qcPass === false ? '#fca5a5' : '#6ee7b7',
            background: qcPass === false ? '#fff5f5' : '#f0fdf4',
          }}
        >
          {qcPass === false
            ? `结构未通过${gradeScore ? `(${gradeScore.grade_score}分)` : ''}`
            : '出具最终病历'}
        </Button>

        <Button
          icon={<FileWordOutlined />}
          size="small"
          disabled={!recordContent.trim() || isBusy}
          onClick={() => exportWordDoc(recordContent, currentPatient, recordType, finalizedAt)}
          style={{ borderRadius: 8, fontSize: 12, height: 30 }}
        >
          导出 Word
        </Button>
      </Space>
    </div>
  )
}
