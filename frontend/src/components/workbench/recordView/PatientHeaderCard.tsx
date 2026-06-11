/**
 * 病案首页 inline 渲染卡片（components/workbench/recordView/PatientHeaderCard.tsx）
 *
 * 2026-06-11 Round 5.5 拆分：从 RecordViewModal.tsx 抽出（纯搬家，不改行为）。
 * 2026-05-16 加的合规级"签发时冻结身份信息"展示：打印/导出走
 * buildPatientHeaderHtml；Modal 内是 React 节点。两者都按
 * "snapshot → patient → ctx" 顺序取值。
 * 类型与纯函数辅助见同目录 viewableRecord.ts（组件文件只导出组件，
 * 满足 react-refresh/only-export-components）。
 */
import { Typography, Row, Col } from 'antd'
import {
  type ViewableRecord,
  toExportPatient,
  toExportCtx,
  GENDER_LABEL,
  VISIT_TYPE_LABEL,
  pick,
  calcAgeFromBirth,
  fmtDateTime,
  fmtDate,
} from './viewableRecord'

const { Text } = Typography

export default function PatientHeaderCard({ record }: { record: ViewableRecord }) {
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
