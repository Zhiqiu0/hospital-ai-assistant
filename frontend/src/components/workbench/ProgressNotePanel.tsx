/**
 * 病程记录编辑/查看面板（components/workbench/ProgressNotePanel.tsx）
 *
 * 选中时间轴条目后展示此面板：
 *   - 入院记录（medical_record）：只读展示
 *   - 病程记录（progress_note）：草稿可编辑，已签发只读
 *   - 支持保存草稿、签发（submitted）
 */
import { useState, useEffect } from 'react'
import { Button, Input, Tag, Typography, DatePicker } from 'antd'
import { message } from '@/services/messageBridge'
import { SaveOutlined, CheckOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { TimelineItem } from '@/domain/inpatient'
import { getNoteRule } from '@/domain/inpatient'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import api from '@/services/api'
import { useProgressNoteAutosave } from './useProgressNoteAutosave'

const { TextArea } = Input
const { Text } = Typography

interface Props {
  item: TimelineItem | null
  onSaved: () => void // 保存/签发后通知时间轴刷新
}

export default function ProgressNotePanel({ item, onSaved }: Props) {
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const [content, setContent] = useState('')
  const [recordedAt, setRecordedAt] = useState<dayjs.Dayjs | null>(null)
  const [saving, setSaving] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  // 本地乐观状态覆盖：签发成功后 item prop 来不及刷新，先本地切到 submitted
  const [localStatus, setLocalStatus] = useState<string | null>(null)

  useEffect(() => {
    if (!item) return
    setContent(item.content || '')
    setRecordedAt(item.recordedAt ? dayjs(item.recordedAt) : dayjs())
    setLocalStatus(null) // 切换条目时清除本地覆盖
    // 只关心 item.id 变化（切到新条目时重置）；setState 在条目切换时是预期路径
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id])

  // 草稿自动保存（2026-08-14 第七轮审计 #34）：正文原先只活在上面这个 useState
  // 里，切换时间轴条目 / 关标签页 / 面板卸载都会无声吞掉医生已写的内容。
  // 已签发和入院记录是只读的，不参与。
  const { markSaved } = useProgressNoteAutosave({
    encounterId: currentEncounterId,
    itemId: item?.id,
    recordType: item?.noteType,
    content,
    recordedAt,
    disabled:
      !item || item.type === 'medical_record' || (localStatus || item.status) === 'submitted',
  })

  if (!item) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          color: 'var(--text-4)',
          fontSize: 13,
        }}
      >
        从左侧时间轴选择或新建文书
      </div>
    )
  }

  const rule = getNoteRule(item.noteType)
  // 用本地 localStatus 覆盖（签发成功后立即生效，不等外层 timeline refresh）
  const effectiveStatus = localStatus || item.status
  const isReadOnly = item.type === 'medical_record' || effectiveStatus === 'submitted'

  // 入院记录：直接展示病历文本
  if (item.type === 'medical_record') {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <div
          style={{
            padding: '10px 14px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            gap: 8,
            alignItems: 'center',
          }}
        >
          <Tag color={rule.color}>{rule.label}</Tag>
          <Tag color="green">已签发</Tag>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {item.recordedAt ? new Date(item.recordedAt).toLocaleString('zh-CN') : ''}
          </Text>
        </div>
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: 14,
            fontSize: 13,
            lineHeight: 1.9,
            whiteSpace: 'pre-wrap',
            fontFamily: 'inherit',
          }}
        >
          {item.content || '（内容为空）'}
        </div>
      </div>
    )
  }

  const handleSave = async () => {
    if (!currentEncounterId || !item) return
    setSaving(true)
    try {
      // 正式病历的草稿保存（统一文书模型，见 InpatientTimeline 的说明）
      await api.post('/medical-records/auto-save-draft', {
        encounter_id: currentEncounterId,
        record_type: item.noteType,
        content,
        // 用本地 naive ISO（无 Z/tz），配合后端 TIMESTAMP WITHOUT TIME ZONE 字段
        recorded_at: recordedAt?.format('YYYY-MM-DDTHH:mm:ss'),
      })
      // 基线复合键与 autosave 脏判断同口径（记录时间+正文，2026-08-28 补记修复）
      markSaved(`${recordedAt?.format('YYYY-MM-DDTHH:mm:ss') ?? ''}\u0001${content}`)
      message.success('已保存')
      onSaved()
    } catch {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleSubmit = async () => {
    if (!currentEncounterId || !item) return
    setSubmitting(true)
    try {
      // 走正式签发（quick-save）：这条路径才有版本、签名链、HIS 回写与质控。
      // 原先打 progress-notes 的 PATCH status=submitted，界面同样显示「已签发」，
      // 但那份文书四样一样都没有。
      await api.post('/medical-records/quick-save', {
        encounter_id: currentEncounterId,
        record_type: item.noteType,
        content,
      })
      setLocalStatus('submitted') // 乐观更新本地状态，立即切到只读
      message.success('已签发')
      onSaved()
    } catch {
      message.error('签发失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 顶部信息栏 */}
      <div
        style={{
          padding: '8px 14px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          flexWrap: 'wrap',
          flexShrink: 0,
        }}
      >
        <Tag color={rule.color}>{rule.label}</Tag>
        {isReadOnly ? <Tag color="green">已签发</Tag> : <Tag color="orange">草稿</Tag>}
        {/* 日期格式必须带年份（2026-08-14 第八轮审计）：原先是 MM-DD HH:mm，
            跨年补写时选出来的 2027-12-29 在框里显示成「12-29 10:00」，与正确的
            2026-12-29 肉眼完全无法区分，而病历时间逻辑是住院质控的必查项。
            后端对 recorded_at 有上限校验兜底（2026-08-28 补），界面同样禁选未来。 */}
        {!isReadOnly && (
          <DatePicker
            size="small"
            showTime={{ format: 'HH:mm' }}
            format="YYYY-MM-DD HH:mm"
            disabledDate={d => !!d && d.isAfter(dayjs(), 'day')}
            value={recordedAt}
            onChange={v => setRecordedAt(v)}
            style={{ fontSize: 12 }}
          />
        )}
        {isReadOnly && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {item.recordedAt ? new Date(item.recordedAt).toLocaleString('zh-CN') : ''}
          </Text>
        )}
      </div>

      {/* 编辑区 */}
      <div
        style={{
          flex: 1,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          padding: 10,
        }}
      >
        {isReadOnly ? (
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              fontSize: 13,
              lineHeight: 1.9,
              whiteSpace: 'pre-wrap',
              fontFamily: 'inherit',
              color: 'var(--text-1)',
            }}
          >
            {content || '（内容为空）'}
          </div>
        ) : (
          <TextArea
            value={content}
            onChange={e => setContent(e.target.value)}
            style={{
              flex: 1,
              resize: 'none',
              fontSize: 13,
              lineHeight: 1.8,
              fontFamily: 'inherit',
              border: 'none',
              boxShadow: 'none',
              padding: '4px 0',
            }}
            placeholder="在此书写病程记录..."
          />
        )}
      </div>

      {/* 操作栏 */}
      {!isReadOnly && (
        <div
          style={{
            borderTop: '1px solid var(--border)',
            padding: '8px 14px',
            display: 'flex',
            gap: 8,
            flexShrink: 0,
          }}
        >
          <Button size="small" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
            保存草稿
          </Button>
          <Button
            size="small"
            type="primary"
            icon={<CheckOutlined />}
            loading={submitting}
            onClick={handleSubmit}
            style={{ background: '#059669', borderColor: '#059669' }}
          >
            签发
          </Button>
        </div>
      )}
    </div>
  )
}
