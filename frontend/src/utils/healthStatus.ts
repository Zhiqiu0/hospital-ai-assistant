/** 深度探活展示契约；提取为纯函数便于验证错误状态不会误报正常。 */
export interface HealthDeep {
  status: string
  deps: { db?: string; redis?: string; ai_credential?: string; orthanc?: string; holiday_calendar?: string }
}

export function describeHealth(
  health: HealthDeep | null,
  failed: boolean
): { text: string; type: 'success' | 'warning' | 'error' } {
  if (!health) {
    return failed
      ? { text: '无法获取系统健康状态（健康检查接口不可达）', type: 'warning' }
      : { text: '正在检测系统健康状态…', type: 'warning' }
  }
  const d = health.deps || {}
  const bad: string[] = []
  if (d.db && d.db !== 'ok') bad.push('数据库')
  if (d.redis === 'error') bad.push('Redis 缓存/事件总线')
  if (d.ai_credential === 'missing') bad.push('AI 凭证未配置')
  if (d.ai_credential === 'invalid') bad.push('AI 凭证已失效或无权限')
  if (d.ai_credential === 'unavailable') bad.push('AI 账户余额不足')
  if (d.ai_credential === 'error') bad.push('AI 供应商鉴权探测失败')
  if (d.orthanc === 'error') bad.push('影像服务')
  if (d.holiday_calendar === 'expired') bad.push('节假日日历已过期')
  if (!bad.length && d.ai_credential === 'unverified') {
    return { text: 'AI 供应商鉴权未验证，请完成实际功能检查；当前不能确认系统全部健康', type: 'warning' }
  }
  // 新增依赖尚未进入前端词典时，仍尊重后端总体降级结果。
  if (health.status !== 'ok' && !bad.length) bad.push('关键依赖')
  if (bad.length) {
    return { text: `系统异常 — ${bad.join('、')}不可用，请立即检查`, type: 'error' }
  }
  if (d.ai_credential !== 'ok' || d.db !== 'ok') {
    return { text: '部分服务未验证：AI 凭证或数据库状态未确认，请完成实际功能检查', type: 'warning' }
  }
  const note = d.redis === 'unconfigured' ? '（Redis 未配置）' : ''
  return { text: `数据库连接、AI 鉴权及账户可用性检查通过${note}；生成质量需通过实际病历验证`, type: 'success' }
}
