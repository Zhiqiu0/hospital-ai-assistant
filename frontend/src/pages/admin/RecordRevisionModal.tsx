/** 管理员留痕修订：正文诊断核对通过后，连同修订理由一次提交。 */
import { useEffect, useRef, useState } from 'react'
import { Alert, Input, Modal, Space, Tag, Typography } from 'antd'
import api from '@/services/api'
import { message } from '@/services/messageBridge'
import { RECORD_TYPE_LABEL } from '@/utils/recordExport'
import DiagnosisConfirmation from '@/components/workbench/DiagnosisConfirmation'
import { useDiagnosisConfirmation } from '@/hooks/useDiagnosisConfirmation'

interface Props {
  record: { id: string; record_type: string; content?: string; patient_name?: string }
  onClose: () => void
  onSaved: () => void
}

export default function RecordRevisionModal({ record, onClose, onSaved }: Props) {
  const [content, setContent] = useState(record.content || '')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const submitting = useRef(false)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const diagnosis = useDiagnosisConfirmation({
    open: true,
    content,
    recordType: record.record_type,
    recordId: record.id,
  })
  const canSubmit = !!content.trim() && !!reason.trim() && diagnosis.canSubmit && !saving

  const submit = async () => {
    // 不以按钮 disabled 代替处理器守卫，双击和过期回调都不能重复提交。
    if (!canSubmit || submitting.current) return
    submitting.current = true
    setSaving(true)
    try {
      await api.post(`/admin/records/${record.id}/revise`, {
        content,
        revise_reason: reason.trim(),
        confirmed_diagnoses: diagnosis.diagnoses,
      })
      if (!mounted.current) return
      message.success('病历已修订，原版本保留供审计')
      onSaved()
      onClose()
    } catch (error) {
      if (mounted.current) {
        const detail = (error as { detail?: unknown })?.detail
        message.error(typeof detail === 'string' ? detail : '修订失败，请重试')
      }
    } finally {
      submitting.current = false
      if (mounted.current) setSaving(false)
    }
  }

  return (
    <Modal
      open
      title={
        <Space>
          <span>修订病历</span>
          <Tag>{record.patient_name}</Tag>
          <Tag color="blue">{RECORD_TYPE_LABEL[record.record_type] || record.record_type}</Tag>
        </Space>
      }
      onCancel={saving ? undefined : onClose}
      closable={!saving}
      maskClosable={!saving}
      keyboard={!saving}
      okText="确认修订并留痕"
      cancelText="取消"
      onOk={submit}
      width={760}
      okButtonProps={{ loading: saving, disabled: !canSubmit, danger: true }}
      cancelButtonProps={{ disabled: saving }}
    >
      <Alert
        type="warning"
        message="已签发病历的修订会创建新版本，原版本永久保留；操作人、时间与修订理由均会记录。"
      />
      {saving && <Alert type="info" message="修订已提交，请等待处理结果。" />}
      <div style={{ margin: '12px 0' }}>
        <Typography.Text strong>
          修订理由 <Typography.Text type="danger">*</Typography.Text>
        </Typography.Text>
        <Input.TextArea
          value={reason}
          onChange={event => setReason(event.target.value)}
          disabled={saving}
          rows={2}
          placeholder="请说明本次修订原因（如：医生提交后发现 XX 字段有误，需更正）"
          maxLength={500}
          showCount
        />
      </div>
      <Typography.Text strong>病历正文（修订后）</Typography.Text>
      <Input.TextArea
        value={content}
        onChange={event => setContent(event.target.value)}
        disabled={saving}
        aria-label="病历正文（修订后）"
        rows={16}
        style={{ marginTop: 6, fontSize: 13, lineHeight: 1.8 }}
      />
      <DiagnosisConfirmation state={diagnosis} disabled={saving} />
    </Modal>
  )
}
