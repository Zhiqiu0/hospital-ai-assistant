/**
 * Shared record export utilities: print and Word export.
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

function buildPatientDesc(patient: any): string {
  if (!patient) return '未知患者'
  return [
    patient.name,
    patient.gender === 'male' ? '男' : patient.gender === 'female' ? '女' : '',
    patient.age ? `${patient.age}岁` : '',
  ]
    .filter(Boolean)
    .join(' · ')
}

export function printRecord(
  content: string,
  patient: any,
  recordType: string,
  signedAt: string | null
) {
  const patientDesc = buildPatientDesc(patient)
  const typeLabel = RECORD_TYPE_LABEL[recordType] || recordType
  const formatted = content.replace(/\n/g, '<br>')
  const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>${typeLabel} - ${patientDesc}</title>
<style>
  body { font-family: 'PingFang SC','Microsoft YaHei',sans-serif; margin: 0; padding: 32px 48px; color: #1e293b; }
  h2 { text-align: center; font-size: 20px; margin-bottom: 4px; }
  .meta { text-align: center; font-size: 13px; color: #64748b; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 1px solid #e2e8f0; }
  .content { font-size: 14px; line-height: 2.0; white-space: pre-wrap; }
  .footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8; text-align: right; }
  @media print { body { padding: 20px 32px; } }
</style></head><body>
<h2>${typeLabel}</h2>
<div class="meta">${patientDesc}${signedAt ? `&nbsp;&nbsp;|&nbsp;&nbsp;签发时间：${signedAt}` : ''}</div>
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
  patient: any,
  recordType: string,
  signedAt: string | null
) {
  const patientDesc = buildPatientDesc(patient)
  const typeLabel = RECORD_TYPE_LABEL[recordType] || recordType
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
<style>body{font-family:'宋体',serif;font-size:12pt;line-height:1.8;margin:2cm;}h1{text-align:center;font-size:16pt;}</style>
</head><body>
<h1>${typeLabel}</h1>
<p style="text-align:center;color:#666;margin-bottom:16pt;">${patientDesc}${signedAt ? `　|　签发时间：${signedAt}` : ''}</p>
${paragraphs}
<p style="margin-top:24pt;color:#999;font-size:9pt;text-align:right;">MediScribe 智能病历系统 · 本病历由医生审核签发</p>
</body></html>`
  const blob = new Blob(['\ufeff' + html], { type: 'application/msword;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${typeLabel}_${patient?.name || '未知患者'}.doc`
  a.click()
  URL.revokeObjectURL(url)
}
