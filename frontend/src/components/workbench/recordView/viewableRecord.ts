/**
 * 病历查看弹窗类型与纯函数辅助（components/workbench/recordView/viewableRecord.ts）
 *
 * 2026-06-11 Round 5.5 拆分：从 RecordViewModal.tsx 抽出（纯搬家，不改行为）：
 *   - ViewableRecord：病历详情视图入参契约类型
 *   - toExportPatient / toExportCtx：ViewableRecord → recordExport 入参的字段映射
 *   - pick / calcAgeFromBirth / fmtDateTime / fmtDate：取值与格式化纯函数
 *   - handlePrint：调 utils/recordExport.printRecord，复用同一段首页+样式
 *
 * 单独成 .ts 文件（不含组件）：满足 react-refresh/only-export-components——
 * 组件文件只导出组件，常量/函数放这里共享。
 */
import {
  printRecord,
  type RecordExportSnapshot,
  type RecordExportContext,
  type RecordExportPatient,
} from '@/utils/recordExport'

/**
 * 病历详情视图所需字段。
 * 后端 medical-records 接口联表后字段较多（含医生 / 患者 / 接诊信息），
 * 这里取本组件实际用到的字段集合作为入参契约，其他字段透传不消费。
 */
export interface ViewableRecord {
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

// 把 ViewableRecord 上的 patient_xxx 实时字段提取成 RecordExportPatient
export function toExportPatient(r: ViewableRecord): RecordExportPatient {
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

export function toExportCtx(r: ViewableRecord): RecordExportContext {
  return {
    visit_type: r.visit_type ?? null,
    visit_time: r.visit_time ?? null,
    bed_no: r.bed_no ?? null,
    doctor_name: r.doctor_name ?? null,
    department_name: r.department_name ?? null,
  }
}

export const GENDER_LABEL: Record<string, string> = { male: '男', female: '女', unknown: '未知' }
export const VISIT_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊',
  emergency: '急诊',
  inpatient: '住院',
}

/** 依序取第一个非空值（null/undefined/空串视为缺失） */
export function pick<T>(...vs: (T | null | undefined)[]): T | null {
  return vs.find(v => v !== null && v !== undefined && v !== '') ?? null
}

/** 根据出生日期推算周岁年龄；无效日期或未来日期返回 null */
export function calcAgeFromBirth(birth?: string | null): number | null {
  if (!birth) return null
  const d = new Date(birth)
  if (Number.isNaN(d.getTime())) return null
  const now = new Date()
  let age = now.getFullYear() - d.getFullYear()
  const m = now.getMonth() - d.getMonth()
  if (m < 0 || (m === 0 && now.getDate() < d.getDate())) age--
  return age >= 0 ? age : null
}

/** 格式化日期时间（无效输入原样返回，空值显示 "—"） */
export function fmtDateTime(s?: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN')
}

/** 格式化日期（无效输入原样返回，空值显示 "—"） */
export function fmtDate(s?: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString('zh-CN')
}

/** 打印按钮回调：组装 patient/ctx/snapshot 后调 recordExport.printRecord */
export function handlePrint(record: ViewableRecord, recordTypeLabel: (type: string) => string) {
  const patient = toExportPatient(record)
  const ctx = toExportCtx(record)
  const snapshot = record.patient_snapshot ?? null
  const signedAt = record.submitted_at ? new Date(record.submitted_at).toLocaleString('zh-CN') : ''
  // recordExport.printRecord 走 RECORD_TYPE_LABEL；这里调用方传的 recordTypeLabel
  // 仅用于弹窗顶部标题展示，不影响打印（打印自己查 RECORD_TYPE_LABEL[record_type]）
  void recordTypeLabel
  printRecord(record.content || '', patient, record.record_type, signedAt, snapshot, ctx)
}
