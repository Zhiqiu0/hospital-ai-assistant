/**
 * 上次病历参考面板（components/workbench/PreviousRecordPanel.tsx）
 * 复诊时在病历编辑区上方展示上次病历全文，折叠只读，供医生参考。
 */
import { useState } from 'react'
import { Button } from 'antd'
import { HistoryOutlined, DownOutlined, UpOutlined } from '@ant-design/icons'

interface Props {
  content: string
}

export default function PreviousRecordPanel({ content }: Props) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div
      style={{
        borderBottom: '1px solid #fde68a',
        background: '#fffbeb',
        flexShrink: 0,
      }}
    >
      {/* 折叠标题栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '6px 14px',
          cursor: 'pointer',
          userSelect: 'none',
        }}
        onClick={() => setExpanded(v => !v)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <HistoryOutlined style={{ color: '#d97706', fontSize: 13 }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: '#92400e' }}>
            上次病历参考（只读）
          </span>
        </div>
        <Button
          type="text"
          size="small"
          icon={expanded ? <UpOutlined /> : <DownOutlined />}
          style={{ color: '#92400e', fontSize: 11 }}
        >
          {expanded ? '收起' : '展开查看'}
        </Button>
      </div>

      {/* 病历全文 */}
      {expanded && (
        <div
          style={{
            padding: '0 14px 12px',
            maxHeight: 360,
            overflowY: 'auto',
            borderTop: '1px solid #fde68a',
          }}
        >
          <pre
            style={{
              fontSize: 12,
              lineHeight: 1.8,
              color: '#78350f',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              margin: '10px 0 0',
              fontFamily: 'inherit',
            }}
          >
            {content}
          </pre>
        </div>
      )}
    </div>
  )
}
