/**
 * AI 辅助建议面板（components/workbench/AISuggestionPanel.tsx）
 *
 * 三栏标签页，汇总来自 DeepSeek 的三类实时 AI 辅助建议：
 *   1. 「问诊建议」(InquirySuggestionTab)  — 追问方向与鉴别诊断思路
 *   2. 「检查建议」(ExamSuggestionTab)     — 推荐检查项目及理由
 *   3. 「诊断建议」(DiagnosisSuggestionTab)— 鉴别诊断列表及置信度
 *
 * 未读徽标：
 *   workbenchStore.suggestions 中每类建议有独立 seen 标记；
 *   收到新建议时对应标签显示红点，点进去后标记已读。
 *
 * 各 Tab 均通过 SSE stream 实时填充，用户无需手动刷新。
 */
import { Tabs, Badge } from 'antd'
import { QuestionCircleOutlined, ExperimentOutlined, SafetyOutlined } from '@ant-design/icons'
import { useQCStore } from '@/store/qcStore'
import { useAISuggestionStore } from '@/store/aiSuggestionStore'
import InquirySuggestionTab from './InquirySuggestionTab'
import ExamSuggestionTab from './ExamSuggestionTab'
import QCIssuePanel from './QCIssuePanel'

export default function AISuggestionPanel() {
  const qcIssues = useQCStore(s => s.qcIssues)
  const inquirySuggestions = useAISuggestionStore(s => s.inquirySuggestions)

  const unansweredCount = inquirySuggestions.filter(s => s.selectedOptions.length === 0).length
  // 角标 = 必须修复（阻塞出具）的问题数，与 QCIssuePanel 的"N 项必须修复"口径一致。
  // 2026-06-11 修复：原先按 risk_level==='high' 计数，与面板数字对不上
  // （E2E 实测角标 7 / 面板 9），医生不知道该信哪个数
  const blockingQcCount = qcIssues.filter(i => i.source === 'rule' || i.source == null).length

  return (
    <Tabs
      defaultActiveKey="inquiry"
      style={{ height: '100%' }}
      tabBarStyle={{ padding: '0 12px', marginBottom: 0 }}
      size="small"
      items={[
        {
          key: 'inquiry',
          label: (
            <Badge count={unansweredCount} size="small" offset={[4, -2]}>
              <span>
                <QuestionCircleOutlined style={{ marginRight: 4 }} />
                追问建议
              </span>
            </Badge>
          ),
          children: (
            <div style={{ padding: '0 12px 16px', overflowY: 'auto', height: '100%' }}>
              <InquirySuggestionTab />
            </div>
          ),
        },
        {
          key: 'exam',
          label: (
            <span>
              <ExperimentOutlined style={{ marginRight: 4 }} />
              检查建议
            </span>
          ),
          children: (
            <div style={{ padding: '8px 12px' }}>
              <ExamSuggestionTab />
            </div>
          ),
        },
        {
          key: 'qc',
          label: (
            <Badge count={blockingQcCount} size="small" offset={[4, -2]}>
              <span>
                <SafetyOutlined style={{ marginRight: 4 }} />
                质控提示
              </span>
            </Badge>
          ),
          children: (
            <div style={{ padding: '8px 12px', overflowY: 'auto', height: '100%' }}>
              <QCIssuePanel />
            </div>
          ),
        },
      ]}
    />
  )
}
