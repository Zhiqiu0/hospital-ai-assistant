/**
 * URL 脱敏工具（services/urlSanitize.ts，2026-08-28 PHI 出口审计抽出）
 *
 * 把 URL 里的常见 ID（uuid / 长 hex / 纯数字 ID）替换为占位符、剥掉查询串
 * （患者搜索 keyword=姓名 会走查询串），保留 endpoint 结构便于聚合分析。
 *
 * 原先私有在 api.ts 只服务 console；PHI 审计发现 Sentry 的 breadcrumbs 与
 * http.url tag 是清洗盲区（报错事件会携带 /patients?keyword=张三 出境到
 * Sentry 云且 tag 可索引），抽成共享模块让 api.ts 与 sentry.ts 用同一把刀。
 */
export function sanitizeUrlForLog(url: string): string {
  if (!url) return ''
  return (
    url
      // UUID（含/不含连字符）
      .replace(
        /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g,
        ':uuid'
      )
      // 长 hex（>=24 字符，覆盖患者外部码 / sha 等）
      .replace(/\b[0-9a-fA-F]{24,}\b/g, ':hex')
      // 纯数字 ID（连续 6 位以上，避免误伤短数字如分页）
      .replace(/\/\d{6,}/g, '/:num')
      // query string（可能含患者姓名 / 关键词）
      .replace(/\?.*$/, '?[scrubbed]')
  )
}
