import { message } from '@/services/messageBridge'
/**
 * 病历导出入口（utils/recordExport.ts）
 *
 * printRecord / exportWordDoc 两个入口函数；类型、标签表与全部格式化
 * 纯函数已拆至 recordExportShared.ts（2026-09-19 两拆，纯机械搬移）。
 * 本文件 re-export 共享层全部公共符号——调用方与既有测试的
 * `from '@/utils/recordExport'` 路径不变。
 */
import {
  HEADER_CSS,
  HOSPITAL_NAME,
  PAGE_CSS,
  RECORD_TYPE_LABEL,
  buildPatientHeaderHtml,
  esc,
  fmtDateTime,
  maskName,
  normalizeEol,
} from './recordExportShared'
import type {
  RecordExportContext,
  RecordExportPatient,
  RecordExportSnapshot,
} from './recordExportShared'

// 兼容层：共享符号原路 re-export
export { HOSPITAL_NAME, RECORD_TYPE_LABEL, buildPatientHeaderHtml } from './recordExportShared'
export type {
  RecordExportContext,
  RecordExportPatient,
  RecordExportSnapshot,
} from './recordExportShared'

export function printRecord(
  content: string,
  patient: RecordExportPatient | null | undefined,
  recordType: string,
  signedAt: string | null,
  snapshot?: RecordExportSnapshot | null,
  ctx?: RecordExportContext | null
) {
  const typeLabel = RECORD_TYPE_LABEL[recordType] || recordType
  // 先转义再换行：正文里的 < > 必须先变成 HTML 实体，否则 <script> 会在
  // document.write 出来的**同源**窗口里执行，直接读走 localStorage 里的登录 token
  // CRLF 先归一（2026-08-31 导出审计）：从 Word/HIS 粘贴来的正文含 \r，
  // 不归一时 \r 残留 + pre-wrap 会让每行之间多出一个空行
  const formatted = normalizeEol(esc(content)).replace(/\n/g, '<br>')
  const headerHtml = buildPatientHeaderHtml(patient, snapshot, ctx)
  const revisionCount = ctx?.revision_count ?? 0
  const revised = revisionCount > 0
  // 补记注明（见 RecordExportContext 里的规范依据）：两个时间都要露出来，
  // 「原记录保持可见」正是规范对补记的要求，只写「补记」二字不够。
  const lateNote =
    ctx?.is_late_entry === true
      ? `本文书为补记：记录时间 ${fmtDateTime(ctx?.recorded_at)}，系统录入时间 ${fmtDateTime(ctx?.entered_at)}`
      : ''
  const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>${esc(typeLabel)} - ${esc(maskName(patient?.name))}</title>
<style>
  /* 字体栈补 SimSun-ExtB：CJK 扩展 B 区生僻字姓名（如𰻝）在宋体/雅黑里缺字 */
  body { font-family: 'PingFang SC','Microsoft YaHei','SimSun-ExtB',sans-serif; margin: 0; padding: 32px 48px; color: #1e293b; }
  h1.hospital { text-align: center; font-size: 17px; font-weight: 700; margin: 0 0 6px; letter-spacing: 2px; }
  h2 { text-align: center; font-size: 20px; margin-bottom: 12px; }
  .revised-note { text-align: center; font-size: 12px; color: #b45309; margin-bottom: 10px; }
  .signed { text-align: center; font-size: 12px; color: #64748b; margin-bottom: 16px; }
  .content { font-size: 14px; line-height: 2.0; white-space: pre-wrap; border-top: 1px solid #cbd5e1; padding-top: 14px; }
  .footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid #cbd5e1; font-size: 12px; color: #94a3b8; text-align: right; }
  /* 未签发草稿标识（2026-08-14 第六轮审计修复）：草稿也能一键导出，而原先
     页脚硬编码"本病历由医生审核签发"——草稿被当成正式病历流出去是合规问题。
     横幅放正文顶部，因为翻内页看不到页脚。 */
  .draft-banner { margin: 8px 0 14px; padding: 8px; border: 2px solid #dc2626; color: #dc2626;
                  font-size: 15px; font-weight: 700; text-align: center; letter-spacing: 2px; }
  .footer.draft { color: #dc2626; font-weight: 600; }
  ${HEADER_CSS}
  ${PAGE_CSS}
  @media print { body { padding: 20px 32px; } }
</style></head><body>
<h1 class="hospital">${esc(HOSPITAL_NAME)}</h1>
<h2>${esc(typeLabel)}</h2>
${revised ? '<div class="revised-note">本文书经修订（共 ' + String(revisionCount) + ' 次），修订留痕见医院审计日志</div>' : ''}
${lateNote ? '<div class="revised-note">' + esc(lateNote) + '</div>' : ''}
${
  signedAt
    ? `<div class="signed">签发时间：${esc(signedAt)}</div>`
    : '<div class="draft-banner">未 签 发 草 稿 · 不作为正式病历</div>'
}
${headerHtml}
<div class="content">${formatted}</div>
${
  signedAt
    ? '<div class="footer">MediScribe 智能病历系统 · 本病历由医生审核签发</div>'
    : '<div class="footer draft">MediScribe 智能病历系统 · 未签发草稿，仅供内部核对，不作为正式病历</div>'
}
<script>window.onload = function() { window.print(); }<\/script>
</body></html>`
  const w = window.open('', '_blank')
  if (w) {
    w.document.write(html)
    w.document.close()
    return true
  }
  // 弹窗被拦截时必须告知（2026-08-31 导出审计）：原先静默失败，而调用方
  // 已经先行上报了"已导出"审计——追责时的时间线是错的
  message.error('打印窗口被浏览器拦截，请允许本站弹窗后重试')
  return false
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
  // 经修订的文书要在纸面注明（同 printRecord，见那里的注释）
  const revisionCount = ctx?.revision_count ?? 0
  const revised = revisionCount > 0
  // 补记注明（见 RecordExportContext 里的规范依据）：两个时间都要露出来，
  // 「原记录保持可见」正是规范对补记的要求，只写「补记」二字不够。
  const lateNote =
    ctx?.is_late_entry === true
      ? `本文书为补记：记录时间 ${fmtDateTime(ctx?.recorded_at)}，系统录入时间 ${fmtDateTime(ctx?.entered_at)}`
      : ''
  const paragraphs = normalizeEol(content)
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
<head><meta charset="utf-8"><title>${esc(typeLabel)}</title>
<style>
  /* 字体栈补英文别名与扩展 B 区（2026-08-31 导出审计）：单写'宋体'在英文版
     Office / WPS 海外版解析失败会回落西文字体渲染中文；SimSun-ExtB 供生僻字姓名 */
  body{font-family:'宋体',SimSun,'Songti SC','SimSun-ExtB',serif;font-size:12pt;line-height:1.8;margin:2cm;}
  h1{text-align:center;font-size:16pt;margin-bottom:8pt;}
  .signed{text-align:center;color:#666;font-size:10pt;margin-bottom:12pt;}
  ${HEADER_CSS}
</style>
</head><body>
<p style="text-align:center;font-size:14pt;font-weight:bold;letter-spacing:2pt;margin:0 0 6pt;">${esc(HOSPITAL_NAME)}</p>
<h1>${esc(typeLabel)}</h1>
${revised ? '<p style="text-align:center;color:#b45309;font-size:10pt;margin-bottom:8pt;">本文书经修订（共 ' + String(revisionCount) + ' 次），修订留痕见医院审计日志</p>' : ''}
${lateNote ? '<p style="text-align:center;color:#b45309;font-size:10pt;margin-bottom:8pt;">' + esc(lateNote) + '</p>' : ''}
${
  signedAt
    ? `<p class="signed">签发时间：${esc(signedAt)}</p>`
    : '<p style="color:#c00;font-size:13pt;font-weight:bold;text-align:center;border:2px solid #c00;padding:6pt;">未 签 发 草 稿 · 不作为正式病历</p>'
}
${headerHtml}
${paragraphs}
${
  signedAt
    ? '<p style="margin-top:24pt;color:#999;font-size:9pt;text-align:right;">MediScribe 智能病历系统 · 本病历由医生审核签发</p>'
    : '<p style="margin-top:24pt;color:#c00;font-size:10pt;text-align:center;font-weight:bold;">未签发草稿 · 仅供内部核对，不作为正式病历</p>'
}
</body></html>`
  const blob = new Blob(['﻿' + html], { type: 'application/msword;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  // 文件名脱敏（2026-08-28 PHI 审计）：全名会永久留在公用电脑下载目录/
  // 最近文件/回收站，文书类型本身就是病情线索。取姓+*，医生仍可辨认。
  a.download = `${typeLabel}_${maskName(patient?.name)}.doc`
  a.click()
  URL.revokeObjectURL(url)
}
