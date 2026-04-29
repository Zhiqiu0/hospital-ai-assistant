/**
 * 住院文书时效提醒栏（components/workbench/ComplianceBar.tsx）
 *
 * 显示各类住院文书的书写时限（入院记录24小时、首次病程8小时），
 * 并根据剩余时间用颜色区分紧急程度。
 * 点击某条提示可直接切换到对应病历类型。
 */
import { useEffect, useState, useCallback } from 'react'
import { Typography, Tooltip } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import api from '@/services/api'
import { useRecordStore } from '@/store/recordStore'

const { Text } = Typography

interface ComplianceItem {
  record_type: string
  label: string
  deadline_hours: number
  deadline: string
  status: 'done' | 'ok' | 'urgent' | 'overdue'
  detail: string
  done_at: string | null
}

const STATUS_CONFIG = {
  done: { color: '#16a34a', bg: '#f0fdf4', border: '#bbf7d0', icon: <CheckCircleOutlined /> },
  ok: { color: '#0284c7', bg: '#f0f9ff', border: '#bae6fd', icon: <ClockCircleOutlined /> },
  urgent: { color: '#d97706', bg: '#fffbeb', border: '#fde68a', icon: <WarningOutlined /> },
  overdue: {
    color: '#dc2626',
    bg: '#fef2f2',
    border: '#fecaca',
    icon: <ExclamationCircleOutlined />,
  },
}

interface Props {
  encounterId: string | null
}

export default function ComplianceBar({ encounterId }: Props) {
  const { setRecordType } = useRecordStore()
  const [items, setItems] = useState<ComplianceItem[]>([])

  const fetchCompliance = useCallback(async () => {
    if (!encounterId) return
    try {
      const res = (await api.get(`/encounters/${encounterId}/compliance`)) as any
      setItems(res.items || [])
    } catch {
      setItems([])
    }
  }, [encounterId])

  useEffect(() => {
    fetchCompliance()
    // 每分钟刷新一次时效状态
    const timer = setInterval(fetchCompliance, 60000)
    return () => clearInterval(timer)
  }, [fetchCompliance])

  if (!encounterId || items.length === 0) return null

  // 只显示未完成或已超时的条目（done 的在只有 overdue/urgent 时才一起显示）
  const hasUrgent = items.some(i => i.status === 'urgent' || i.status === 'overdue')
  const visibleItems = hasUrgent ? items : items.filter(i => i.status !== 'done')
  if (visibleItems.length === 0) return null

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '5px 12px',
        background: '#fffbeb',
        borderBottom: '1px solid #fde68a',
        flexShrink: 0,
        flexWrap: 'wrap',
      }}
    >
      <Text style={{ fontSize: 11, fontWeight: 700, color: '#92400e', flexShrink: 0 }}>
        文书时效
      </Text>
      {visibleItems.map(item => {
        const cfg = STATUS_CONFIG[item.status]
        return (
          <Tooltip key={item.record_type} title={`点击切换至${item.label}`}>
            <div
              onClick={() => {
                if (item.status !== 'done') setRecordType(item.record_type)
              }}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                background: cfg.bg,
                border: `1px solid ${cfg.border}`,
                borderRadius: 6,
                padding: '2px 8px',
                cursor: item.status !== 'done' ? 'pointer' : 'default',
                transition: 'all 0.15s',
              }}
            >
              <span style={{ color: cfg.color, fontSize: 12 }}>{cfg.icon}</span>
              <Text style={{ fontSize: 11, fontWeight: 600, color: cfg.color }}>{item.label}</Text>
              <Text style={{ fontSize: 10, color: cfg.color }}>{item.detail}</Text>
            </div>
          </Tooltip>
        )
      })}
    </div>
  )
}
