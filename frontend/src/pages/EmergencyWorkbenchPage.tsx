/**
 * 急诊工作台页面（pages/EmergencyWorkbenchPage.tsx）
 *
 * 急诊接诊入口，复用 WorkbenchPage 组件并传入 mode="emergency"。
 * 与门诊工作台的差异由 WorkbenchPage 内部根据 mode 参数控制：
 *   - 病历类型默认值：emergency（急诊病历）
 *   - 问诊模板：急诊关注主诉紧迫性、生命体征优先
 */
import WorkbenchPage from './WorkbenchPage'

export default function EmergencyWorkbenchPage() {
  return <WorkbenchPage mode="emergency" />
}
