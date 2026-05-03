/**
 * 取消接诊弹窗（components/workbench/CancelEncounterModal.tsx）
 *
 * 业务背景（2026-05-03 加）：
 *   之前系统没有"取消接诊"操作——上次接诊未签发就只能卡在 in_progress 状态，
 *   患者复诊判断也乱（"上次没签发也算复诊"）。Phase 1 加这个功能让接诊状态机
 *   闭环：in_progress → completed（签发/出院） / cancelled（医生主动取消）。
 *
 * 设计要点：
 *   - 取消理由必填（前端预设 5 选 + 自由备注）
 *   - 软取消：所有数据保留供回溯（inquiry/voice/AI 草稿/病历草稿都不删）
 *   - 已签发病历不可取消（后端会拒，前端不依赖此防御）
 *   - 二次确认：如果当前接诊已有数据（病历草稿 / 语音转写），弹窗顶部高亮提示
 */

import { useMemo, useState } from 'react'
import { Modal, Select, Input, Alert, Typography } from 'antd'
import { useRecordStore } from '@/store/recordStore'
import { useVoiceTranscriptStore } from '@/store/voiceTranscriptStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'

const { TextArea } = Input
const { Text } = Typography

/** 预设取消理由（A-E 拍板）；选"其他"时备注必填，前端 UI 校验，后端只确保非空 */
const PRESET_REASONS = [
  { value: '误开接诊', label: '误开接诊' },
  { value: '患者未到诊', label: '患者未到诊' },
  { value: '患者已转院', label: '患者已转院' },
  { value: '重复创建', label: '重复创建' },
  { value: '其他', label: '其他（请在备注说明）' },
] as const

interface Props {
  open: boolean
  onClose: () => void
  /** 取消提交回调，参数是组装好的最终 cancel_reason 文本（含备注） */
  onConfirm: (cancelReason: string) => Promise<void>
}

export default function CancelEncounterModal({ open, onClose, onConfirm }: Props) {
  const [reason, setReason] = useState<string>('')
  const [note, setNote] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)

  // 二次确认依据：当前接诊是否已有"实质数据"——
  // 病历草稿非空 / 语音转写非空（按当前 encounter slot 取）
  const recordContent = useRecordStore(s => s.recordContent)
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const voiceDraft = useMemo(() => {
    if (!currentEncounterId) return null
    return useVoiceTranscriptStore.getState().get(currentEncounterId)
  }, [currentEncounterId, open]) // open 变化时重新算（弹窗打开瞬间快照）

  const recordCharCount = recordContent.trim().length
  const voiceCharCount = voiceDraft?.transcript?.trim().length || 0
  const hasUnsavedData = recordCharCount > 0 || voiceCharCount > 0

  // "其他" 时备注必填；其他选项备注可选
  const isOtherReason = reason === '其他'
  const canSubmit = !!reason && (!isOtherReason || !!note.trim())

  const handleSubmit = async () => {
    if (!canSubmit) return
    // 拼最终 cancel_reason：选项 + （可选）备注
    const finalReason = note.trim() ? `${reason}：${note.trim()}` : reason
    setSubmitting(true)
    try {
      await onConfirm(finalReason)
      // 成功后清空本地态，外层负责关弹窗
      setReason('')
      setNote('')
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancel = () => {
    if (submitting) return
    setReason('')
    setNote('')
    onClose()
  }

  return (
    <Modal
      open={open}
      title="取消本次接诊"
      okText="确认取消"
      okButtonProps={{ danger: true, disabled: !canSubmit, loading: submitting }}
      cancelText="再想想"
      onOk={handleSubmit}
      onCancel={handleCancel}
      maskClosable={false}
      destroyOnClose
      width={520}
    >
      <Alert
        type="warning"
        showIcon
        message="取消后本次接诊作废，无法恢复"
        description={
          <>
            重新接诊会创建一条<b>新接诊（数据从空白开始）</b>。本次内容仅在「历史接诊
            记录」可查阅，不会带入新接诊。
            <br />
            <span style={{ color: 'var(--text-3)' }}>
              如只是想暂离稍后继续，<b>直接关闭浏览器或切到别的页面</b>
              即可，下次进入会自动续接当前接诊。
            </span>
          </>
        }
        style={{ marginBottom: 16 }}
      />

      {hasUnsavedData && (
        <Alert
          type="info"
          showIcon
          message="本接诊已有未签发数据"
          description={
            <span>
              {recordCharCount > 0 && (
                <span>
                  病历草稿 <Text strong>{recordCharCount}</Text> 字
                </span>
              )}
              {recordCharCount > 0 && voiceCharCount > 0 && '；'}
              {voiceCharCount > 0 && (
                <span>
                  语音转写 <Text strong>{voiceCharCount}</Text> 字
                </span>
              )}
              。取消后这些内容仍可在历史接诊里查到。
            </span>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      <div style={{ marginBottom: 12 }}>
        <Text style={{ fontSize: 13, fontWeight: 600 }}>
          取消理由 <Text type="danger">*</Text>
        </Text>
        <Select
          value={reason || undefined}
          onChange={setReason}
          options={[...PRESET_REASONS]}
          placeholder="请选择"
          style={{ width: '100%', marginTop: 6 }}
        />
      </div>

      <div>
        <Text style={{ fontSize: 13, fontWeight: 600 }}>
          备注{' '}
          {isOtherReason ? (
            <Text type="danger">*（选「其他」时必填）</Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>
              （可选）
            </Text>
          )}
        </Text>
        <TextArea
          value={note}
          onChange={e => setNote(e.target.value)}
          rows={3}
          placeholder="补充说明，便于日后回溯（最多 400 字）"
          maxLength={400}
          showCount
          style={{ marginTop: 6 }}
        />
      </div>
    </Modal>
  )
}
