/**
 * 患者档案"新鲜度"工具（components/workbench/patientProfile/staleness.ts）
 *
 * 把 PatientProfileCard 里"距今天数 → 颜色 + 文案"逻辑独立出来（Audit Round 4 M6）。
 *
 * 染色阈值（基于 staleAfterDays 参数）：
 *   ≤ 7 天             灰色（新鲜，不打扰）
 *   ≤ staleAfterDays   浅褐（默认范围内，建议关注）
 *   ≤ 3×staleAfterDays 橙黄背景（建议确认）
 *   > 3×staleAfterDays 深橙背景（请重新核对）
 *
 * 文案规则：今天 / N 天前 / N 月前 / N 年前确认。
 */

import { usePatientProfileCard } from '@/hooks/usePatientProfileCard'

/** PatientProfileCard 字段配置（不含月经史）。 */
export interface FieldConfig {
  key: keyof ReturnType<typeof usePatientProfileCard>['form']
  label: string
  rows: number
  placeholder: string
  /** 单行 Input 而非 TextArea。 */
  singleLine?: boolean
  /** 该字段 N 天后开始黄色提醒（不传走默认 180 天）。 */
  staleAfterDays?: number
}

/**
 * 7 个档案字段（不含月经史 — 月经史是时变信息，挪去 InpatientInquiryPanel 的专项评估）。
 * staleAfterDays：长期用药 30 天，其他用默认 180 天。
 */
export const PROFILE_FIELDS: FieldConfig[] = [
  {
    key: 'past_history',
    label: '既往史',
    rows: 2,
    placeholder: '既往病史、手术史、传染病史；无特殊可填「既往体质可」',
  },
  {
    key: 'allergy_history',
    label: '过敏史',
    rows: 1,
    placeholder: '如：青霉素过敏 / 否认药物及食物过敏史',
    singleLine: true,
  },
  {
    key: 'personal_history',
    label: '个人史',
    rows: 2,
    placeholder: '吸烟、饮酒、职业、生活习惯；无特殊可填「无特殊」',
  },
  {
    key: 'family_history',
    label: '家族史',
    rows: 2,
    placeholder: '直系亲属重要疾病史；无特殊可填「无特殊」',
  },
  {
    key: 'current_medications',
    label: '长期用药',
    rows: 2,
    placeholder: '正在服用的药物名称、剂量、用法；无可填「无」',
    staleAfterDays: 30, // 用药变化快，30 天就提醒确认
  },
  {
    key: 'marital_history',
    label: '婚育史',
    rows: 2,
    placeholder: '婚姻、生育情况；无特殊可填「适龄结婚，配偶子女体健」',
  },
  {
    key: 'religion_belief',
    label: '宗教信仰',
    rows: 1,
    placeholder: '如：无 / 佛教 / 基督教（涉及禁忌时填写）',
    singleLine: true,
  },
]

export interface StalenessInfo {
  days: number
  label: string
  color: string
  bgColor?: string
}

/**
 * 计算字段元数据距今的"天数 + 颜色"。未录入或非法时间返回 null。
 * staleAfterDays：超过此天数显示为浅褐；3×staleAfterDays 显示为橙黄。
 */
export function getStaleness(
  updatedAt: string | null | undefined,
  staleAfterDays: number
): StalenessInfo | null {
  if (!updatedAt) return null
  const updated = new Date(updatedAt).getTime()
  if (Number.isNaN(updated)) return null
  const days = Math.floor((Date.now() - updated) / (1000 * 60 * 60 * 24))
  let color: string
  let bgColor: string | undefined
  if (days <= 7) {
    color = '#9ca3af' // 灰：新鲜
  } else if (days <= staleAfterDays) {
    color = '#a16207' // 浅褐：默认范围内
  } else if (days <= staleAfterDays * 3) {
    color = '#b45309' // 橙黄：建议确认
    bgColor = '#fef3c7'
  } else {
    color = '#ea580c' // 深橙：请重新核对
    bgColor = '#ffedd5'
  }
  let label: string
  if (days === 0) label = '今天确认'
  else if (days < 30) label = `${days} 天前确认`
  else if (days < 365) label = `${Math.floor(days / 30)} 个月前确认`
  else label = `${Math.floor(days / 365)} 年前确认`
  return { days, label, color, bgColor }
}
