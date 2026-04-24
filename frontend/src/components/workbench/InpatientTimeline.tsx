/**
 * 住院时间轴面板（components/workbench/InpatientTimeline.tsx）
 *
 * 展示当前住院接诊的所有文书（入院记录 + 病程记录），按时间排列。
 * 支持选中条目、新建病程记录、删除草稿。
 */
import { useEffect, useState, useCallback } from 'react'
import { Button, Tag, Empty, Spin, Popconfirm, message } from 'antd'
import { PlusOutlined, DeleteOutlined, FileTextOutlined } from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import { buildTimeline, TimelineItem } from '@/domain/inpatient'
import { getNoteRule } from '@/domain/inpatient'
import api from '@/services/api'

interface Props {
  selectedId: string | null
  onSelect: (item: TimelineItem) => void
  onCreated: () => void   // 新建后刷新
  refreshToken: number    // 外部触发刷新
}

const NOTE_TYPE_OPTIONS = [
  { value: 'first_course', label: '首次病程' },
  { value: 'daily_course', label: '日常病程' },
  { value: 'surgery_pre',  label: '术前小结' },
  { value: 'surgery_post', label: '术后病程' },
  { value: 'discharge',    label: '出院小结' },
]

export default function InpatientTimeline({ selectedId, onSelect, onCreated, refreshToken }: Props) {
  const { currentEncounterId, recordContent, recordType } = useWorkbenchStore()
  const [items, setItems] = useState<TimelineItem[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    if (!currentEncounterId) return
    setLoading(true)
    try {
      const [notesRes, recordRes]: [any, any] = await Promise.all([
        api.get(`/encounters/${currentEncounterId}/progress-notes`),
        api.get(`/encounters/${currentEncounterId}/workspace`),
      ])
      const progressNotes = (notesRes as any).items || []

      // 入院记录从 workspace active_record 构造
      const admissionItems: any[] = []
      if ((recordRes as any).active_record) {
        admissionItems.push({
          ...(recordRes as any).active_record,
          record_type: recordType || 'admission_note',
        })
      } else if (recordContent) {
        admissionItems.push({
          id: 'current-admission',
          record_type: recordType || 'admission_note',
          content: recordContent,
          status: 'draft',
          created_at: new Date().toISOString(),
        })
      }

      setItems(buildTimeline(admissionItems, progressNotes))
    } catch {
      message.error('加载病程记录失败')
    } finally {
      setLoading(false)
    }
  }, [currentEncounterId, recordContent, recordType])

  useEffect(() => { load() }, [load, refreshToken])

  const handleCreate = async (noteType: string) => {
    if (!currentEncounterId) return
    setCreating(true)
    try {
      const note: any = await api.post(`/encounters/${currentEncounterId}/progress-notes`, {
        note_type: noteType,
        content: '',
      })
      await load()
      onSelect({
        id: note.id,
        type: 'progress_note',
        noteType: note.note_type,
        label: getNoteRule(note.note_type).label,
        color: getNoteRule(note.note_type).color,
        bgColor: getNoteRule(note.note_type).bgColor,
        recordedAt: note.recorded_at,
        status: note.status,
        content: note.content,
      })
      onCreated()
    } catch {
      message.error('新建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (item: TimelineItem) => {
    try {
      await api.delete(`/encounters/${currentEncounterId}/progress-notes/${item.id}`)
      await load()
      message.success('已删除')
    } catch {
      message.error('删除失败')
    }
  }

  if (!currentEncounterId) return <Empty description="请先选择患者" style={{ marginTop: 40 }} image={Empty.PRESENTED_IMAGE_SIMPLE} />
  if (loading) return <div style={{ textAlign: 'center', padding: 24 }}><Spin size="small" /></div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 时间轴列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
        {items.length === 0 ? (
          <Empty description="暂无文书" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 24 }} />
        ) : (
          items.map(item => (
            <div
              key={item.id}
              onClick={() => onSelect(item)}
              style={{
                padding: '8px 12px',
                margin: '2px 8px',
                borderRadius: 8,
                cursor: 'pointer',
                background: selectedId === item.id ? item.bgColor : 'var(--surface)',
                border: `1px solid ${selectedId === item.id ? '#93c5fd' : 'var(--border)'}`,
                display: 'flex',
                alignItems: 'flex-start',
                gap: 8,
              }}
            >
              <FileTextOutlined style={{ color: 'var(--text-4)', marginTop: 3, flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <Tag color={item.color} style={{ margin: 0, fontSize: 11 }}>{item.label}</Tag>
                  {item.status === 'submitted' && <Tag color="green" style={{ margin: 0, fontSize: 10 }}>已签发</Tag>}
                  {item.status === 'draft' && <Tag color="default" style={{ margin: 0, fontSize: 10 }}>草稿</Tag>}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-4)', marginTop: 2 }}>
                  {item.recordedAt ? new Date(item.recordedAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''}
                </div>
              </div>
              {item.type === 'progress_note' && item.status === 'draft' && (
                <Popconfirm title="确认删除？" onConfirm={e => { e?.stopPropagation(); handleDelete(item) }} okText="删除" cancelText="取消">
                  <DeleteOutlined
                    onClick={e => e.stopPropagation()}
                    style={{ color: '#ef4444', fontSize: 12, flexShrink: 0 }}
                  />
                </Popconfirm>
              )}
            </div>
          ))
        )}
      </div>

      {/* 新建按钮组 */}
      <div style={{ borderTop: '1px solid var(--border)', padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 4 }}>
        {NOTE_TYPE_OPTIONS.map(opt => (
          <Button
            key={opt.value}
            size="small"
            icon={<PlusOutlined />}
            loading={creating}
            onClick={() => handleCreate(opt.value)}
            style={{ fontSize: 12, textAlign: 'left', justifyContent: 'flex-start' }}
          >
            {opt.label}
          </Button>
        ))}
      </div>
    </div>
  )
}
