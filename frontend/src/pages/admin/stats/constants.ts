/**
 * 统计页常量映射（admin/stats/constants.ts）
 *
 * 抽出来供 4 个 Tab 共用，避免 StatsPage 容器膨胀。
 */

export const TASK_TYPE_MAP: Record<string, string> = {
  generate: '病历生成',
  polish: '病历润色',
  qc: 'AI质控',
  inquiry: '追问建议',
  exam: '检查建议',
}

export const RISK_COLOR: Record<string, string> = {
  high: 'red',
  medium: 'orange',
  low: 'blue',
}

export const RISK_LABEL: Record<string, string> = {
  high: '高风险',
  medium: '中风险',
  low: '低风险',
}

export const ISSUE_TYPE_LABEL: Record<string, string> = {
  completeness: '完整性缺失',
  format: '格式不规范',
  logic: '逻辑问题',
  insurance: '医保风险',
  normality: '规范性',
  consistency: '一致性',
}
