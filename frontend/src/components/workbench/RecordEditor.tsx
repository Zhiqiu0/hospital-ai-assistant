import { useRef, useState, useEffect } from 'react'
import { Button, Space, Typography, Input, Alert, Select, message, Spin, Tag, Modal, Checkbox, Radio, Dropdown } from 'antd'
import { ThunderboltOutlined, EditOutlined, SafetyOutlined, FileDoneOutlined, CheckOutlined, PlusOutlined, MedicineBoxOutlined, PrinterOutlined, EllipsisOutlined } from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import { useAuthStore } from '@/store/authStore'
import api from '@/services/api'

const { Text } = Typography
const { TextArea } = Input

const RECORD_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊病历', admission_note: '入院记录', first_course_record: '首次病程记录',
  course_record: '日常病程记录', senior_round: '上级查房记录', discharge_record: '出院记录',
  pre_op_summary: '术前小结', op_record: '手术记录', post_op_record: '术后病程记录',
}

function printRecord(content: string, patient: any, recordType: string, signedAt: string | null) {
  const patientDesc = patient
    ? [patient.name, patient.gender === 'male' ? '男' : patient.gender === 'female' ? '女' : '', patient.age ? `${patient.age}岁` : ''].filter(Boolean).join(' · ')
    : '未知患者'
  const typeLabel = RECORD_TYPE_LABEL[recordType] || recordType
  const formatted = content.replace(/\n/g, '<br>')
  const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>${typeLabel} - ${patientDesc}</title>
<style>
  body { font-family: 'PingFang SC','Microsoft YaHei',sans-serif; margin: 0; padding: 32px 48px; color: #1e293b; }
  h2 { text-align: center; font-size: 20px; margin-bottom: 4px; }
  .meta { text-align: center; font-size: 13px; color: #64748b; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 1px solid #e2e8f0; }
  .content { font-size: 14px; line-height: 2.0; white-space: pre-wrap; }
  .footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8; text-align: right; }
  @media print { body { padding: 20px 32px; } }
</style></head><body>
<h2>${typeLabel}</h2>
<div class="meta">${patientDesc}${signedAt ? `&nbsp;&nbsp;|&nbsp;&nbsp;签发时间：${signedAt}` : ''}</div>
<div class="content">${formatted}</div>
<div class="footer">MediScribe 智能病历系统 · 本病历由医生审核签发</div>
<script>window.onload = function() { window.print(); }<\/script>
</body></html>`
  const w = window.open('', '_blank')
  if (w) { w.document.write(html); w.document.close() }
}

export default function RecordEditor() {
  const {
    inquiry, recordContent, recordType,
    isGenerating, isPolishing, isQCing,
    setRecordContent, setRecordType,
    setGenerating, setPolishing, setQCing, setQCResult,
    setInquiry,
    isFinal, finalizedAt, reset,
    qcIssues, qcPass,
    currentPatient, currentEncounterId,
    pendingGenerate, setPendingGenerate,
  } = useWorkbenchStore()
  const { token } = useAuthStore()
  const abortRef = useRef<AbortController | null>(null)

  const [generateConfirmOpen, setGenerateConfirmOpen] = useState(false)
  const [finalModalOpen, setFinalModalOpen] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [isContinuing, setIsContinuing] = useState(false)
  const [isSupplementing, setIsSupplementing] = useState(false)
  const [patientNameInput, setPatientNameInput] = useState('')
  const [patientGenderInput, setPatientGenderInput] = useState('')
  const [patientAgeInput, setPatientAgeInput] = useState('')

  const streamSSE = async (url: string, body: object, onChunk: (text: string) => void) => {
    const ctrl = new AbortController()
    abortRef.current = ctrl
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        try {
          const obj = JSON.parse(line.slice(5).trim())
          if (obj.type === 'chunk') onChunk(obj.text)
        } catch { /* ignore */ }
      }
    }
  }

  // 生成完成后，把病历各段落解析回左侧问诊字段，确保左右一致
  const syncGeneratedRecordToInquiry = (content: string) => {
    const result: Record<string, string> = {}
    const pattern = /【([^】]+)】[^\S\n]*\n?([\s\S]*?)(?=\n【|$)/g
    let m: RegExpExecArray | null
    while ((m = pattern.exec(content)) !== null) {
      const text = m[2].trim()
      if (!text) continue
      switch (m[1]) {
        case '主诉': result.chief_complaint = text; break
        case '现病史': result.history_present_illness = text; break
        case '既往史': result.past_history = text; break
        case '过敏史': result.allergy_history = text; break
        case '个人史': result.personal_history = text; break
        case '月经史': result.menstrual_history = text; break
        case '体格检查': result.physical_exam = text; break
        case '辅助检查': result.auxiliary_exam = text; break
        case '初步诊断': result.initial_impression = text; break
      }
    }
    if (Object.keys(result).length > 0) {
      setInquiry({ ...useWorkbenchStore.getState().inquiry, ...result })
    }
  }

  const handleGenerate = async () => {
    if (!inquiry.chief_complaint) { message.warning('请先填写并保存主诉'); return }
    setGenerating(true)
    setRecordContent('')
    try {
      await streamSSE('/api/v1/ai/quick-generate', {
        ...inquiry,
        record_type: recordType,
        patient_name: currentPatient?.name || patientNameInput || '',
        patient_gender: currentPatient?.gender || patientGenderInput || '',
        patient_age: currentPatient?.age != null ? String(currentPatient.age) : patientAgeInput || '',
      }, (text) => setRecordContent(useWorkbenchStore.getState().recordContent + text))
      // 生成完成后同步回左侧字段
      syncGeneratedRecordToInquiry(useWorkbenchStore.getState().recordContent)
    } catch (e: any) {
      if (e.name !== 'AbortError') message.error('生成失败，请重试')
    } finally { setGenerating(false) }
  }

  // 组件卸载时中断正在进行的 SSE 请求
  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  // 问诊保存且病历为空时自动触发生成
  useEffect(() => {
    if (pendingGenerate) {
      setPendingGenerate(false)
      handleGenerate()
    }
  }, [pendingGenerate])

  const handlePolish = async () => {
    if (!recordContent.trim()) { message.warning('病历内容为空，无法润色'); return }
    setPolishing(true)
    const original = recordContent
    setRecordContent('')
    try {
      await streamSSE('/api/v1/ai/quick-polish', { content: original },
        (text) => setRecordContent(useWorkbenchStore.getState().recordContent + text)
      )
    } catch (e: any) {
      if (e.name !== 'AbortError') { message.error('润色失败，请重试'); setRecordContent(original) }
    } finally { setPolishing(false) }
  }

  const handleSupplement = async () => {
    if (!qcIssues.length) { message.warning('请先执行 AI 质控'); return }
    setIsSupplementing(true)
    const original = recordContent
    setRecordContent('')
    try {
      await streamSSE('/api/v1/ai/quick-supplement', {
        current_content: original,
        qc_issues: qcIssues,
        ...inquiry,
        record_type: recordType,
      }, (text) => setRecordContent(useWorkbenchStore.getState().recordContent + text))
      message.success('补全完成')
    } catch (e: any) {
      if (e.name !== 'AbortError') { message.error('补全失败，请重试'); setRecordContent(original) }
    } finally { setIsSupplementing(false) }
  }

  const handleContinue = async () => {
    if (!recordContent.trim()) { message.warning('请先输入部分病历内容，再使用续写'); return }
    setIsContinuing(true)
    const originalContent = recordContent
    setRecordContent(originalContent.trimEnd() + '\n\n')
    try {
      await streamSSE('/api/v1/ai/quick-continue', {
        current_content: originalContent,
        ...inquiry,
        record_type: recordType,
      }, (text) => setRecordContent(useWorkbenchStore.getState().recordContent + text))
    } catch (e: any) {
      if (e.name !== 'AbortError') message.error('续写失败，请重试')
    } finally { setIsContinuing(false) }
  }

  const handleQC = async () => {
    if (!recordContent.trim()) { message.warning('病历内容为空，无法质控'); return }
    setQCing(true)
    try {
      const result: any = await api.post('/ai/quick-qc', {
        content: recordContent,
        record_type: recordType,
        // 基础问诊字段
        chief_complaint: inquiry.chief_complaint || '',
        history_present_illness: inquiry.history_present_illness || '',
        past_history: inquiry.past_history || '',
        allergy_history: inquiry.allergy_history || '',
        physical_exam: inquiry.physical_exam || '',
        // 住院专项字段（用于规则引擎）
        marital_history: inquiry.marital_history || '',
        family_history: inquiry.family_history || '',
        pain_assessment: inquiry.pain_assessment || '',
        vte_risk: inquiry.vte_risk || '',
        nutrition_assessment: inquiry.nutrition_assessment || '',
        psychology_assessment: inquiry.psychology_assessment || '',
        rehabilitation_assessment: inquiry.rehabilitation_assessment || '',
        current_medications: inquiry.current_medications || '',
        religion_belief: inquiry.religion_belief || '',
        auxiliary_exam: inquiry.auxiliary_exam || '',
        admission_diagnosis: inquiry.admission_diagnosis || '',
        encounter_id: currentEncounterId || undefined,
      })
      const gradeScore = (result.grade_score != null)
        ? { grade_score: result.grade_score, grade_level: result.grade_level, strengths: result.strengths }
        : null
      setQCResult(result.issues || [], result.summary || '', result.pass ?? false, gradeScore)
      if (result.grade_level === '甲级') {
        message.success(`质控通过！预估评分 ${result.grade_score} 分，达到甲级病历标准`)
      } else if (result.grade_score != null) {
        message.warning(`预估评分 ${result.grade_score} 分（${result.grade_level}），发现 ${(result.issues || []).length} 个问题，请查看右侧质控提示`)
      } else if (result.pass) {
        message.success('质控通过！')
      } else {
        message.warning(`发现 ${(result.issues || []).length} 个问题，请查看右侧质控提示`)
      }
    } catch {
      message.error('质控失败，请重试')
    } finally { setQCing(false) }
  }

  const isBusy = isGenerating || isPolishing || isQCing || isContinuing || isSupplementing
  const busyText = isGenerating ? 'AI 生成中...' : isPolishing ? 'AI 润色中...' : isContinuing ? 'AI 续写中...' : isSupplementing ? 'AI 补全中...' : 'AI 质控中...'

  const highRiskCount = qcIssues.filter((i) => i.risk_level === 'high').length

  return (
    <div style={{
      height: '100%',
      background: '#fff',
      borderRadius: 12,
      border: '1px solid var(--border)',
      boxShadow: 'var(--shadow-sm)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* Toolbar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 14px',
        borderBottom: '1px solid var(--border-subtle)',
        background: 'var(--surface-2)',
        flexShrink: 0,
        gap: 8,
      }}>
        {/* Left: title + type selector */}
        <Space size={8} style={{ flexShrink: 0 }}>
          <Text style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)', letterSpacing: '-0.2px' }}>
            病历草稿
          </Text>
          {isFinal && finalizedAt && (
            <Tag color="success" style={{ margin: 0 }}>已签发 · {finalizedAt}</Tag>
          )}
          <Select
            value={recordType}
            onChange={setRecordType}
            size="small"
            style={{ width: 120 }}
            options={[
              { value: 'outpatient', label: '门诊病历' },
              { label: '─── 住院病历 ───', options: [
                { value: 'admission_note', label: '入院记录' },
                { value: 'first_course_record', label: '首次病程' },
                { value: 'course_record', label: '日常病程' },
                { value: 'senior_round', label: '上级查房' },
                { value: 'pre_op_summary', label: '术前小结' },
                { value: 'op_record', label: '手术记录' },
                { value: 'post_op_record', label: '术后病程' },
                { value: 'discharge_record', label: '出院记录' },
              ]},
            ]}
          />
        </Space>

        {/* Right: action buttons */}
        <Space size={4}>
          {/* Primary: 一键生成 */}
          <Button
            icon={<ThunderboltOutlined />}
            type="primary"
            size="small"
            loading={isGenerating}
            onClick={() => {
              if (!inquiry.chief_complaint) { message.warning('请先填写并保存主诉'); return }
              if (recordContent.trim()) {
                setGenerateConfirmOpen(true)
              } else {
                handleGenerate()
              }
            }}
            disabled={isFinal}
            style={{
              borderRadius: 8, fontWeight: 600, fontSize: 13, height: 30, paddingInline: 14,
              background: isFinal ? undefined : 'linear-gradient(135deg, #1d4ed8, #3b82f6)',
              border: isFinal ? undefined : 'none',
              boxShadow: isFinal ? undefined : '0 2px 8px rgba(37,99,235,0.35)',
            }}
          >
            一键生成
          </Button>

          {/* Separator */}
          <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 2px' }} />

          {/* Secondary actions: ··· dropdown */}
          <Dropdown
            disabled={isFinal}
            menu={{
              items: [
                {
                  key: 'continue',
                  icon: <PlusOutlined />,
                  label: '续写',
                  onClick: handleContinue,
                },
                {
                  key: 'polish',
                  icon: <EditOutlined />,
                  label: '润色',
                  onClick: handlePolish,
                },
              ],
            }}
            trigger={['click']}
          >
            <Button
              size="small"
              disabled={isFinal}
              loading={isContinuing || isPolishing}
              style={{ borderRadius: 8, fontSize: 12, height: 30 }}
            >
              更多 <EllipsisOutlined />
            </Button>
          </Dropdown>

          {/* Separator */}
          <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 2px' }} />

          <Button
            icon={<SafetyOutlined />}
            size="small"
            loading={isQCing}
            onClick={handleQC}
            disabled={isFinal}
            style={{
              borderRadius: 8, fontSize: 12, height: 30,
              color: isFinal ? undefined : '#dc2626',
              borderColor: isFinal ? undefined : '#fca5a5',
              background: isFinal ? undefined : '#fff5f5',
            }}
          >
            AI质控
          </Button>
          {qcIssues.length > 0 && !isFinal && (
            <Button
              icon={<MedicineBoxOutlined />}
              size="small"
              loading={isSupplementing}
              onClick={handleSupplement}
              style={{
                borderRadius: 8, fontSize: 12, height: 30,
                color: '#92400e', borderColor: '#fcd34d',
                background: '#fffbeb',
              }}
            >
              补全缺失项
            </Button>
          )}

          {/* Separator */}
          <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 2px' }} />

          <Button
            icon={<FileDoneOutlined />}
            size="small"
            disabled={!recordContent.trim()}
            onClick={() => { setConfirmed(false); setFinalModalOpen(true) }}
            style={{
              borderRadius: 8, fontSize: 12, height: 30,
              color: '#065f46', borderColor: '#6ee7b7',
              background: '#f0fdf4',
            }}
          >
            出具最终病历
          </Button>
        </Space>
      </div>

      {/* Status / busy bar */}
      {isBusy ? (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '7px 16px', flexShrink: 0,
          background: 'linear-gradient(90deg, #eff6ff, #f0f9ff)',
          borderBottom: '1px solid #bfdbfe',
          color: '#1d4ed8', fontSize: 12, fontWeight: 500,
        }}>
          <Spin size="small" />
          <span>{busyText}</span>
        </div>
      ) : isFinal ? (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '6px 16px', flexShrink: 0,
          background: '#f0fdf4', borderBottom: '1px solid #bbf7d0',
        }}>
          <Space size={6}>
            <CheckOutlined style={{ fontSize: 12, color: '#065f46' }} />
            <span style={{ color: '#065f46', fontSize: 12, fontWeight: 500 }}>病历已签发，不可修改</span>
          </Space>
          <Button
            size="small" icon={<PrinterOutlined />}
            onClick={() => printRecord(recordContent, currentPatient, recordType, finalizedAt)}
            style={{ borderRadius: 6, fontSize: 12, height: 26, color: '#065f46', borderColor: '#86efac', background: '#fff' }}
          >打印</Button>
        </div>
      ) : (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 4,
          padding: '3px 14px', flexShrink: 0,
          borderBottom: '1px solid var(--border-subtle)',
          color: '#b0bec5', fontSize: 11,
        }}>
          <span>AI 生成内容仅供参考，请医生审核后使用</span>
        </div>
      )}

      {/* Editor */}
      <TextArea
        value={recordContent}
        onChange={(e) => setRecordContent(e.target.value)}
        readOnly={isFinal}
        placeholder="填写左侧问诊信息后，点击「一键生成」自动生成病历草稿，或直接在此输入..."
        style={{
          flex: 1,
          fontSize: 14,
          lineHeight: 2.0,
          resize: 'none',
          border: 'none',
          outline: 'none',
          padding: '12px 16px',
          color: '#1e293b',
          background: isFinal ? '#f8fafc' : '#fff',
        }}
        variant="borderless"
      />

      {/* Generate overwrite confirmation modal */}
      <Modal
        title="覆盖现有内容？"
        open={generateConfirmOpen}
        onCancel={() => setGenerateConfirmOpen(false)}
        onOk={() => { setGenerateConfirmOpen(false); handleGenerate() }}
        okText="确认覆盖"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        width={380}
      >
        <p style={{ color: '#475569', fontSize: 14, margin: 0 }}>
          病历编辑区已有内容，点击「确认覆盖」将清空并重新生成，该操作不可撤销。
        </p>
      </Modal>

      {/* Final record modal */}
      <Modal
        title="出具最终病历"
        width={720}
        open={finalModalOpen}
        onCancel={() => { setFinalModalOpen(false); setConfirmed(false); setPatientNameInput(''); setPatientGenderInput(''); setPatientAgeInput('') }}
        footer={[
          <Button key="cancel" onClick={() => { setFinalModalOpen(false); setConfirmed(false); setPatientNameInput(''); setPatientGenderInput(''); setPatientAgeInput('') }}>
            取消
          </Button>,
          <Button
            key="confirm"
            type="primary"
            disabled={!confirmed || saving || (!currentEncounterId && (!patientNameInput.trim() || !patientGenderInput || !patientAgeInput.trim()))}
            loading={saving}
            icon={<CheckOutlined />}
            onClick={async () => {
              setSaving(true)
              try {
                let encounterId = useWorkbenchStore.getState().currentEncounterId

                const inferredVisitType = recordType === 'outpatient' ? 'outpatient' : 'inpatient'

                // If no encounter, create one first
                if (!encounterId) {
                  const pName = patientNameInput.trim() || inquiry.chief_complaint.slice(0, 6) + '患者' || '未知患者'
                  const res: any = await api.post('/encounters/quick-start', {
                    patient_name: pName,
                    gender: patientGenderInput || 'unknown',
                    age: patientAgeInput.trim() ? parseInt(patientAgeInput.trim()) : undefined,
                    visit_type: inferredVisitType,
                  })
                  encounterId = res.encounter_id
                  useWorkbenchStore.getState().setCurrentEncounter(
                    { id: res.patient.id, name: res.patient.name },
                    encounterId
                  )
                }

                await api.post('/medical-records/quick-save', {
                  encounter_id: encounterId,
                  record_type: recordType,
                  content: recordContent,
                })

                message.success('病历已签发，可在「历史病历」中查看或打印')
                setFinalModalOpen(false)
                reset()
                setConfirmed(false)
                setPatientNameInput('')
                setPatientGenderInput('')
                setPatientAgeInput('')
              } catch (e: any) {
                message.error('保存失败：' + (e?.detail || '请重试'))
              } finally {
                setSaving(false)
              }
            }}
          >
            确认签发
          </Button>,
        ]}
      >
        {/* QC status alert */}
        {qcPass === false && qcIssues.length > 0 ? (
          <Alert
            type="warning"
            showIcon
            message="病历存在质控问题，建议修复后签发"
            description={`共发现 ${qcIssues.length} 个质控问题${highRiskCount > 0 ? `，其中高风险问题 ${highRiskCount} 个` : ''}`}
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
          <div style={{
            margin: '10px 0 4px',
            padding: '12px 14px',
            background: '#fffbeb',
            border: '1px solid #fde68a',
            borderRadius: 8,
          }}>
            <Text style={{ fontSize: 13, color: '#92400e', display: 'block', marginBottom: 10 }}>
              ⚠️ 未关联接诊记录，保存时将自动创建患者档案（以下信息必填）
            </Text>
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <Input
                placeholder="患者姓名（必填）"
                value={patientNameInput}
                onChange={(e) => setPatientNameInput(e.target.value)}
                style={{ borderRadius: 6 }}
              />
              <div style={{ display: 'flex', gap: 8 }}>
                <div style={{ flex: 1 }}>
                  <Text style={{ fontSize: 12, color: '#92400e', display: 'block', marginBottom: 4 }}>性别（必填）</Text>
                  <Radio.Group
                    value={patientGenderInput}
                    onChange={(e) => setPatientGenderInput(e.target.value)}
                    buttonStyle="solid"
                    size="small"
                  >
                    <Radio.Button value="male">男</Radio.Button>
                    <Radio.Button value="female">女</Radio.Button>
                  </Radio.Group>
                </div>
                <div style={{ flex: 1 }}>
                  <Text style={{ fontSize: 12, color: '#92400e', display: 'block', marginBottom: 4 }}>年龄（必填）</Text>
                  <Input
                    placeholder="如：35"
                    value={patientAgeInput}
                    onChange={(e) => setPatientAgeInput(e.target.value.replace(/\D/g, ''))}
                    suffix="岁"
                    style={{ borderRadius: 6 }}
                  />
                </div>
              </div>
            </Space>
          </div>
        )}

        {/* Record preview */}
        <div style={{
          background: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: 8,
          padding: '20px 24px',
          maxHeight: 400,
          overflowY: 'auto',
          fontSize: 14,
          lineHeight: 1.9,
          whiteSpace: 'pre-wrap',
          margin: '16px 0',
          fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
          color: '#1e293b',
        }}>
          {recordContent}
        </div>

        {/* Confirmation checkbox */}
        <Checkbox
          onChange={(e) => setConfirmed(e.target.checked)}
          checked={confirmed}
          style={{ marginTop: 8 }}
        >
          我已认真阅读以上病历内容，确认内容真实、完整，同意签发
        </Checkbox>
      </Modal>
    </div>
  )
}
