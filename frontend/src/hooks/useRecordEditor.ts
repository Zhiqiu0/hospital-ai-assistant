/**
 * 病历编辑器逻辑（hooks/useRecordEditor.ts）
 *
 * 从 RecordEditor 抽离的业务 hook：负责 AI 生成 / 润色 / 质控 / 补全四个动作
 * 和章节守卫、SSE 流处理。SSE 通用代码已抽到 services/streamSSE.ts。
 */
import { useRef, useState, useEffect } from 'react'
import { message } from 'antd'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { useQCStore } from '@/store/qcStore'
import { useAuthStore } from '@/store/authStore'
import { usePatientCacheStore } from '@/store/patientCacheStore'
import { useActiveEncounterStore, useCurrentPatient } from '@/store/activeEncounterStore'
import {
  isCourseRecordType,
  pickInquiryByRecordType,
  type RecordType,
} from '@/store/inquiryFieldGroups'
import { PROFILE_FIELD_KEYS } from '@/domain/medical'
import { streamSSE } from '@/services/streamSSE'
import { parseGeneratedSectionsToInquiry, restoreMissingSections } from '@/utils/recordSections'

export function useRecordEditor() {
  // 各域字段从对应子 store 取
  const { inquiry, setInquiry } = useInquiryStore()
  const {
    recordContent,
    recordType,
    isGenerating,
    isPolishing,
    setRecordContent,
    setRecordType,
    setGenerating,
    setPolishing,
    isFinal,
    finalizedAt,
    pendingGenerate,
    setPendingGenerate,
  } = useRecordStore()
  const {
    isQCing,
    isQCStale,
    setQCing,
    setQCResult,
    appendQCIssues,
    setQCSummary,
    setQCLlmLoading,
    startQCRun,
    qcIssues,
    qcPass,
    gradeScore,
  } = useQCStore()
  const currentPatient = useCurrentPatient()
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const previousRecordContent = useActiveEncounterStore(s => s.previousRecordContent)
  const { token } = useAuthStore()
  const abortRef = useRef<AbortController | null>(null)

  const [finalModalOpen, setFinalModalOpen] = useState(false)
  const [isSupplementing, setIsSupplementing] = useState(false)

  // 把 abortRef 与 streamSSE 衔接：每次新调用前换一个 AbortController，
  // 卸载或主动取消时 abortRef.current?.abort() 触发流中止
  const runSSE = async (url: string, body: object, handlers: Parameters<typeof streamSSE>[3]) => {
    const ctrl = new AbortController()
    abortRef.current = ctrl
    return streamSSE(url, body, token || '', handlers, { signal: ctrl.signal })
  }

  // 生成完成后，把病历各段落解析回左侧问诊字段，确保左右一致
  const syncGeneratedRecordToInquiry = (content: string) => {
    const result = parseGeneratedSectionsToInquiry(content)
    if (Object.keys(result).length > 0) {
      setInquiry({ ...useInquiryStore.getState().inquiry, ...result })
    }
  }

  // 病程类病历生成前，从后端拉取最新病历作为参考（pull-forward 机制）
  const fetchLatestRecord = async (): Promise<string | undefined> => {
    const currentEncounterId = useActiveEncounterStore.getState().encounterId
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
    const { isFirstVisit, visitType: currentVisitType } = useActiveEncounterStore.getState()

    // 病程记录类型需要注入上一份病历作为 AI 上下文（pull-forward）
    // 用共享 isCourseRecordType()，避免跟 record_prompts._INPATIENT_TITLES /
    // record_renderer._RENDERERS 三处硬编码列表不同步。
    let previousRecord = previousRecordContent || undefined
    if (isCourseRecordType(recordType) && !previousRecord) {
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

    // 按 record_type 取该场景需要的字段子集，避免把全 43 字段（含其他场景专属字段）
    // 一股脑透传到后端——派生 selector 是 InquiryData Pick 拆分的"运行时出口"，
    // 类型层面同时保证编译期不串场。后端 QuickGenerateRequest 兼容缺字段（默认空）。
    const inquirySubset = pickInquiryByRecordType(recordType as RecordType, inquiry)

    try {
      await runSSE(
        '/api/v1/ai/quick-generate',
        {
          ...inquirySubset,
          ...profilePayload,
          record_type: recordType,
          // 接诊维度——后端 RequestContext 据此把 ai_task / 自动 quick_save
          // 都绑定到正确的接诊上，logout 重登能拿回 AI 产物
          encounter_id: currentEncounterId || undefined,
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
        {
          onChunk: text => setRecordContent(useRecordStore.getState().recordContent + text),
        }
      )
      syncGeneratedRecordToInquiry(useRecordStore.getState().recordContent)
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
    // 历史遗留：自由文本时代为防 LLM 幻觉编造舌象/脉象/证候诊断，这里加了个
    // "TCM 字段全空就拦一下"的弹窗。但它有两个问题：
    //   1) 不区分 record_type——首次病程记录 / 入院记录 等纯西医场景也会弹
    //   2) JSON 模式 + render_record 已经把空字段统一渲染成 [未填写] 占位符，
    //      LLM 拿到的是 schema 字段说明而非自由文本回填，根本不会编造
    // 同时 QC 引擎按 scope='tcm' 走专项规则，缺漏会单独提示。
    // 这道 guard 已经过时，直接删除。
    _doGenerate()
  }

  const handlePolish = async () => {
    if (!recordContent.trim()) {
      message.warning('病历内容为空，无法润色')
      return
    }
    setPolishing(true)
    const original = recordContent

    // 【追问补充】是结构化数据（来自右侧追问建议勾选 → buildSupplementSection 拼接的"问：答"），
    // 不能交给 LLM 润色——POLISH_PROMPT 虽然要求"原文保留"，实测 LLM 仍会把多行"问：答"
    // 合并整理成 1 句自然语言（5 行变 1 句），导致勾选数据丢失。
    // 解决：润色前把整段拆出，只把上半部分发给 LLM，润色完原样拼回。
    const supplementMarker = '【追问补充】'
    const supplementIdx = original.indexOf(supplementMarker)
    const contentForPolish =
      supplementIdx === -1 ? original : original.slice(0, supplementIdx).trimEnd()
    const supplementSection = supplementIdx === -1 ? '' : original.slice(supplementIdx).trimEnd()

    setRecordContent('')
    try {
      await runSSE(
        '/api/v1/ai/quick-polish',
        { content: contentForPolish },
        {
          onChunk: text => setRecordContent(useRecordStore.getState().recordContent + text),
        }
      )
      // 章节完整性守卫：LLM 可能误删章节（针对 contentForPolish 比对，不含追问补充）
      const polished = useRecordStore.getState().recordContent
      const { restored, missing } = restoreMissingSections(contentForPolish, polished)

      // 把保护下来的【追问补充】区块原样拼回末尾
      const finalContent = supplementSection
        ? restored.trimEnd() + '\n\n' + supplementSection
        : restored

      if (finalContent !== polished) {
        setRecordContent(finalContent)
      }
      if (missing.length > 0) {
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
    const qcContent = contentOverride ?? useRecordStore.getState().recordContent
    if (!qcContent.trim()) {
      message.warning('病历内容为空，无法质控')
      return
    }
    setQCing(true)
    startQCRun()
    let finalData: any = null
    try {
      // 质控接口推回多种事件类型（rule_issues / llm_issues / done），
      // 用 streamSSE 的通用 onEvent 分发器统一处理
      await runSSE(
        '/api/v1/ai/quick-qc',
        {
          content: qcContent,
          record_type: recordType,
          patient_gender: currentPatient?.gender || '',
          is_first_visit: useActiveEncounterStore.getState().isFirstVisit,
          encounter_id: currentEncounterId || undefined,
        },
        {
          onEvent: obj => {
            if (obj.type === 'rule_issues') {
              const gs =
                obj.grade_score != null
                  ? {
                      grade_score: obj.grade_score,
                      grade_level: obj.grade_level,
                      must_fix_count: obj.must_fix_count,
                    }
                  : null
              setQCResult(obj.issues || [], '', obj.pass ?? false, gs)
              setQCLlmLoading(true)
            } else if (obj.type === 'llm_issues') {
              appendQCIssues(obj.issues || [])
            } else if (obj.type === 'done') {
              finalData = obj
              setQCSummary(obj.summary || '')
              setQCLlmLoading(false)
            }
          },
        }
      )
      if (finalData) {
        const totalIssues = useQCStore.getState().qcIssues.length
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

    // 跟 handlePolish 同样的保护：把【追问补充】拆出去，不让 LLM 看到 → 不可能改写
    // SUPPLEMENT_PROMPT 让 LLM 全篇重写，不保护就会把"问：答"压缩成自然语言导致勾选数据丢失
    const supplementMarker = '【追问补充】'
    const supplementIdx = original.indexOf(supplementMarker)
    const contentForLLM =
      supplementIdx === -1 ? original : original.slice(0, supplementIdx).trimEnd()
    const supplementSection = supplementIdx === -1 ? '' : original.slice(supplementIdx).trimEnd()

    setRecordContent('')
    try {
      await runSSE(
        '/api/v1/ai/quick-supplement',
        {
          current_content: contentForLLM,
          qc_issues: qcIssues,
          ...inquiry,
          record_type: recordType,
          patient_name: currentPatient?.name || '',
          patient_gender: currentPatient?.gender || '',
          patient_age: currentPatient?.age != null ? String(currentPatient.age) : '',
        },
        {
          onChunk: text => setRecordContent(useRecordStore.getState().recordContent + text),
        }
      )
      // 把保护下来的【追问补充】区块原样拼回末尾
      const supplemented = useRecordStore.getState().recordContent
      const newContent = supplementSection
        ? supplemented.trimEnd() + '\n\n' + supplementSection
        : supplemented
      if (newContent !== supplemented) setRecordContent(newContent)

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
