/**
 * 数据更正页（/admin/data-fix）
 *
 * 2026-09-01 新增。汇集两个「录错了怎么办」的工具：HIS 工号改绑与重复档案合并。
 * 这两件事在开业第一周撞上的概率最高，而在此之前系统对它们零应对能力——
 * 工号绑错人时提示「请联系管理员改派」而改派功能不存在；三处代码注释写着
 * 重复档案「可事后人工合并」而合并功能同样不存在。
 */
import DoctorCodePanel from './dataFix/DoctorCodePanel'
import PatientMergePanel from './dataFix/PatientMergePanel'

export default function DataFixPage() {
  return (
    <div>
      <DoctorCodePanel />
      <PatientMergePanel />
    </div>
  )
}
