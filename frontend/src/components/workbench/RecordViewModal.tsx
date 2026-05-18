/**
 * 病历查看弹窗（components/workbench/RecordViewModal.tsx）
 *
 * 只读模式展示一份完整病历内容，被 HistoryDrawer 和管理页调用：
 *   - 顶部"病案首页"：患者+就诊+医生+科室；优先用 patient_snapshot（签发那一刻
 *     冻结的快照，合规要求），缺失才回落到当前 patient 字段
 *   - 病历正文（pre 标签保留格式）
 *   - "打印"按钮调用 utils/recordExport.printRecord，复用同一段首页+样式，
 *     保证查看/打印/导出三处首页布局完全一致
 *
 * Props:
 *   record: 完整病历对象（含 content 字段与可选 patient_snapshot）
 *   open: 是否显示
 *   onClose: 关闭回调
 *
 * 不提供编辑功能：已签发病历不可修改，
 * 草稿病历应通过续接诊恢复工作台进行编辑。
 *
 * 2026-05-16 加：病案首页（合规级"签发时冻结身份信息"）。原来弹窗只显示
 * 姓名/性别/年龄+正文，医生导出/打印都丢身份信息；现在三个入口共用 buildPatientHeaderHtml
 * 以及 inline 卡片，统一展示完整首页。
 */
import { Modal, Space, Tag, Button, Typography, Row, Col } from 'antd'
import { FileTextOutlined, CheckOutlined, PrinterOutlined } from '@ant-design/icons'
import {
  printRecord,
  type RecordExportSnapshot,
  type RecordExportContext,
  type RecordExportPatient,
} from '@/utils/recordExport'

const { Text } = Typography

/**
 * 病历详情视图所需字段。
 * 后端 medical-records 接口联表后字段较多（含医生 / 患者 / 接诊信息），
 * 这里取本组件实际用到的字段集合作为入参契约，其他字段透传不消费。
 */
interface ViewableRecord {
  id?: string
  record_type: string
  visit_type?: string | null
  status?: string
  content?: string
  submitted_at?: string | null
  patient_name?: string
  patient_gender?: string
  patient_age?: number | null
  doctor_name?: string | null
  submitted_by_name?: string | null
  // ── 病案首页扩展字段（2026-05-16 加）────────────────────────────────
  // 优先用 patient_snapshot（签发时冻结）；为空回落到 patient_xxx 实时字段
  patient_snapshot?: RecordExportSnapshot | null
  patient_no?: string | null
  patient_phone?: string | null
  patient_id_card?: string | null
  patient_address?: string | null
  patient_ethnicity?: string | null
  patient_marital_status?: string | null
  patient_occupation?: string | null
  patient_workplace?: string | null
  patient_contact_name?: string | null
  patient_contact_phone?: string | null
  patient_contact_relation?: string | null
  patient_blood_type?: string | null
  patient_birth_date?: string | null
  visit_time?: string | null
  bed_no?: string | null
  department_name?: string | null
  [key: string]: unknown
}

interface RecordViewModalProps {
  record: ViewableRecord | null
  onClose: () => void
  accentColor: string
  tagColor: string
  recordTypeLabel: (type: string) => string
  showPrint?: boolean
}

// 把 ViewableRecord 上的 patient_xxx 实时字段提取成 RecordExportPatient
function toExportPatient(r: ViewableRecord): RecordExportPatient {
  return {
    name: r.patient_name,
    gender: r.patient_gender,
    age: r.patient_age ?? null,
    patient_no: r.patient_no ?? null,
    birth_date: r.patient_birth_date ?? null,
    id_card: r.patient_id_card ?? null,
    phone: r.patient_phone ?? null,
    address: r.patient_address ?? null,
    ethnicity: r.patient_ethnicity ?? null,
    marital_status: r.patient_marital_status ?? null,
    occupation: r.patient_occupation ?? null,
    workplace: r.patient_workplace ?? null,
    contact_name: r.patient_contact_name ?? null,
    contact_phone: r.patient_contact_phone ?? null,
    contact_relation: r.patient_contact_relation ?? null,
    blood_type: r.patient_blood_type ?? null,
  }
}

function toExportCtx(r: ViewableRecord): RecordExportContext {
  return {
    visit_type: r.visit_type ?? null,
    visit_time: r.visit_time ?? null,
    bed_no: r.bed_no ?? null,
    doctor_name: r.doctor_name ?? null,
    department_name: r.department_name ?? null,
  }
}

const GENDER_LABEL: Record<string, string> = { male: '男', female: '女', unknown: '未知' }
const VISIT_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊',
  emergency: '急诊',
  inpatient: '住院',
}

function pick<T>(...vs: (T | null | undefined)[]): T | null {
  return vs.find(v => v !== null && v !== undefined && v !== '') ?? null
}

function calcAgeFromBirth(birth?: string | null): number | null {
  if (!birth) return null
  const d = new Date(birth)
  if (Number.isNaN(d.getTime())) return null
  const now = new Date()
  let age = now.getFullYear() - d.getFullYear()
  const m = now.getMonth() - d.getMonth()
  if (m < 0 || (m === 0 && now.getDate() < d.getDate())) age--
  return age >= 0 ? age : null
}

function fmtDateTime(s?: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN')
}

function fmtDate(s?: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString('zh-CN')
}

/**
 * 病案首页（inline 渲染版本）。打印/导出走 buildPatientHeaderHtml；
 * Modal 内是 React 节点。两者都按 "snapshot → patient → ctx" 顺序取值。
 */
function PatientHeaderCard({ record }: { record: ViewableRecord }) {
  const s = record.patient_snapshot || {}
  const p = toExportPatient(record)
  const c = toExportCtx(record)

  const name = pick(s.name, p.name) || '—'
  const genderRaw = pick(s.gender, p.gender)
  const gender = genderRaw ? GENDER_LABEL[genderRaw] || genderRaw : '—'
  const birth = pick(s.birth_date, p.birth_date)
  // age 优先用后端返回值（PatientService 计算）；admin/records 没有 age 字段
  // 但有 birth_date，这里 fallback 算一下避免显示 "—"
  const ageVal = p.age ?? calcAgeFromBirth(birth)
  const ageText = ageVal != null ? `${ageVal}岁` : '—'
  const visitTypeRaw = pick(s.visit_type, c.visit_type)
  const visitType = visitTypeRaw ? VISIT_TYPE_LABEL[visitTypeRaw] || visitTypeRaw : '—'

  const items: Array<[string, string]> = [
    ['姓名', name],
    ['性别', gender],
    ['年龄', ageText],
    ['出生日期', fmtDate(birth)],
    ['民族', pick(s.ethnicity, p.ethnicity) || '—'],
    ['血型', pick(s.blood_type, p.blood_type) || '—'],
    ['婚姻', pick(s.marital_status, p.marital_status) || '—'],
    ['职业', pick(s.occupation, p.occupation) || '—'],
    ['身份证号', pick(s.id_card, p.id_card) || '—'],
    ['联系电话', pick(s.phone, p.phone) || '—'],
    ['家庭住址', pick(s.address, p.address) || '—'],
    ['工作单位', pick(s.workplace, p.workplace) || '—'],
    ['紧急联系人', pick(s.contact_name, p.contact_name) || '—'],
    ['联系人电话', pick(s.contact_phone, p.contact_phone) || '—'],
    ['与患者关系', pick(s.contact_relation, p.contact_relation) || '—'],
    ['患者编号', pick(s.patient_no, p.patient_no) || '—'],
    ['就诊类型', visitType],
    ['床位号', pick(s.bed_no, c.bed_no) || '—'],
    ['接诊医生', pick(s.doctor_name, c.doctor_name) || '—'],
    ['所属科室', pick(s.department_name, c.department_name) || '—'],
    ['就诊时间', fmtDateTime(pick(s.visit_time, c.visit_time))],
  ]

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: '10px 14px',
        marginBottom: 10,
        fontSize: 12.5,
      }}
    >
      <div
        style={{
          fontWeight: 600,
          fontSize: 12,
          color: 'var(--text-3)',
          marginBottom: 6,
          letterSpacing: 0.3,
        }}
      >
        病案首页
        {record.patient_snapshot && (
          <Text type="secondary" style={{ fontSize: 11, fontWeight: 400, marginLeft: 6 }}>
            （签发时冻结）
          </Text>
        )}
      </div>
      <Row gutter={[8, 4]}>
        {items.map(([label, value]) => (
          <Col span={12} key={label}>
            <span style={{ color: 'var(--text-3)', marginRight: 6 }}>{label}：</span>
            <span style={{ color: 'var(--text-1)' }}>{value}</span>
          </Col>
        ))}
      </Row>
    </div>
  )
}

function handlePrint(record: ViewableRecord, recordTypeLabel: (type: string) => string) {
  const patient = toExportPatient(record)
  const ctx = toExportCtx(record)
  const snapshot = record.patient_snapshot ?? null
  const signedAt = record.submitted_at ? new Date(record.submitted_at).toLocaleString('zh-CN') : ''
  // recordExport.printRecord 走 RECORD_TYPE_LABEL；这里调用方传的 recordTypeLabel
  // 仅用于弹窗顶部标题展示，不影响打印（打印自己查 RECORD_TYPE_LABEL[record_type]）
  void recordTypeLabel
  printRecord(record.content || '', patient, record.record_type, signedAt, snapshot, ctx)
}

export default function RecordViewModal({
  record,
  onClose,
  accentColor,
  tagColor,
  recordTypeLabel,
  showPrint = false,
}: RecordViewModalProps) {
  return (
    <Modal
      title={
        record && (
          <Space wrap>
            <FileTextOutlined style={{ color: accentColor }} />
            <span style={{ fontWeight: 600 }}>{record.patient_name}</span>
            {record.patient_gender && record.patient_gender !== 'unknown' && (
              <Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>
                {record.patient_gender === 'male' ? '男' : '女'}
              </Text>
            )}
            {record.patient_age != null && (
              <Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>
                {record.patient_age}岁
              </Text>
            )}
            <Tag color={tagColor} style={{ margin: 0 }}>
              {recordTypeLabel(record.record_type)}
            </Tag>
            <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
              {record.submitted_at ? new Date(record.submitted_at).toLocaleString('zh-CN') : ''}
            </Text>
          </Space>
        )
      }
      open={!!record}
      onCancel={onClose}
      footer={
        <Space>
          {showPrint && record && (
            <Button
              icon={<PrinterOutlined />}
              onClick={() => handlePrint(record, recordTypeLabel)}
            >
              打印 / 导出PDF
            </Button>
          )}
          <Button type={showPrint ? 'primary' : 'default'} onClick={onClose}>
            关闭
          </Button>
        </Space>
      }
      width={720}
    >
      {record && <PatientHeaderCard record={record} />}
      <div
        style={{
          background: 'var(--surface-2)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '20px 24px',
          maxHeight: 460,
          overflowY: 'auto',
          fontSize: 14,
          lineHeight: 1.9,
          whiteSpace: 'pre-wrap',
          fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
          color: 'var(--text-1)',
        }}
      >
        {record?.content || '（病历内容为空）'}
      </div>
      {/* 已签发标识 + 责任医生 + 签发时间。
          按《病历书写规范》要求展示责任医生姓名；后端从 list_by_patient 返回。
          submitted_by_name = 实际触发签发的医生（可能与接诊医生不同：管床代签等）；
          doctor_name = 接诊医生（接诊创建者，主要责任人）。一般情况下两者相同。 */}
      <div
        style={{
          marginTop: 12,
          padding: '10px 14px',
          background: '#f0fdf4',
          border: '1px solid #bbf7d0',
          borderRadius: 8,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
          fontSize: 12,
          color: '#166534',
        }}
      >
        <Space size={6}>
          <CheckOutlined style={{ color: '#22c55e' }} />
          <span>已签发病历 · 不可修改</span>
        </Space>
        {record?.doctor_name && (
          <span style={{ color: '#065f46' }}>
            接诊医生：<b>{record.doctor_name}</b>
            {/* 2026-05-03 改：医生侧不再展示 submitted_by_name 差异——
                管理员后台修订病历会让 submitted_by_name 变成 admin，原逻辑会显示
                "（签发：系统管理员）"误导医生认为责任主体不是自己。合规要求的修订
                留痕走 audit_logs 表（管理员后台 + 审计员可查），医生侧只看接诊医生
                即可。如未来真有"管床代签"需求需另起字段（如 first_signed_by）单独
                展示，不复用 submitted_by_name（语义已被修订人占用）。 */}
          </span>
        )}
        {record?.submitted_at && (
          <span style={{ color: '#065f46' }}>
            签发于：{new Date(record.submitted_at).toLocaleString('zh-CN')}
          </span>
        )}
      </div>
    </Modal>
  )
}
