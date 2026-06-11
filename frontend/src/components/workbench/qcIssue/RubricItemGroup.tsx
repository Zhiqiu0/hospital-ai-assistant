/**
 * 单大项分组块（components/workbench/qcIssue/RubricItemGroup.tsx）
 *
 * 从 QCIssuePanel.tsx 拆出（2026-06-11 Round 5.5 拆分），逻辑一字未改。
 *
 * A 方案核心组件。显示：
 *   ▶ 现病史 (实际扣 7/20 分)              ← 头部，可点击折叠
 *     [-5 分] 现病史缺失或主要症状描述不清
 *     [-2 分] 缺诊治经过
 *
 *   ▶ 治疗意见及措施 (实际扣 10/10 分 ⚠️ 已达上限)
 *     [-5 分] 检查治疗项目不明确
 *     [-5 分] 治则治法与证型不符
 *     [-5 分] 无复诊建议或注意事项
 *     原始扣分 15 分 → 按 PDF 大项上限保护实际扣 10 分
 *
 * 默认展开（医生需要一屏看完），头部可点击切折叠。
 */
import { useState } from 'react'
import { Tag, Tooltip, Typography } from 'antd'
import { CaretDownOutlined, CaretRightOutlined, WarningOutlined } from '@ant-design/icons'
import { QCIssue } from '@/store/types'

const { Text } = Typography

interface RubricItemGroupProps {
  itemName: string
  maxPoints: number
  deducted: number
  rawSum: number
  cappedDown: boolean
  vetoTriggered: boolean
  issues: QCIssue[]
  renderItem: (issue: QCIssue) => JSX.Element
}

export default function RubricItemGroup({
  itemName,
  maxPoints,
  deducted,
  rawSum,
  cappedDown,
  vetoTriggered,
  issues,
  renderItem,
}: RubricItemGroupProps) {
  // 默认展开（A 方案核心：一屏看完所有问题，医生可手动折叠）
  const [expanded, setExpanded] = useState(true)

  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 8,
        background: 'var(--surface-1)',
        marginBottom: 8,
      }}
    >
      {/* 头部：大项名 + 实际扣分/满分 + 角标 */}
      <div
        onClick={() => setExpanded(v => !v)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '8px 12px',
          cursor: 'pointer',
          userSelect: 'none',
          background: vetoTriggered ? '#fff1f2' : '#fffbeb',
          borderRadius: '8px 8px 0 0',
          fontSize: 12,
        }}
      >
        {expanded ? (
          <CaretDownOutlined style={{ fontSize: 10, color: 'var(--text-4)' }} />
        ) : (
          <CaretRightOutlined style={{ fontSize: 10, color: 'var(--text-4)' }} />
        )}
        <Text strong style={{ fontSize: 12 }}>
          {itemName}
        </Text>
        <Text type="secondary" style={{ fontSize: 11 }}>
          （实际扣 <Text type="danger">{deducted}</Text>/{maxPoints} 分）
        </Text>
        {vetoTriggered && (
          <Tag color="red" style={{ fontSize: 10, marginLeft: 4 }}>
            单项否决
          </Tag>
        )}
        {cappedDown && !vetoTriggered && (
          <Tooltip
            title={`原始扣分 ${rawSum} 分 → 按 PDF 大项上限保护实际扣 ${deducted} 分（同一项扣分不超过该项满分）`}
          >
            <Tag color="orange" icon={<WarningOutlined />} style={{ fontSize: 10, marginLeft: 4 }}>
              已达上限
            </Tag>
          </Tooltip>
        )}
      </div>

      {/* 展开后：该大项内所有 issue */}
      {expanded && (
        <div style={{ padding: '4px 8px 8px 8px' }}>
          {issues.map(renderItem)}
          {cappedDown && !vetoTriggered && (
            <Text
              type="secondary"
              style={{
                display: 'block',
                fontSize: 10,
                marginTop: 4,
                paddingLeft: 8,
                fontStyle: 'italic',
              }}
            >
              ↑ 原始扣分总计 {rawSum} 分，按 PDF 大项上限保护实际扣 {deducted} 分
            </Text>
          )}
        </div>
      )}
    </div>
  )
}
