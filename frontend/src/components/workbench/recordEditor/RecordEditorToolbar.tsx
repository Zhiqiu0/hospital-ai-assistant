/**
 * 病历编辑器顶部工具栏（components/workbench/recordEditor/RecordEditorToolbar.tsx）
 *
 * 从 RecordEditor.tsx 拆出（Audit Round 4 M6）：原文件 341 行，工具栏占 ~160 行。
 * 字段众多（病历类型选择、生成/润色/质控/补全/出具/导出 5 个核心按钮 + 已签发标签），
 * 每个按钮都依赖外部 hook 状态——抽出来后 props 较多但语义清晰，主组件只剩"组合"职责。
 */
import { App, Button, Select, Space, Tag, Typography } from 'antd'
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
import AutoFillButton from '@/components/embed/AutoFillButton'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useAuthStore } from '@/store/authStore'
import { useEmbedStore } from '@/store/embedStore'
import { useInquiryStore } from '@/store/inquiryStore'
import type { Patient } from '@/domain/medical'

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
  // 用完整 Patient（含病案首页字段），导出 Word 时一并写入顶部首页
  currentPatient: Patient | null
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

  // App.useApp() 拿到的 modal 实例能 consume 主题 context；
  // 不要用 Modal.warning/info/confirm 静态方法（会绕开 ConfigProvider 主题）。
  const { modal } = App.useApp()

  // HIS 嵌入模式状态：决定是否在工具栏渲染"自动填入 HIS"按钮。
  // SaaS 用户 isEmbed=false，按钮完全不渲染，行为零变化。
  const isEmbed = useEmbedStore(s => s.isEmbed)
  const embedEncounterId = useEmbedStore(s => s.session?.encounter_id)
  const inquiry = useInquiryStore(s => s.inquiry)
  // collectFields: AutoFillButton 点击时收集当前问诊 + 病历内容,
  // 打包成 Agent /fill 入参。MVP 阶段:整段 record.content + 关键 intake 字段。
  // 注意:defaultInquiry 数值字段默认是 '' 空字符串(不是 null/undefined),
  // 所以判断要用 nonEmpty(去空格后真有值),不能用 != null 否则空字段全推上去。
  const collectFieldsForFill = () => {
    const fields: Array<{
      section: 'intake' | 'record' | 'diagnosis'
      field_key: string
      value: unknown
    }> = []
    const nonEmpty = (v: unknown): boolean => {
      if (v == null) return false
      const s = String(v).trim()
      return s !== ''
    }
    // intake: 从问诊 store 取生命体征 + 体格检查关键字段
    if (nonEmpty(inquiry.temperature))
      fields.push({ section: 'intake', field_key: 'temperature', value: inquiry.temperature })
    if (nonEmpty(inquiry.pulse))
      fields.push({ section: 'intake', field_key: 'heart_rate', value: inquiry.pulse })
    if (nonEmpty(inquiry.respiration))
      fields.push({ section: 'intake', field_key: 'respiration', value: inquiry.respiration })
    if (nonEmpty(inquiry.bp_systolic) && nonEmpty(inquiry.bp_diastolic)) {
      fields.push({
        section: 'intake',
        field_key: 'blood_pressure',
        value: `${inquiry.bp_systolic}/${inquiry.bp_diastolic}`,
      })
    }
    if (nonEmpty(inquiry.spo2))
      fields.push({ section: 'intake', field_key: 'spo2', value: inquiry.spo2 })
    if (nonEmpty(inquiry.height))
      fields.push({ section: 'intake', field_key: 'height', value: inquiry.height })
    if (nonEmpty(inquiry.weight))
      fields.push({ section: 'intake', field_key: 'weight', value: inquiry.weight })
    // record: 病历主页各 section
    if (nonEmpty(inquiry.chief_complaint))
      fields.push({
        section: 'record',
        field_key: 'chief_complaint',
        value: inquiry.chief_complaint,
      })
    if (nonEmpty(inquiry.history_present_illness))
      fields.push({
        section: 'record',
        field_key: 'history_present_illness',
        value: inquiry.history_present_illness,
      })
    if (nonEmpty(inquiry.past_history))
      fields.push({ section: 'record', field_key: 'past_history', value: inquiry.past_history })
    if (nonEmpty(inquiry.allergy_history))
      fields.push({
        section: 'record',
        field_key: 'allergy_history',
        value: inquiry.allergy_history,
      })
    if (nonEmpty(recordContent))
      fields.push({ section: 'record', field_key: 'full_text', value: recordContent })
    return fields
  }

  // 按当前接诊的 visit_type 决定下拉框该出哪些病历类型——
  // 门诊 / 急诊医生只看到"门诊病历"；住院端只看到 8 项住院病历类型。
  // 之前模块级常量把所有类型都暴露，门诊医生能选"入院记录"是设计 bug。
  const visitType = useActiveEncounterStore(s => s.visitType)
  // 导出 Word 时拼"病案首页"用的接诊上下文：医生姓名/科室来自 authStore，
  // visit_type 来自 activeEncounterStore。编辑器场景没有 snapshot，传 null。
  const user = useAuthStore(s => s.user)
  const exportCtx = {
    visit_type: visitType,
    visit_time: finalizedAt,
    doctor_name: user?.real_name,
    department_name: user?.department_name,
  }
  const recordTypeOptions =
    visitType === 'inpatient' ? INPATIENT_RECORD_OPTIONS : OUTPATIENT_RECORD_OPTIONS
  // 兜底：recordStore 默认 recordType='outpatient'，住院接诊建立时不会自动切换。
  // 如果当前 recordType 不在本场景的可选列表里，Select 会渲染 raw value（"outpatient"
  // 字面量），破坏 UI。这里在渲染层用合法默认值兜底（住院→入院记录，门诊→门诊病历）。
  const effectiveRecordType = recordTypeOptions.some(o => o.value === recordType)
    ? recordType
    : recordTypeOptions[0].value

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
            value={effectiveRecordType}
            onChange={setRecordType}
            size="small"
            style={{ width: 120 }}
            options={recordTypeOptions}
          />
        ) : (
          // 急诊也走这个分支（visitType=outpatient/emergency 都用单一病历类型），
          // 之前硬编码"门诊病历"会在急诊工作台错显——按 visitType 区分。
          <Tag style={{ margin: 0, fontSize: 12 }}>
            {visitType === 'emergency' ? '急诊病历' : '门诊病历'}
          </Tag>
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
              modal.warning({
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
          onClick={() =>
            exportWordDoc(recordContent, currentPatient, recordType, finalizedAt, null, exportCtx)
          }
          style={{ borderRadius: 8, fontSize: 12, height: 30 }}
        >
          导出 Word
        </Button>

        {/*
         * HIS 嵌入模式专属按钮：调本地桌面 Agent 把病历自动填回金算盘 HIS。
         * SaaS 用户 isEmbed=false → 完全不渲染，UI/行为零差异。
         */}
        {isEmbed && embedEncounterId && (
          <AutoFillButton encounterId={embedEncounterId} collectFields={collectFieldsForFill} />
        )}
      </Space>
    </div>
  )
}
