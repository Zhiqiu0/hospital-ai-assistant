/**
 * 签发病历弹窗（components/workbench/FinalRecordModal.tsx）
 *
 * 医生完成病历后点击「签发」时弹出的确认对话框，执行最终提交流程：
 *   1. 展示当前病历内容供最后核查
 *   2. 检查 blockingIssues > 0 时显示红色警告（有必须修复项）
 *   3. 医生确认后调用 POST /medical-records/{id}/submit
 *   4. 提交成功后 setFinal(true) 锁定工作台，阻止进一步编辑
 *
 * 签发选项：
 *   - record_type: 门诊/急诊/住院（Radio 选择）
 *   - with_qc_override: 管理员可强制签发（Checkbox，有 blockingIssues 时才出现）
 *
 * 防止误操作：
 *   存在必须修复项且未勾选 override 时，提交按钮 disabled。
 */
import { useState } from 'react'
import { Button, Modal, Alert, Input, Space, Typography, Checkbox, Radio, message } from 'antd'
import { CheckOutlined } from '@ant-design/icons'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { useQCStore } from '@/store/qcStore'
import {
  useActiveEncounterStore,
  setCurrentEncounterFromPatient,
} from '@/store/activeEncounterStore'
import api from '@/services/api'

const { Text } = Typography

interface FinalRecordModalProps {
  open: boolean
  onCancel: () => void
}

export default function FinalRecordModal({ open, onCancel }: FinalRecordModalProps) {
  const { qcPass, qcIssues, gradeScore } = useQCStore()
  const { recordContent, recordType } = useRecordStore()
  const inquiry = useInquiryStore(s => s.inquiry)
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)

  const [confirmed, setConfirmed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [patientName, setPatientName] = useState('')
  const [patientGender, setPatientGender] = useState('')
  const [patientAge, setPatientAge] = useState('')

  const handleClose = () => {
    setConfirmed(false)
    setPatientName('')
    setPatientGender('')
    setPatientAge('')
    onCancel()
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      let encounterId = useActiveEncounterStore.getState().encounterId
      const inferredVisitType = recordType === 'outpatient' ? 'outpatient' : 'inpatient'

      if (!encounterId) {
        const pName =
          patientName.trim() || inquiry.chief_complaint.slice(0, 6) + '患者' || '未知患者'
        const res: any = await api.post('/encounters/quick-start', {
          patient_name: pName,
          gender: patientGender || 'unknown',
          age: patientAge.trim() ? parseInt(patientAge.trim()) : undefined,
          visit_type: inferredVisitType,
        })
        const newEncounterId: string = res.encounter_id
        encounterId = newEncounterId
        // 通过聚合 helper 一次性 upsert 到 patientCacheStore + setActive 到指针 store
        setCurrentEncounterFromPatient(res.patient, newEncounterId, {
          visitType: inferredVisitType as 'outpatient' | 'emergency' | 'inpatient',
        })
      }

      await api.post('/medical-records/quick-save', {
        encounter_id: encounterId,
        record_type: recordType,
        content: recordContent,
      })

      // 标记本地 isFinal=true：编辑器只读、auto-save 停摆，但接诊上下文保留
      // 不再 resetAllWorkbench——A 方案下转住院要求"先签发"，签发后立刻 reset
      // 会让医生失去转住院入口，形成"必须先签发→签发就清空→无法转住院"死循环。
      // 让医生显式选择下一步动作（转住院 / 新建接诊 / 登出），各动作自带 reset。
      useRecordStore.getState().setFinal(true)
      message.success('病历已签发，可继续转住院或开始下一位接诊')
      handleClose()
    } catch (e: any) {
      message.error('保存失败：' + (e?.detail || '请重试'))
    } finally {
      setSaving(false)
    }
  }

  const canSubmit =
    confirmed &&
    !saving &&
    qcPass !== false &&
    (!!currentEncounterId || (!!patientName.trim() && !!patientGender && !!patientAge.trim()))

  return (
    <Modal
      title="出具最终病历"
      width={720}
      open={open}
      onCancel={handleClose}
      footer={[
        <Button key="cancel" onClick={handleClose}>
          取消
        </Button>,
        <Button
          key="confirm"
          type="primary"
          disabled={!canSubmit}
          loading={saving}
          icon={<CheckOutlined />}
          onClick={handleSave}
        >
          确认签发
        </Button>,
      ]}
    >
      {/* QC status */}
      {qcPass === false ? (
        <Alert
          type="error"
          showIcon
          message={`结构检查未通过，无法正式提交${gradeScore ? `（${gradeScore.grade_score} 分，${gradeScore.grade_level}）` : ''}`}
          description="请修复右侧质控提示中标注「必须修复」的所有问题后重新质控。"
          style={{ marginBottom: 4 }}
        />
      ) : qcPass === true || (qcIssues.length === 0 && qcPass !== null) ? (
        <Alert
          type="success"
          showIcon
          message="病历质控通过，可以签发"
          style={{ marginBottom: 4 }}
        />
      ) : (
        <Alert
          type="info"
          showIcon
          message="尚未进行质控检查，建议先运行 AI 质控"
          style={{ marginBottom: 4 }}
        />
      )}

      {/* Patient info — only when no encounter */}
      {!currentEncounterId && (
        <div
          style={{
            margin: '10px 0 4px',
            padding: '12px 14px',
            background: '#fffbeb',
            border: '1px solid #fde68a',
            borderRadius: 8,
          }}
        >
          <Text style={{ fontSize: 13, color: '#92400e', display: 'block', marginBottom: 10 }}>
            ⚠️ 未关联接诊记录，保存时将自动创建患者档案（以下信息必填）
          </Text>
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            <Input
              placeholder="患者姓名（必填）"
              value={patientName}
              onChange={e => setPatientName(e.target.value)}
              style={{ borderRadius: 6 }}
            />
            <div style={{ display: 'flex', gap: 8 }}>
              <div style={{ flex: 1 }}>
                <Text style={{ fontSize: 12, color: '#92400e', display: 'block', marginBottom: 4 }}>
                  性别（必填）
                </Text>
                <Radio.Group
                  value={patientGender}
                  onChange={e => setPatientGender(e.target.value)}
                  buttonStyle="solid"
                  size="small"
                >
                  <Radio.Button value="male">男</Radio.Button>
                  <Radio.Button value="female">女</Radio.Button>
                </Radio.Group>
              </div>
              <div style={{ flex: 1 }}>
                <Text style={{ fontSize: 12, color: '#92400e', display: 'block', marginBottom: 4 }}>
                  年龄（必填）
                </Text>
                <Input
                  placeholder="如：35"
                  value={patientAge}
                  onChange={e => setPatientAge(e.target.value.replace(/\D/g, ''))}
                  suffix="岁"
                  style={{ borderRadius: 6 }}
                />
              </div>
            </div>
          </Space>
        </div>
      )}

      {/* Record preview */}
      <div
        style={{
          background: 'var(--surface-2)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '20px 24px',
          maxHeight: 400,
          overflowY: 'auto',
          fontSize: 14,
          lineHeight: 1.9,
          whiteSpace: 'pre-wrap',
          margin: '16px 0',
          fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
          color: 'var(--text-1)',
        }}
      >
        {recordContent}
      </div>

      <Checkbox
        onChange={e => setConfirmed(e.target.checked)}
        checked={confirmed}
        style={{ marginTop: 8 }}
      >
        我已认真阅读以上病历内容，确认内容真实、完整，同意签发
      </Checkbox>
    </Modal>
  )
}
