/**
 * 工具栏左侧区：标题 + 已签发徽章 + 病历类型选择
 * （components/workbench/recordEditor/RecordEditorToolbarTypeSelect.tsx）
 *
 * 2026-06-11 Round 5 拆分：从 RecordEditorToolbar.tsx 抽出（原文件 471 行超 300 行规范）。
 * 逻辑原样搬家：按 visitType 决定下拉选项 / 静态 Tag，未做任何改动。
 */
import { Select, Space, Tag, Typography } from 'antd'
import type { VisitType } from '@/domain/medical'

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

interface RecordEditorToolbarTypeSelectProps {
  /** 当前病历类型（recordStore） */
  recordType: string
  /** 切换病历类型回调 */
  setRecordType: (value: string) => void
  /** 病历是否已签发（已签发时显示绿色徽章） */
  isFinal: boolean
  /** 签发时间（与 isFinal 配合渲染徽章文案） */
  finalizedAt: string | null
  /** 当前接诊类型（outpatient/emergency/inpatient），决定下拉选项范围 */
  visitType: VisitType
}

export default function RecordEditorToolbarTypeSelect({
  recordType,
  setRecordType,
  isFinal,
  finalizedAt,
  visitType,
}: RecordEditorToolbarTypeSelectProps) {
  // 按当前接诊的 visit_type 决定下拉框该出哪些病历类型——
  // 门诊 / 急诊医生只看到"门诊病历"；住院端只看到 8 项住院病历类型。
  // 之前模块级常量把所有类型都暴露，门诊医生能选"入院记录"是设计 bug。
  const recordTypeOptions =
    visitType === 'inpatient' ? INPATIENT_RECORD_OPTIONS : OUTPATIENT_RECORD_OPTIONS
  // 兜底：recordStore 默认 recordType='outpatient'，住院接诊建立时不会自动切换。
  // 如果当前 recordType 不在本场景的可选列表里，Select 会渲染 raw value（"outpatient"
  // 字面量），破坏 UI。这里在渲染层用合法默认值兜底（住院→入院记录，门诊→门诊病历）。
  const effectiveRecordType = recordTypeOptions.some(o => o.value === recordType)
    ? recordType
    : recordTypeOptions[0].value

  return (
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
  )
}
