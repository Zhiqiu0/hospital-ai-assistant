/**
 * 病历导出/打印的审计上报（utils/exportAudit.ts，2026-08-14 第六轮审计修复）
 *
 * 为什么需要：打印与导出 Word 全在客户端完成（前端直接把正文拼成 HTML 再
 * 下载/打印），服务端根本不知道发生过——而**导出是把整份病历连同患者身份信息
 * 一起带走**，是所有 PHI 操作里最敏感的一个。放开归属校验后审计是唯一的追责
 * 手段，这条路径上却完全没有留痕。
 *
 * 为什么单独封一个函数而不是在每个调用点写：导出入口有三处（编辑器状态栏打印、
 * 工具栏导出 Word、病历查看弹窗打印），以后还会加。散着写必然漏一个，
 * 而漏掉的那个就是没留痕的导出口。
 */

import api from '@/services/api'

interface ExportAuditPayload {
  record_id?: string | null
  encounter_id?: string | null
  record_type?: string | null
  /** print=打印，word=导出 Word */
  method: 'print' | 'word'
  is_signed: boolean
}

/**
 * 上报一次导出/打印。
 *
 * 刻意不 await、不抛错：审计失败绝不能阻断医生导出病历（那是正常业务动作），
 * 后端 log_action 内部也已吞掉写入异常。
 */
export function reportRecordExport(payload: ExportAuditPayload): void {
  void api.post('/medical-records/export-audit', payload).catch(() => {
    // 静默：上报失败不影响导出本身
  })
}
