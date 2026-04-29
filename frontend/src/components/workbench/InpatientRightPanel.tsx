/**
 * 住院工作台右侧面板（components/workbench/InpatientRightPanel.tsx）
 *
 * 4 Tab 切换：
 *   AI 建议 / 病程记录时间轴 / 问题列表 / 体征
 *
 * 时间轴 Tab 是住院端核心：医生在这里点击不同病程进入对应编辑器。
 */
import { Tabs } from 'antd'
import { UnorderedListOutlined, HeartOutlined, FileTextOutlined } from '@ant-design/icons'
import AISuggestionPanel from './AISuggestionPanel'
import InpatientTimeline from './InpatientTimeline'
import ProblemListPanel from './ProblemListPanel'
import VitalsPanel from './VitalsPanel'
import type { TimelineItem } from '@/domain/inpatient'

interface InpatientRightPanelProps {
  selectedNote: TimelineItem | null
  setSelectedNote: (item: TimelineItem | null) => void
  timelineRefresh: number
  setTimelineRefresh: (updater: (n: number) => number) => void
}

export default function InpatientRightPanel({
  selectedNote,
  setSelectedNote,
  timelineRefresh,
  setTimelineRefresh,
}: InpatientRightPanelProps) {
  return (
    <div
      style={{
        width: 340,
        background: 'var(--surface)',
        borderRadius: 12,
        border: '1px solid var(--border)',
        overflow: 'hidden',
        flexShrink: 0,
        boxShadow: 'var(--shadow-sm)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Tabs
        defaultActiveKey="ai"
        size="small"
        style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
        tabBarStyle={{ padding: '0 12px', marginBottom: 0, flexShrink: 0 }}
        items={[
          {
            key: 'ai',
            label: 'AI 建议',
            children: (
              <div style={{ overflow: 'auto', height: '100%' }}>
                <AISuggestionPanel />
              </div>
            ),
          },
          {
            key: 'timeline',
            label: (
              <span>
                <FileTextOutlined /> 病程记录
              </span>
            ),
            children: (
              <div style={{ overflow: 'hidden', height: '100%' }}>
                <InpatientTimeline
                  selectedId={selectedNote?.id || null}
                  onSelect={setSelectedNote}
                  onCreated={() => setTimelineRefresh(n => n + 1)}
                  refreshToken={timelineRefresh}
                />
              </div>
            ),
          },
          {
            key: 'problems',
            label: (
              <span>
                <UnorderedListOutlined /> 问题列表
              </span>
            ),
            children: (
              <div style={{ overflow: 'auto', height: '100%' }}>
                <ProblemListPanel />
              </div>
            ),
          },
          {
            key: 'vitals',
            label: (
              <span>
                <HeartOutlined /> 体征
              </span>
            ),
            children: (
              <div style={{ overflow: 'auto', height: '100%' }}>
                <VitalsPanel />
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}
