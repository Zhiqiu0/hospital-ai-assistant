/**
 * 病历编辑器组件（components/workbench/RecordEditor.tsx）
 *
 * 工作台核心区域，提供病历的完整编辑和操作流程：
 *   - AI 生成：调用 POST /ai/quick-generate，SSE 流式接收并实时更新编辑区
 *   - AI 续写：调用 POST /ai/quick-continue，补全未完成部分
 *   - AI 润色：调用 POST /ai/quick-polish，去重/规范化/口语转书面语
 *   - AI 质控：调用 POST /ai/quick-qc，SSE 流式接收规则+LLM双重质控结果
 *   - 签发病历：调用 POST /medical-records/quick-save，保存并锁定
 *   - 打印/导出 Word：调用 utils/recordExport 工具函数
 *
 * 状态来源：全部从 useWorkbenchStore 读写（recordContent/isGenerating/isQCing 等）
 * 签发后 isFinal=true，编辑区变为只读，按钮替换为打印/导出。
 *
 * SSE 流处理（EventSource API）：
 *   - 收到 chunk 事件：追加文本到 recordContent
 *   - 收到 rule_issues/llm_issues 事件：更新 qcIssues
 *   - 收到 done/error 事件：关闭流，更新加载状态
 */
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
    isQCStale,
    setRecordContent,
    setRecordType,
    setGenerating,
    setPolishing,
    setQCing,
    setQCResult,
    appendQCIssues,
    setQCSummary,
    setQCLlmLoading,
    startQCRun,
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

  /**
   * 从病历文本中提取所有章节，返回 Map<章节标题, 该章节完整文本（含标题）>。
   * 用于润色后的章节完整性校验。
   */
  const extractSections = (text: string): Map<string, string> => {
    const map = new Map<string, string>()
    const pattern = /【[^】]+】/g
    const matches: Array<{ header: string; index: number }> = []
    let m: RegExpExecArray | null
    while ((m = pattern.exec(text)) !== null) {
      matches.push({ header: m[0], index: m.index })
    }
    for (let i = 0; i < matches.length; i++) {
      const start = matches[i].index
      const end = i + 1 < matches.length ? matches[i + 1].index : text.length
      map.set(matches[i].header, text.slice(start, end).trimEnd())
    }
    return map
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

      // ── 章节完整性守卫 ──────────────────────────────────────────
      // LLM 可能无视"禁止删除"指令而遗漏章节，此处程序化补回，不依赖 prompt 约束。
      const polished = useWorkbenchStore.getState().recordContent
      const originalSections = extractSections(original)
      const polishedSections = extractSections(polished)

      const missing: string[] = []
      let restored = polished
      for (const [header, sectionText] of originalSections) {
        if (!polishedSections.has(header)) {
          missing.push(header)
          restored = restored.trimEnd() + '\n\n' + sectionText
        }
      }

      if (missing.length > 0) {
        setRecordContent(restored)
        message.warning(`润色完成，但 AI 误删了 ${missing.join('、')}，已自动还原`)
      }
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
    startQCRun()

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      const res = await fetch('/api/v1/ai/quick-qc', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          content: qcContent,
          record_type: recordType,
          patient_gender: currentPatient?.gender || '',
          is_first_visit: useWorkbenchStore.getState().isFirstVisit,
          encounter_id: currentEncounterId || undefined,
        }),
        signal: ctrl.signal,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let finalData: any = null

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
          if (obj.type === 'rule_issues') {
            const gs =
              obj.grade_score != null
                ? { grade_score: obj.grade_score, grade_level: obj.grade_level }
                : null
            setQCResult(obj.issues || [], '', obj.pass ?? false, gs)
            setQCLlmLoading(true)
          } else if (obj.type === 'llm_issues') {
            appendQCIssues(obj.issues || [])
          } else if (obj.type === 'done') {
            finalData = obj
            setQCSummary(obj.summary || '')
            setQCLlmLoading(false)
          } else if (obj.type === 'error') {
            throw new Error(obj.message || 'QC_ERROR')
          }
        }
      }

      if (finalData) {
        const totalIssues = useWorkbenchStore.getState().qcIssues.length
        if (finalData.grade_level === '甲级') {
          message.success(`质控通过！预估评分 ${finalData.grade_score} 分，达到甲级病历标准`)
        } else if (finalData.grade_score != null) {
          message.warning(
            `预估评分 ${finalData.grade_score} 分（${finalData.grade_level}），发现 ${totalIssues} 个问题，请查看右侧质控提示`
          )
        } else if (finalData.pass) {
          message.success('质控通过！')
        } else {
          message.warning(`发现 ${totalIssues} 个问题，请查看右侧质控提示`)
        }
      }
    } catch (e: any) {
      if (e.name !== 'AbortError') message.error('质控失败，请重试')
      setQCLlmLoading(false)
    } finally {
      setQCing(false)
      setQCLlmLoading(false)
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
            disabled={isFinal || !recordContent.trim() || isBusy}
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
            disabled={isFinal || isBusy}
            style={{
              borderRadius: 8,
              fontSize: 12,
              height: 30,
              // 病历改动后变为橙色提示重新质控
              ...(isFinal
                ? {}
                : isQCStale
                  ? { color: '#d97706', borderColor: '#fcd34d', background: '#fffbeb' }
                  : { color: '#dc2626', borderColor: '#fca5a5', background: '#fff5f5' }),
            }}
          >
            {isQCStale ? '重新质控' : 'AI质控'}
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
