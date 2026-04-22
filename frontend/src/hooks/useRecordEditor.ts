/**
 * 病历编辑器逻辑（hooks/useRecordEditor.ts）
 * 从 RecordEditor 提取的业务逻辑 hook，包含所有 AI 操作和 SSE 流处理。
 */
import { useRef, useState, useEffect } from 'react'
import { message, Modal } from 'antd'
import { useWorkbenchStore } from '@/store/workbenchStore'
import { useAuthStore } from '@/store/authStore'
import { usePatientCacheStore } from '@/store/patientCacheStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { PROFILE_FIELD_KEYS } from '@/domain/medical'

export function useRecordEditor() {
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
    previousRecordContent,
  } = useWorkbenchStore()
  const { token } = useAuthStore()
  const abortRef = useRef<AbortController | null>(null)

  const [finalModalOpen, setFinalModalOpen] = useState(false)
  const [isSupplementing, setIsSupplementing] = useState(false)

  // 通用 SSE 流请求，逐块回调 onChunk
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
        // 既往/过敏/个人/月经史 不再回写 inquiry：这些字段属于 PatientProfile，
        // 由 PatientProfileCard 单独维护，避免 AI 单次生成覆盖患者纵向档案
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

  // 病程类病历生成前，从后端拉取最新病历作为参考（pull-forward 机制）
  const fetchLatestRecord = async (): Promise<string | undefined> => {
    const { currentEncounterId } = useWorkbenchStore.getState()
    if (!currentEncounterId) return undefined
    try {
      const res = await fetch(
        `/api/v1/medical-records?encounter_id=${currentEncounterId}&limit=1`,
        { headers: { Authorization: `Bearer ${token}` } }
      )
      if (!res.ok) return undefined
      const data = await res.json()
      const items = data.items || data
      if (!Array.isArray(items) || items.length === 0) return undefined
      return items[0]?.content || undefined
    } catch {
      return undefined
    }
  }

  const _doGenerate = async () => {
    setGenerating(true)
    setRecordContent('')
    const { isFirstVisit, currentVisitType } = useWorkbenchStore.getState()

    // 病程记录类型需要注入上一份病历作为 AI 上下文（pull-forward）
    const isCourseType = [
      'first_course_record',
      'course_record',
      'senior_round',
      'pre_op_summary',
      'post_op_record',
      'discharge_record',
    ].includes(recordType)
    let previousRecord = previousRecordContent || undefined
    if (isCourseType && !previousRecord) {
      previousRecord = await fetchLatestRecord()
    }

    // 1.6 起 8 个 profile 字段已迁出 inquiry，但后端 prompt 仍然需要它们：
    // 这里从 patientCacheStore 读取并合并到 payload。profile 是权威源，
    // 同名字段会覆盖 inquiry 中可能残留的旧值。
    const activePatientId = useActiveEncounterStore.getState().patientId
    const profile = activePatientId
      ? usePatientCacheStore.getState().getProfile(activePatientId)
      : null
    const profilePayload: Record<string, string> = {}
    if (profile) {
      for (const key of PROFILE_FIELD_KEYS) {
        const v = profile[key]
        if (v) profilePayload[key] = String(v)
      }
    }

    try {
      await streamSSE(
        '/api/v1/ai/quick-generate',
        {
          ...inquiry,
          ...profilePayload,
          record_type: recordType,
          patient_name: currentPatient?.name || '',
          patient_gender: currentPatient?.gender || '',
          patient_age: currentPatient?.age != null ? String(currentPatient.age) : '',
          is_first_visit: isFirstVisit,
          visit_type_detail: currentVisitType,
          visit_time: inquiry.visit_time || '',
          onset_time: inquiry.onset_time || '',
          // 复诊或病程记录传入上次病历全文，AI 据此保持稳定信息并生成变化对比
          previous_record: previousRecord,
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
        content: `以下字段为空，AI将无法生成有效内容：\n\n${tcmMissing.map(f => `• ${f}`).join('\n')}\n\n建议先填写完整后再生成，或确认继续后手动补充。`,
        okText: '继续生成',
        cancelText: '返回填写',
        onOk: _doGenerate,
      })
      return
    }
    _doGenerate()
  }

  // 提取病历所有章节，返回 Map<标题, 完整段落文本>，用于润色后守卫章节完整性
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
      // 章节完整性守卫：LLM 可能误删章节，程序化补回
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

  // 组件卸载时中止当前请求
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  // 监听 pendingGenerate 标志，自动触发生成
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

  return {
    recordContent,
    setRecordContent,
    recordType,
    setRecordType,
    isGenerating,
    isPolishing,
    isQCing,
    isQCStale,
    isFinal,
    finalizedAt,
    qcIssues,
    qcPass,
    gradeScore,
    currentPatient,
    finalModalOpen,
    setFinalModalOpen,
    isSupplementing,
    isBusy,
    busyText,
    handleGenerate,
    handlePolish,
    handleQC,
    handleSupplement,
  }
}
