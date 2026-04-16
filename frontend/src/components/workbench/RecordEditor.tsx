import { useRef, useState, useEffect } from 'react'
import { Button, Space, Typography, Input, Select, message, Spin, Tag, Modal } from 'antd'
import {
  ThunderboltOutlined,
  EditOutlined,
  SafetyOutlined,
  FileDoneOutlined,
  CheckOutlined,
  MedicineBoxOutlined,
  PrinterOutlined,
  FileWordOutlined,
  StopOutlined,
} from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import { useAuthStore } from '@/store/authStore'
import api from '@/services/api'
import { printRecord, exportWordDoc } from '@/utils/recordExport'
import FinalRecordModal from './FinalRecordModal'

const { Text } = Typography
const { TextArea } = Input

export default function RecordEditor() {
  const {
    inquiry,
    recordContent,
    recordType,
    isGenerating,
    isPolishing,
    isQCing,
    setRecordContent,
    setRecordType,
    setGenerating,
    setPolishing,
    setQCing,
    setQCResult,
    setInquiry,
    isFinal,
    finalizedAt,
    qcIssues,
    qcPass,
    gradeScore,
    currentPatient,
    currentEncounterId,
    pendingGenerate,
    setPendingGenerate,
  } = useWorkbenchStore()
  const { token } = useAuthStore()
  const abortRef = useRef<AbortController | null>(null)

  const [finalModalOpen, setFinalModalOpen] = useState(false)
  const [isSupplementing, setIsSupplementing] = useState(false)

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
        let obj: any
        try {
          obj = JSON.parse(line.slice(5).trim())
        } catch {
          continue
        }
        if (obj.type === 'chunk') onChunk(obj.text)
        else if (obj.type === 'error') throw new Error(obj.message || 'LLM_ERROR')
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
        case '主诉':
          result.chief_complaint = text
          break
        case '现病史':
          result.history_present_illness = text
          break
        case '既往史':
          result.past_history = text
          break
        case '过敏史':
          result.allergy_history = text
          break
        case '个人史':
          result.personal_history = text
          break
        case '月经史':
          result.menstrual_history = text
          break
        case '体格检查': {
          const filteredLines = text.split('\n').filter(line => {
            const trimmed = line.trim()
            return (
              !trimmed.match(/^(望诊|闻诊|切诊[··]?舌象|切诊[··]?脉象|舌象|脉象)[：:]/u) &&
              !trimmed.match(/^其余阳性体征[：:]/u)
            )
          })
          const physicalLine = text.split('\n').find(l => l.trim().match(/^其余阳性体征[：:]/u))
          const physicalContent = physicalLine
            ? physicalLine.replace(/^其余阳性体征[：:]\s*/u, '').trim()
            : ''
          result.physical_exam = [physicalContent, filteredLines.join('\n').trim()]
            .filter(Boolean)
            .join('\n')
            .trim()
          break
        }
        case '辅助检查':
          result.auxiliary_exam = text
          break
        case '初步诊断':
          result.initial_impression = text
          break
      }
    }
    if (Object.keys(result).length > 0) {
      setInquiry({ ...useWorkbenchStore.getState().inquiry, ...result })
    }
  }

  const _doGenerate = async () => {
    setGenerating(true)
    setRecordContent('')
    const { isFirstVisit, currentVisitType } = useWorkbenchStore.getState()
    try {
      await streamSSE(
        '/api/v1/ai/quick-generate',
        {
          ...inquiry,
          record_type: recordType,
          patient_name: currentPatient?.name || '',
          patient_gender: currentPatient?.gender || '',
          patient_age: currentPatient?.age != null ? String(currentPatient.age) : '',
          is_first_visit: isFirstVisit,
          visit_type_detail: currentVisitType,
          visit_time: inquiry.visit_time || '',
          onset_time: inquiry.onset_time || '',
        },
        text => setRecordContent(useWorkbenchStore.getState().recordContent + text)
      )
      syncGeneratedRecordToInquiry(useWorkbenchStore.getState().recordContent)
    } catch (e: any) {
      if (e.name !== 'AbortError') message.error('生成失败，请重试')
    } finally {
      setGenerating(false)
    }
  }

  const handleGenerate = async () => {
    if (!inquiry.chief_complaint) {
      message.warning('请先填写并保存主诉')
      return
    }
    const tcmMissing: string[] = []
    if (!recordContent.trim()) {
      if (!inquiry.tongue_coating?.trim()) tcmMissing.push('舌象')
      if (!inquiry.pulse_condition?.trim()) tcmMissing.push('脉象')
      if (!inquiry.tcm_disease_diagnosis?.trim()) tcmMissing.push('中医疾病诊断')
      if (!inquiry.tcm_syndrome_diagnosis?.trim()) tcmMissing.push('中医证候诊断')
      if (!inquiry.treatment_method?.trim()) tcmMissing.push('治则治法')
    }
    if (tcmMissing.length > 0) {
      Modal.confirm({
        title: '中医必填字段未填写',
        content: `以下字段为空，AI将无法生成有效内容，病历中会出现"[未填写，需补充]"占位符：\n\n${tcmMissing.map(f => `• ${f}`).join('\n')}\n\n建议先在左侧填写完整后再生成，或确认继续生成后手动补充。`,
        okText: '继续生成',
        cancelText: '返回填写',
        onOk: _doGenerate,
      })
      return
    }
    _doGenerate()
  }

  const handlePolish = async () => {
    if (!recordContent.trim()) {
      message.warning('病历内容为空，无法润色')
      return
    }
    setPolishing(true)
    const original = recordContent
    setRecordContent('')
    try {
      await streamSSE('/api/v1/ai/quick-polish', { content: original }, text =>
        setRecordContent(useWorkbenchStore.getState().recordContent + text)
      )
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        message.error('润色失败，请重试')
        setRecordContent(original)
      }
    } finally {
      setPolishing(false)
    }
  }

  const handleQC = async (contentOverride?: string) => {
    const qcContent = contentOverride ?? useWorkbenchStore.getState().recordContent
    if (!qcContent.trim()) {
      message.warning('病历内容为空，无法质控')
      return
    }
    setQCing(true)
    try {
      const result: any = await api.post('/ai/quick-qc', {
        content: qcContent,
        record_type: recordType,
        chief_complaint: inquiry.chief_complaint || '',
        history_present_illness: inquiry.history_present_illness || '',
        past_history: inquiry.past_history || '',
        allergy_history: inquiry.allergy_history || '',
        physical_exam: inquiry.physical_exam || '',
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
        tcm_inspection: inquiry.tcm_inspection || '',
        tcm_auscultation: inquiry.tcm_auscultation || '',
        tongue_coating: inquiry.tongue_coating || '',
        pulse_condition: inquiry.pulse_condition || '',
        tcm_disease_diagnosis: inquiry.tcm_disease_diagnosis || '',
        tcm_syndrome_diagnosis: inquiry.tcm_syndrome_diagnosis || '',
        treatment_method: inquiry.treatment_method || '',
        treatment_plan: inquiry.treatment_plan || '',
        followup_advice: inquiry.followup_advice || '',
        is_first_visit: useWorkbenchStore.getState().isFirstVisit,
        onset_time: inquiry.onset_time || '',
        encounter_id: currentEncounterId || undefined,
      })
      const gradeScoreResult =
        result.grade_score != null
          ? {
              grade_score: result.grade_score,
              grade_level: result.grade_level,
              strengths: result.strengths,
            }
          : null
      setQCResult(result.issues || [], result.summary || '', result.pass ?? false, gradeScoreResult)
      if (result.grade_level === '甲级') {
        message.success(`质控通过！预估评分 ${result.grade_score} 分，达到甲级病历标准`)
      } else if (result.grade_score != null) {
        message.warning(
          `预估评分 ${result.grade_score} 分（${result.grade_level}），发现 ${(result.issues || []).length} 个问题，请查看右侧质控提示`
        )
      } else if (result.pass) {
        message.success('质控通过！')
      } else {
        message.warning(`发现 ${(result.issues || []).length} 个问题，请查看右侧质控提示`)
      }
    } catch {
      message.error('质控失败，请重试')
    } finally {
      setQCing(false)
    }
  }

  const handleSupplement = async () => {
    if (!qcIssues.length) {
      message.warning('请先执行 AI 质控')
      return
    }
    setIsSupplementing(true)
    const original = recordContent
    setRecordContent('')
    try {
      await streamSSE(
        '/api/v1/ai/quick-supplement',
        {
          current_content: original,
          qc_issues: qcIssues,
          ...inquiry,
          record_type: recordType,
          patient_name: currentPatient?.name || '',
          patient_gender: currentPatient?.gender || '',
          patient_age: currentPatient?.age != null ? String(currentPatient.age) : '',
        },
        text => setRecordContent(useWorkbenchStore.getState().recordContent + text)
      )
      const newContent = useWorkbenchStore.getState().recordContent
      message.success('补全完成，正在重新质控...')
      setIsSupplementing(false)
      await handleQC(newContent)
      return
    } catch (e: any) {
      if (e.name === 'AbortError') return
      setRecordContent(original)
      const msg = e?.message || ''
      if (
        msg.includes('context_length_exceeded') ||
        msg.includes('maximum context length') ||
        msg.includes('too many tokens')
      ) {
        message.error('病历内容超出AI处理上限，请联系管理员或手动分段修改')
      } else {
        message.error('补全失败，请重试')
      }
    } finally {
      setIsSupplementing(false)
    }
  }

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    if (pendingGenerate) {
      setPendingGenerate(false)
      handleGenerate()
    }
  }, [pendingGenerate])

  const isBusy = isGenerating || isPolishing || isQCing || isSupplementing
  const busyText = isGenerating
    ? 'AI 生成中...'
    : isPolishing
      ? 'AI 润色中...'
      : isSupplementing
        ? 'AI 补全中...'
        : 'AI 质控中...'

  return (
    <div
      style={{
        height: '100%',
        background: '#fff',
        borderRadius: 12,
        border: '1px solid var(--border)',
        boxShadow: 'var(--shadow-sm)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 14px',
          borderBottom: '1px solid var(--border-subtle)',
          background: 'var(--surface-2)',
          flexShrink: 0,
          gap: 8,
        }}
      >
        <Space size={8} style={{ flexShrink: 0 }}>
          <Text
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: 'var(--text-1)',
              letterSpacing: '-0.2px',
            }}
          >
            病历草稿
          </Text>
          {isFinal && finalizedAt && (
            <Tag color="success" style={{ margin: 0 }}>
              已签发 · {finalizedAt}
            </Tag>
          )}
          <Select
            value={recordType}
            onChange={setRecordType}
            size="small"
            style={{ width: 120 }}
            options={[
              { value: 'outpatient', label: '门诊病历' },
              {
                label: '─── 住院病历 ───',
                options: [
                  { value: 'admission_note', label: '入院记录' },
                  { value: 'first_course_record', label: '首次病程' },
                  { value: 'course_record', label: '日常病程' },
                  { value: 'senior_round', label: '上级查房' },
                  { value: 'pre_op_summary', label: '术前小结' },
                  { value: 'op_record', label: '手术记录' },
                  { value: 'post_op_record', label: '术后病程' },
                  { value: 'discharge_record', label: '出院记录' },
                ],
              },
            ]}
          />
        </Space>

        <Space size={4}>
          <Button
            icon={<ThunderboltOutlined />}
            type="primary"
            size="small"
            loading={isGenerating}
            onClick={handleGenerate}
            disabled={isFinal || !!recordContent.trim()}
            style={{
              borderRadius: 8,
              fontWeight: 600,
              fontSize: 13,
              height: 30,
              paddingInline: 14,
              ...(isFinal || recordContent.trim()
                ? {}
                : {
                    background: 'linear-gradient(135deg, #1d4ed8, #3b82f6)',
                    border: 'none',
                    boxShadow: '0 2px 8px rgba(37,99,235,0.35)',
                  }),
            }}
          >
            一键生成
          </Button>

          <Button
            icon={<EditOutlined />}
            size="small"
            loading={isPolishing}
            onClick={handlePolish}
            disabled={isFinal || !recordContent.trim()}
            style={{ borderRadius: 8, fontSize: 12, height: 30 }}
          >
            润色
          </Button>

          <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 2px' }} />

          <Button
            icon={<SafetyOutlined />}
            size="small"
            loading={isQCing}
            onClick={() => handleQC()}
            disabled={isFinal}
            style={{
              borderRadius: 8,
              fontSize: 12,
              height: 30,
              ...(isFinal
                ? {}
                : { color: '#dc2626', borderColor: '#fca5a5', background: '#fff5f5' }),
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
                borderRadius: 8,
                fontSize: 12,
                height: 30,
                color: '#92400e',
                borderColor: '#fcd34d',
                background: '#fffbeb',
              }}
            >
              补全缺失项
            </Button>
          )}

          <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 2px' }} />

          <Button
            icon={qcPass === false ? <StopOutlined /> : <FileDoneOutlined />}
            size="small"
            disabled={!recordContent.trim()}
            onClick={() => {
              if (qcPass === false) {
                Modal.warning({
                  title: `结构检查未通过，无法提交${gradeScore?.grade_score != null ? `（当前 ${gradeScore.grade_score} 分）` : ''}`,
                  content:
                    '请修复右侧质控提示中标注「必须修复」的所有结构性问题后重新质控，通过后方可出具正式病历。',
                  okText: '知道了，去修改',
                  width: 460,
                })
                return
              }
              setFinalModalOpen(true)
            }}
            style={{
              borderRadius: 8,
              fontSize: 12,
              height: 30,
              color: qcPass === false ? '#dc2626' : '#065f46',
              borderColor: qcPass === false ? '#fca5a5' : '#6ee7b7',
              background: qcPass === false ? '#fff5f5' : '#f0fdf4',
            }}
          >
            {qcPass === false
              ? `结构未通过${gradeScore ? `(${gradeScore.grade_score}分)` : ''}`
              : '出具最终病历'}
          </Button>

          <Button
            icon={<FileWordOutlined />}
            size="small"
            disabled={!recordContent.trim()}
            onClick={() => exportWordDoc(recordContent, currentPatient, recordType, finalizedAt)}
            style={{ borderRadius: 8, fontSize: 12, height: 30 }}
          >
            导出 Word
          </Button>
        </Space>
      </div>

      {/* Status bar */}
      {isBusy ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '7px 16px',
            flexShrink: 0,
            background: 'linear-gradient(90deg, #eff6ff, #f0f9ff)',
            borderBottom: '1px solid #bfdbfe',
            color: '#1d4ed8',
            fontSize: 12,
            fontWeight: 500,
          }}
        >
          <Spin size="small" />
          <span>{busyText}</span>
        </div>
      ) : isFinal ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '6px 16px',
            flexShrink: 0,
            background: '#f0fdf4',
            borderBottom: '1px solid #bbf7d0',
          }}
        >
          <Space size={6}>
            <CheckOutlined style={{ fontSize: 12, color: '#065f46' }} />
            <span style={{ color: '#065f46', fontSize: 12, fontWeight: 500 }}>
              病历已签发，不可修改
            </span>
          </Space>
          <Button
            size="small"
            icon={<PrinterOutlined />}
            onClick={() => printRecord(recordContent, currentPatient, recordType, finalizedAt)}
            style={{
              borderRadius: 6,
              fontSize: 12,
              height: 26,
              color: '#065f46',
              borderColor: '#86efac',
              background: '#fff',
            }}
          >
            打印
          </Button>
        </div>
      ) : (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: '3px 14px',
            flexShrink: 0,
            borderBottom: '1px solid var(--border-subtle)',
            color: '#b0bec5',
            fontSize: 11,
          }}
        >
          <span>AI 生成内容仅供参考，请医生审核后使用</span>
        </div>
      )}

      {/* Editor */}
      <TextArea
        value={recordContent}
        onChange={e => setRecordContent(e.target.value)}
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

      <FinalRecordModal open={finalModalOpen} onCancel={() => setFinalModalOpen(false)} />
    </div>
  )
}
