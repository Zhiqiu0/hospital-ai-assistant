/**
 * 病历导出工具（utils/recordExport.ts）
 *
 * 提供两种病历导出方式：
 *   printRecord    : 打开新窗口并自动触发浏览器打印（生成 HTML，含样式）
 *   exportWordDoc  : 生成 Word 兼容的 HTML 文档并触发下载（.doc 格式）
 *
 * 两种格式均包含：
 *   - 病案首页（患者+就诊+医生+科室；优先用签发时冻结的 patient_snapshot，
 *     旧记录无 snapshot 时 fallback 到 patient 实时数据）
 *   - 病历类型标题、签发时间、病历正文（章节标题如【主诉】自动加粗）
 *
 * 注意：exportWordDoc 生成的是 Office XML HTML（非真正 .docx），
 * 但可被 Microsoft Word / WPS 正确识别并打开。
 *
 * 2026-05-16 加：病案首页快照机制。合规要求病历首页（身份信息）在签发那一刻
 * 冻结，不跟随 patient 表后续修改。新签发的病历都会带 patient_snapshot；旧记录
 * 没有时按现有 patient 数据兜底，不会缺信息。
 */

export const RECORD_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊病历',
  admission_note: '入院记录',
  first_course_record: '首次病程记录',
  course_record: '日常病程记录',
  senior_round: '上级查房记录',
  discharge_record: '出院记录',
  pre_op_summary: '术前小结',
  op_record: '手术记录',
  post_op_record: '术后病程记录',
}

/**
 * 病案首页所需患者最小形状（导出/打印场景）。
 * 全部 optional，避免上游 patient 字段缺失导致报错；缺字段在首页上显示为 "—"。
 */
export interface RecordExportPatient {
  name?: string | null
  gender?: string | null
  age?: number | null
  patient_no?: string | null
  birth_date?: string | null
  id_card?: string | null
  phone?: string | null
  address?: string | null
  ethnicity?: string | null
  marital_status?: string | null
  occupation?: string | null
  workplace?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  contact_relation?: string | null
  blood_type?: string | null
}

/**
 * 病案首页快照（与后端 medical_records.patient_snapshot JSONB 字段对齐）。
 * 优先于 RecordExportPatient 使用——首页字段先从这里取，缺失才落到 patient。
 */
export interface RecordExportSnapshot {
  name?: string | null
  gender?: string | null
  birth_date?: string | null
  patient_no?: string | null
  id_card?: string | null
  phone?: string | null
  address?: string | null
  ethnicity?: string | null
  marital_status?: string | null
  occupation?: string | null
  workplace?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  contact_relation?: string | null
  blood_type?: string | null
  visit_type?: string | null
  visit_time?: string | null
  bed_no?: string | null
  doctor_name?: string | null
  department_name?: string | null
}

/** 接诊/医生上下文（不在 patient 表里，由调用方从 encounter/doctor 传入）。 */
export interface RecordExportContext {
  visit_type?: string | null // outpatient/emergency/inpatient
  visit_time?: string | null // ISO datetime 或后端任意时间字符串
  bed_no?: string | null
  doctor_name?: string | null
  department_name?: string | null
}

// ── 内部工具：把后端中英枚举/null 都翻成首页显示文本 ──────────────────────────
const GENDER_LABEL: Record<string, string> = { male: '男', female: '女', unknown: '未知' }
const VISIT_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊',
  emergency: '急诊',
  inpatient: '住院',
}

function pickGender(v?: string | null): string {
  if (!v) return ''
  // 后端 patient.gender 直接存中文 "男/女/未知"；snapshot 也是原样存
  return GENDER_LABEL[v] || v
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
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleString('zh-CN')
}

function fmtDate(s?: string | null): string {
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleDateString('zh-CN')
}

function pickVisitType(v?: string | null): string {
  if (!v) return ''
  return VISIT_TYPE_LABEL[v] || v
}

/**
 * 病案首页拼接（HTML 形式，打印 / Word 公用）。
 *
 * 取值优先级：snapshot → patient → ctx，缺则不渲染该单元格。
 * 渲染样式：两列网格，灰色 label + 黑色 value。打印/导出都用同一段 HTML，
 * 保证查看、打印、导出三处首页一致。
 */
export function buildPatientHeaderHtml(
  patient: RecordExportPatient | null | undefined,
  snapshot: RecordExportSnapshot | null | undefined,
  ctx: RecordExportContext | null | undefined
): string {
  // 工具：snapshot 优先，没有再回落 patient/ctx
  const s = snapshot || {}
  const p = patient || {}
  const c = ctx || {}
  const pick = <T,>(...vs: (T | null | undefined)[]): T | null =>
    vs.find(v => v !== null && v !== undefined && v !== '') ?? null

  const name = pick(s.name, p.name) || '—'
  const gender = pickGender(pick(s.gender, p.gender)) || '—'
  const birth = pick(s.birth_date, p.birth_date)
  const age = p.age ?? calcAgeFromBirth(birth)
  const ageText = age != null ? `${age}岁` : '—'
  const patientNo = pick(s.patient_no, p.patient_no) || '—'
  const idCard = pick(s.id_card, p.id_card) || '—'
  const phone = pick(s.phone, p.phone) || '—'
  const address = pick(s.address, p.address) || '—'
  const ethnicity = pick(s.ethnicity, p.ethnicity) || '—'
  const marital = pick(s.marital_status, p.marital_status) || '—'
  const occupation = pick(s.occupation, p.occupation) || '—'
  const workplace = pick(s.workplace, p.workplace) || '—'
  const contactName = pick(s.contact_name, p.contact_name) || '—'
  const contactPhone = pick(s.contact_phone, p.contact_phone) || '—'
  const contactRelation = pick(s.contact_relation, p.contact_relation) || '—'
  const bloodType = pick(s.blood_type, p.blood_type) || '—'

  const visitType = pickVisitType(pick(s.visit_type, c.visit_type)) || '—'
  const visitTime = fmtDateTime(pick(s.visit_time, c.visit_time)) || '—'
  const bedNo = pick(s.bed_no, c.bed_no) || '—'
  const doctorName = pick(s.doctor_name, c.doctor_name) || '—'
  const deptName = pick(s.department_name, c.department_name) || '—'
  const birthText = fmtDate(birth) || '—'

  // 两列对齐的首页表格——简单 table 兼容 Word/打印渲染最稳
  const row = (a: string, av: string, b: string, bv: string) =>
    `<tr>
      <td class="hk">${a}</td><td class="hv">${av}</td>
      <td class="hk">${b}</td><td class="hv">${bv}</td>
    </tr>`

  return `
<table class="patient-header">
  ${row('姓名', name, '性别', gender)}
  ${row('年龄', ageText, '出生日期', birthText)}
  ${row('民族', ethnicity, '血型', bloodType)}
  ${row('婚姻', marital, '职业', occupation)}
  ${row('身份证号', idCard, '联系电话', phone)}
  ${row('家庭住址', address, '工作单位', workplace)}
  ${row('紧急联系人', contactName, '联系人电话', contactPhone)}
  ${row('与患者关系', contactRelation, '患者编号', patientNo)}
  ${row('就诊类型', visitType, '床位号', bedNo)}
  ${row('接诊医生', doctorName, '所属科室', deptName)}
  ${row('就诊时间', visitTime, '', '')}
</table>`
}

// 首页公用 CSS（打印 + Word 都嵌入）
const HEADER_CSS = `
  .patient-header { width: 100%; border-collapse: collapse; margin: 0 0 18px; font-size: 12pt; }
  .patient-header td { border: 1px solid #cbd5e1; padding: 6px 10px; vertical-align: top; }
  .patient-header .hk { background: #f1f5f9; color: #475569; width: 14%; white-space: nowrap; }
  .patient-header .hv { color: #1e293b; width: 36%; word-break: break-all; }
`

export function printRecord(
  content: string,
  patient: RecordExportPatient | null | undefined,
  recordType: string,
  signedAt: string | null,
  snapshot?: RecordExportSnapshot | null,
  ctx?: RecordExportContext | null
) {
  const typeLabel = RECORD_TYPE_LABEL[recordType] || recordType
  const formatted = content.replace(/\n/g, '<br>')
  const headerHtml = buildPatientHeaderHtml(patient, snapshot, ctx)
  const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>${typeLabel} - ${patient?.name || '未知患者'}</title>
<style>
  body { font-family: 'PingFang SC','Microsoft YaHei',sans-serif; margin: 0; padding: 32px 48px; color: #1e293b; }
  h2 { text-align: center; font-size: 20px; margin-bottom: 12px; }
  .signed { text-align: center; font-size: 12px; color: #64748b; margin-bottom: 16px; }
  .content { font-size: 14px; line-height: 2.0; white-space: pre-wrap; border-top: 1px solid #cbd5e1; padding-top: 14px; }
  .footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid #cbd5e1; font-size: 12px; color: #94a3b8; text-align: right; }
  ${HEADER_CSS}
  @media print { body { padding: 20px 32px; } }
</style></head><body>
<h2>${typeLabel}</h2>
${signedAt ? `<div class="signed">签发时间：${signedAt}</div>` : ''}
${headerHtml}
<div class="content">${formatted}</div>
<div class="footer">MediScribe 智能病历系统 · 本病历由医生审核签发</div>
<script>window.onload = function() { window.print(); }<\/script>
</body></html>`
  const w = window.open('', '_blank')
  if (w) {
    w.document.write(html)
    w.document.close()
  }
}

export function exportWordDoc(
  content: string,
  patient: RecordExportPatient | null | undefined,
  recordType: string,
  signedAt: string | null,
  snapshot?: RecordExportSnapshot | null,
  ctx?: RecordExportContext | null
) {
  const typeLabel = RECORD_TYPE_LABEL[recordType] || recordType
  const headerHtml = buildPatientHeaderHtml(patient, snapshot, ctx)
  const paragraphs = content
    .split('\n')
    .map(line => {
      const isSectionHeader = /^【[^】]+】/.test(line.trim())
      const escaped = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      return isSectionHeader
        ? `<p style="font-weight:bold;margin:12pt 0 4pt;">${escaped}</p>`
        : `<p style="margin:2pt 0;">${escaped || '&nbsp;'}</p>`
    })
    .join('')
  const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="utf-8"><title>${typeLabel}</title>
<style>
  body{font-family:'宋体',serif;font-size:12pt;line-height:1.8;margin:2cm;}
  h1{text-align:center;font-size:16pt;margin-bottom:8pt;}
  .signed{text-align:center;color:#666;font-size:10pt;margin-bottom:12pt;}
  ${HEADER_CSS}
</style>
</head><body>
<h1>${typeLabel}</h1>
${signedAt ? `<p class="signed">签发时间：${signedAt}</p>` : ''}
${headerHtml}
${paragraphs}
<p style="margin-top:24pt;color:#999;font-size:9pt;text-align:right;">MediScribe 智能病历系统 · 本病历由医生审核签发</p>
</body></html>`
  const blob = new Blob(['﻿' + html], { type: 'application/msword;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${typeLabel}_${patient?.name || '未知患者'}.doc`
  a.click()
  URL.revokeObjectURL(url)
}
