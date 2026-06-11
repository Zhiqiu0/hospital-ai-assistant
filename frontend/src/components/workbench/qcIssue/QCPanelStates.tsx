/**
 * 质控面板空态/通过态视图（components/workbench/qcIssue/QCPanelStates.tsx）
 *
 * 从 QCIssuePanel.tsx 拆出（2026-06-11 Round 5.5 拆分），逻辑一字未改：
 *   - QCInitialEmpty：尚未执行质控时的空态提示（原第一个 early-return）
 *   - QCPassedView：质控通过且无问题时的成功提示（原第二个 early-return）
 * 纯展示组件，无状态、无副作用。
 */
import { Alert, Empty } from 'antd'
import type { GradeScore } from '@/store/types'
import GradeScoreCard from '../GradeScoreCard'

/** 尚未执行质控时的空态视图 */
export function QCInitialEmpty({ gradeScore }: { gradeScore: GradeScore | null }) {
  return (
    <>
      {gradeScore != null && <GradeScoreCard gradeScore={gradeScore} />}
      <Empty
        description={
          <span style={{ fontSize: 13, color: 'var(--text-4)' }}>
            点击「AI质控」进行病历质量检查
          </span>
        }
        style={{ marginTop: gradeScore ? 16 : 40 }}
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    </>
  )
}

/** 质控通过且无问题时的成功视图 */
export function QCPassedView({
  gradeScore,
  qcSummary,
}: {
  gradeScore: GradeScore | null
  qcSummary: string
}) {
  return (
    <>
      {gradeScore != null && <GradeScoreCard gradeScore={gradeScore} />}
      <Alert
        message="质控通过"
        description={qcSummary || '病历内容符合规范要求'}
        type="success"
        showIcon
        style={{ marginTop: 8, borderRadius: 8 }}
      />
    </>
  )
}
