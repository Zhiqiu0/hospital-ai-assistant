import { Tabs, Badge } from 'antd'
import { QuestionCircleOutlined, ExperimentOutlined, SafetyOutlined } from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import InquirySuggestionTab from './InquirySuggestionTab'
import ExamSuggestionTab from './ExamSuggestionTab'
import QCIssuePanel from './QCIssuePanel'

export default function AISuggestionPanel() {
  const { qcIssues, inquirySuggestions } = useWorkbenchStore()

  const unansweredCount = inquirySuggestions.filter(s => s.selectedOptions.length === 0).length
  const highRiskQcCount = qcIssues.filter(i => i.risk_level === 'high').length

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
            <div
              style={{ padding: '0 12px 16px', overflowY: 'auto', height: 'calc(100vh - 130px)' }}
            >
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
            <Badge count={highRiskQcCount} size="small" offset={[4, -2]}>
              <span>
                <SafetyOutlined style={{ marginRight: 4 }} />
                质控提示
              </span>
            </Badge>
          ),
          children: (
            <div style={{ padding: '8px 12px', overflowY: 'auto', height: 'calc(100vh - 130px)' }}>
              <QCIssuePanel />
            </div>
          ),
        },
      ]}
    />
  )
}
