/**
 * 住院时间轴面板（components/workbench/InpatientTimeline.tsx）
 *
 * 展示当前住院接诊的所有文书（入院记录 + 病程记录），按时间排列。
 * 支持选中条目、新建病程记录、删除草稿。
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { Button, Tag, Empty, Spin, Popconfirm } from 'antd'
import { message } from '@/services/messageBridge'
import { PlusOutlined, DeleteOutlined, FileTextOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useRecordStore } from '@/store/recordStore'
import { buildTimeline, TimelineItem } from '@/domain/inpatient'
import { getNoteRule } from '@/domain/inpatient'
import api from '@/services/api'

interface Props {
  selectedId: string | null
  onSelect: (item: TimelineItem) => void
  onCreated: () => void // 新建后刷新
  refreshToken: number // 外部触发刷新
}

// 时间轴底部的「新建文书」按钮。
//
// value 用的是**正式病历**的 record_type（2026-08-14 统一文书模型）：
// 这些按钮原先建的是 progress_notes ——那是一张与病历主表互不相通的表，
// 没有版本、没有签名链、不回写 HIS、不进任何病历列表与质控，
// 而界面上它同样显示「已签发」，医生完全看不出区别。
// 统一到 medical_records 后这四样自动都有。
// 命名对齐 HL7 FHIR 的做法：所有临床文书是同一个文档模型，靠 type 码区分种类。
const NOTE_TYPE_OPTIONS = [
  { value: 'first_course_record', label: '首次病程' },
  { value: 'course_record', label: '日常病程' },
  { value: 'senior_round', label: '上级查房' },
  { value: 'discharge_record', label: '出院记录' },
]

export default function InpatientTimeline({
  selectedId,
  onSelect,
  onCreated,
  refreshToken,
}: Props) {
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const recordContent = useRecordStore(s => s.recordContent)
  const recordType = useRecordStore(s => s.recordType)
  // 正文/类型只在"服务端没有 active_record 时造一个本地占位条目"用得到。
  // 把它们放进 load 的依赖数组，会让**医生每敲一个字、AI 每吐一个 chunk**
  // 都重跑 useCallback → useEffect 重新执行 → 重发两个 GET
  // （workspace）。写一段病程就是上百次无谓请求。
  // 用 ref 读实时值，依赖只留接诊 id（2026-08-14 第六轮审计修复）。
  const draftRef = useRef({ content: recordContent, type: recordType })
  // 在 effect 里同步而不是渲染期直接赋值——渲染期写 ref 是 React 反模式
  // （eslint react-hooks 规则会拦），且会让组件不按预期更新。
  useEffect(() => {
    draftRef.current = { content: recordContent, type: recordType }
  }, [recordContent, recordType])
  const [items, setItems] = useState<TimelineItem[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    if (!currentEncounterId) return
    setLoading(true)
    try {
      // 后端返回的 progress note / active_record 字段并不稳定（admission_note 部分
      // 来自 workspace.active_record，含字段视 record_type 而定），所以用 Record 装载
      type RecordLike = Record<string, unknown>
      // 只拉 workspace（2026-08-14 统一文书模型）：住院文书已全部落在
      // medical_records，progress_notes 那条旧路没有任何入口了，多这一个
      // 请求也拿不到东西。
      const recordRes = (await api.get(`/encounters/${currentEncounterId}/workspace`)) as {
        active_record?: RecordLike
        records?: RecordLike[]
      }

      // 病历条目取 workspace 的**完整 records 列表**（2026-08-14 第六轮审计修复）
      //
      // 原先只取 active_record 一份，且把 record_type 覆盖成
      // `draft.type`（编辑器下拉当前选中的类型）。两处都错：
      //   ① 住院一次接诊有入院记录 + 多份病程 + 出院小结，时间轴只显示一份，
      //      医生看不到自己写过的其他文书；
      //   ② 用当前下拉类型覆盖真实类型——医生把下拉切到"出院记录"，
      //      时间轴上那份入院记录就被标成出院记录，时间轴变成误导。
      // 后端 workspace 一直返回 records 完整列表，直接用它，各条保留自己的类型。
      const draft = draftRef.current
      const admissionItems: RecordLike[] = [...(recordRes.records || [])]
      if (admissionItems.length === 0 && draft.content) {
        // 服务端还没有任何病历（医生正在写第一份且未保存）→ 造一个本地占位
        admissionItems.push({
          id: 'current-admission',
          record_type: draft.type || 'admission_note',
          content: draft.content,
          status: 'draft',
          created_at: new Date().toISOString(),
        })
      }

      setItems(buildTimeline(admissionItems, []))
    } catch {
      message.error('加载病程记录失败')
    } finally {
      setLoading(false)
    }
  }, [currentEncounterId])

  useEffect(() => {
    load()
  }, [load, refreshToken])

  const handleCreate = async (noteType: string) => {
    if (!currentEncounterId) return
    setCreating(true)
    try {
      // 建一份空的正式病历草稿（auto-save 接口首次调用即建 record）。
      // recorded_at 传当前时刻：这是"这份文书对应的诊疗时点"，医生随后可在
      // 面板里调整；与系统录入时间差得多会被后端标为「补记」——
      // 规范不允许静默回填时间线，见 backend/app/services/record_time.py。
      interface DraftResponse {
        record_id: string
        version_no: number
      }
      const draft = (await api.post('/medical-records/auto-save-draft', {
        encounter_id: currentEncounterId,
        record_type: noteType,
        content: '',
        recorded_at: dayjs().format('YYYY-MM-DDTHH:mm:ss'),
      })) as DraftResponse
      await load()
      onSelect({
        id: draft.record_id,
        type: 'medical_record',
        noteType,
        label: getNoteRule(noteType).label,
        color: getNoteRule(noteType).color,
        bgColor: getNoteRule(noteType).bgColor,
        recordedAt: dayjs().format('YYYY-MM-DDTHH:mm:ss'),
        status: 'editing',
        content: '',
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
      // 只删得掉**空白草稿**（误点新建的）。病历是法律文件，写过内容的只能
      // 走修订留痕、已签发的不可删——后端会返回 409 并说明原因，
      // 这里如实透传给医生，而不是笼统报删除失败。
      await api.delete(`/medical-records/${item.id}`)
      await load()
      message.success('已删除')
    } catch (err) {
      const detail = (err as { detail?: string })?.detail
      message.error(detail || '删除失败')
    }
  }

  if (!currentEncounterId)
    return (
      <Empty
        description="请先选择患者"
        style={{ marginTop: 40 }}
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    )
  if (loading)
    return (
      <div style={{ textAlign: 'center', padding: 24 }}>
        <Spin size="small" />
      </div>
    )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 时间轴列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
        {items.length === 0 ? (
          <Empty
            description="暂无文书"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            style={{ marginTop: 24 }}
          />
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
                  <Tag color={item.color} style={{ margin: 0, fontSize: 11 }}>
                    {item.label}
                  </Tag>
                  {item.status === 'submitted' && (
                    <Tag color="green" style={{ margin: 0, fontSize: 10 }}>
                      已签发
                    </Tag>
                  )}
                  {item.status === 'draft' && (
                    <Tag color="default" style={{ margin: 0, fontSize: 10 }}>
                      草稿
                    </Tag>
                  )}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-4)', marginTop: 2 }}>
                  {item.recordedAt
                    ? new Date(item.recordedAt).toLocaleString('zh-CN', {
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit',
                      })
                    : ''}
                </div>
              </div>
              {/* 只有未签发草稿能删；后端还会再判一次「必须是空白草稿」，
                  写过内容的只能走修订留痕（病历是法律文件） */}
              {item.status !== 'submitted' && (
                <Popconfirm
                  title="确认删除？"
                  onConfirm={e => {
                    e?.stopPropagation()
                    handleDelete(item)
                  }}
                  okText="删除"
                  cancelText="取消"
                >
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
      <div
        style={{
          borderTop: '1px solid var(--border)',
          padding: '8px 12px',
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
        }}
      >
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
