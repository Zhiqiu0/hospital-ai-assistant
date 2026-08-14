/**
 * 患者性别显示统一工具（utils/gender.ts，2026-08-14 第六轮审计修复）
 *
 * 为什么需要它：
 *   后端 patient.gender 存的是**中文**「男/女/未知」（HIS 建档推来的也是中文），
 *   但前端有 18 处各自写着 `gender === 'male' ? '男' : '女'` 这类三元表达式——
 *   中文值一律匹配不上 'male'，于是**男性患者被显示成「女」**。
 *   病历首页的性别写错是基本信息错误，会一路带进打印件和回写给 HIS 的内容。
 *
 *   根因不是某一处写错，而是"每个组件各自转换"这种写法必然发散。收口成一个
 *   函数后，无论后端给中文还是英文枚举都只在这里处理一次。
 */

/** 英文枚举 → 中文显示（后端历史上两种都出现过） */
const EN_TO_CN: Record<string, string> = {
  male: '男',
  female: '女',
  unknown: '未知',
  m: '男',
  f: '女',
}

/**
 * 把任意来源的性别值转成中文显示文本。
 *
 * - 中文「男/女/未知」原样返回
 * - 英文 male/female/unknown（含大小写、m/f 简写）转成中文
 * - 空值/无法识别 → 返回 fallback（默认空串，由调用方决定显示 '—' 还是留空）
 */
export function genderText(value?: string | null, fallback = ''): string {
  if (!value) return fallback
  const v = String(value).trim()
  if (!v) return fallback
  if (v === '男' || v === '女' || v === '未知') return v
  return EN_TO_CN[v.toLowerCase()] ?? fallback
}

/** 内部枚举：工作台/问诊表单统一用它，而不是各处零散判断 */
export type GenderCode = 'male' | 'female' | 'unknown'

/**
 * 把任意来源的性别值归一化成内部枚举。
 *
 * 与 genderText 的分工：genderText 管**显示**（转中文），本函数管**内部取值**
 * （转 male/female/unknown）。
 *
 * 为什么必须支持中文入参（2026-08-14 第六轮审计修复）：
 *   后端与 HIS 建档存的都是中文「男/女」，而原先各处写的是
 *   `p.gender === 'male' || p.gender === 'female' ? p.gender : 'unknown'`
 *   —— 中文值一律落到 'unknown'，于是打印病案首页的性别恒显示「未知」，
 *   月经史等按性别条件渲染的逻辑也全部失效（女性患者不显示月经史章节）。
 */
export function genderCode(value?: string | null): GenderCode {
  const cn = genderText(value)
  if (cn === '男') return 'male'
  if (cn === '女') return 'female'
  return 'unknown'
}
