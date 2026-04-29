/**
 * 质控问题面板常量（components/workbench/qcIssue/qcConstants.ts）
 *
 * 风险级别 / 问题类型对应的 antd Tag 颜色与中文标签。
 * 从 QCIssuePanel.tsx 拆出（Audit Round 4 M6），方便子组件复用，避免散落的字面量。
 */

export const QC_RISK_COLOR: Record<string, string> = {
  high: 'red',
  medium: 'orange',
  low: 'default',
}

export const QC_RISK_LABEL: Record<string, string> = {
  high: '高风险',
  medium: '中风险',
  low: '低风险',
}

export const QC_TYPE_COLOR: Record<string, string> = {
  completeness: 'blue',
  insurance: 'purple',
  format: 'cyan',
  logic: 'gold',
  normality: 'geekblue',
}

export const QC_TYPE_LABEL: Record<string, string> = {
  completeness: '完整性',
  insurance: '医保风险',
  format: '格式',
  logic: '逻辑',
  normality: '规范性',
}
