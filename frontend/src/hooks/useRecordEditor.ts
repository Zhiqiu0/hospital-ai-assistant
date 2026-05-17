/**
 * 病历编辑器逻辑（hooks/useRecordEditor.ts）
 *
 * 从 RecordEditor 抽离的业务 hook：负责 AI 生成 / 润色 / 质控 / 补全四个动作
 * 和章节守卫、SSE 流处理。SSE 通用代码已抽到 services/streamSSE.ts。
 */
import { useRef, useState, useEffect } from 'react'
import { message } from '@/services/messageBridge'
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
import { parseGeneratedSectionsToInquiry } from '@/utils/recordSections'
import type { QCIssue, GradeScore } from '@/store/types'

/**
 * SSE 事件 - 质控流的统一对象形状。
 * 后端会按 type 分发不同 payload：
 *   rule_issues: 携带 issues / pass / grade_score
 *   llm_issues:  追加质量建议（不影响 pass）
 *   done:        最终摘要 + 评分汇总
 */
interface QCStreamEvent {
  type?: string
  issues?: QCIssue[]
  pass?: boolean
  grade_score?: number
  grade_level?: GradeScore['grade_level']
  must_fix_count?: number
  summary?: string
}

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

  /** 构造发往 quick-supplement / quick-polish 的共享 payload。
   *
   * L3 治本路线：补全 / 润色 都走"JSON schema 输出 → renderer 重渲染"，
   * 与 quick-generate 同构，所以三家发送同一组字段（inquiry + profile +
   * patient 基本信息 + record_type 上下文）。后端依据 schema 字段说明让 LLM
   * 重新生成完整 JSON，renderer 拼装出唯一格式的病历正文——
   * 物理上不可能再出现"两段同名章节"。
   */
  const buildRecordTaskPayload = (currentContent: string): Record<string, unknown> => {
    const { isFirstVisit, visitType: currentVisitType } = useActiveEncounterStore.getState()
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
    // 与 _doGenerate 一致：按 record_type 取字段子集，避免串场
    const inquirySubset = pickInquiryByRecordType(recordType as RecordType, inquiry)
    return {
      ...inquirySubset,
      ...profilePayload,
      record_type: recordType,
      current_content: currentContent,
      encounter_id: currentEncounterId || undefined,
      patient_name: currentPatient?.name || '',
      patient_gender: currentPatient?.gender || '',
      patient_age: currentPatient?.age != null ? String(currentPatient.age) : '',
      is_first_visit: isFirstVisit,
      visit_type_detail: currentVisitType,
      visit_time: inquiry.visit_time || '',
      onset_time: inquiry.onset_time || '',
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
    } catch (e) {
      // AbortError 是用户主动取消，正常路径不弹错；其他错误统一提示
      if ((e as { name?: string })?.name !== 'AbortError') message.error('生成失败，请重试')
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

    // 【追问补充】区块在新架构下仍由前端独立维护——它是医生勾选的"问：答"对
    // 不参与 LLM 润色（防止被合并成自然语言导致勾选数据丢失），润色完原样拼回末尾
    const supplementMarker = '【追问补充】'
    const supplementIdx = original.indexOf(supplementMarker)
    const contentForPolish =
      supplementIdx === -1 ? original : original.slice(0, supplementIdx).trimEnd()
    const supplementSection = supplementIdx === -1 ? '' : original.slice(supplementIdx).trimEnd()

    setRecordContent('')
    let gotError = false
    try {
      await runSSE(
        '/api/v1/ai/quick-polish',
        buildRecordTaskPayload(contentForPolish),
        {
          onChunk: text => setRecordContent(useRecordStore.getState().recordContent + text),
          onEvent: (raw: unknown) => {
            // 后端 JSON 路线下任何异常都通过 type=error 事件返回（不再抛 SSE 异常）
            const obj = (raw || {}) as { type?: string; message?: string }
            if (obj.type === 'error') {
              gotError = true
              message.error(`润色失败：${obj.message || '请重试'}`)
            }
          },
        }
      )
      // 后端 renderer 已保证章节唯一，不再需要 restoreMissingSections 守卫
      // 只把保护下来的【追问补充】区块原样拼回末尾即可
      if (gotError) {
        // LLM 失败时不破坏原内容
        setRecordContent(original)
        return
      }
      const polished = useRecordStore.getState().recordContent
      if (supplementSection) {
        setRecordContent(polished.trimEnd() + '\n\n' + supplementSection)
      }
    } catch (e) {
      if ((e as { name?: string })?.name !== 'AbortError') {
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
    // finalData 收集 done 事件的载荷，跨 onEvent 闭包累积——用 QCStreamEvent 类型化
    let finalData: QCStreamEvent | null = null
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
          // streamSSE 的 onEvent 参数本身是泛型对象，这里把它收敛到 QCStreamEvent
          onEvent: (raw: unknown) => {
            const obj = (raw || {}) as QCStreamEvent
            if (obj.type === 'rule_issues') {
              const gs: GradeScore | null =
                obj.grade_score != null && obj.grade_level
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
        // TS 在闭包外无法推断回调里赋值的 finalData，借助 const 收敛非 null 视图
        const done: QCStreamEvent = finalData
        const totalIssues = useQCStore.getState().qcIssues.length
        if (done.grade_level === '合格' || done.grade_level === '甲级') {
          message.success(
            `质控通过！评分 ${done.grade_score} 分（${done.grade_level}）`
          )
        } else if (done.grade_score != null) {
          message.warning(
            `评分 ${done.grade_score} 分（${done.grade_level}），发现 ${totalIssues} 个问题，请查看右侧质控提示`
          )
        } else if (done.pass) {
          message.success('质控通过！')
        } else {
          message.warning(`发现 ${totalIssues} 个问题，请查看右侧质控提示`)
        }
      }
    } catch (e) {
      if ((e as { name?: string })?.name !== 'AbortError') message.error('质控失败，请重试')
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

    // 【追问补充】区块由前端独立维护（医生勾选的"问：答"对），
    // 不参与 LLM 补全 → 拆出 → LLM 重新生成主体 → 拼回末尾
    const supplementMarker = '【追问补充】'
    const supplementIdx = original.indexOf(supplementMarker)
    const contentForLLM =
      supplementIdx === -1 ? original : original.slice(0, supplementIdx).trimEnd()
    const supplementSection = supplementIdx === -1 ? '' : original.slice(supplementIdx).trimEnd()

    setRecordContent('')
    let gotError = false
    let errorMsg = ''
    try {
      await runSSE(
        '/api/v1/ai/quick-supplement',
        { ...buildRecordTaskPayload(contentForLLM), qc_issues: qcIssues },
        {
          onChunk: text => setRecordContent(useRecordStore.getState().recordContent + text),
          onEvent: (raw: unknown) => {
            const obj = (raw || {}) as { type?: string; message?: string }
            if (obj.type === 'error') {
              gotError = true
              errorMsg = obj.message || ''
            }
          },
        }
      )
      if (gotError) {
        setRecordContent(original)
        // 旧版本会区分 context_length_exceeded 等细节，但 JSON 路线下后端用 ValueError
        // 兜底，前端只显示提示即可——具体错误类型已在后端日志记录
        message.error(`补全失败：${errorMsg || '请重试'}`)
        return
      }
      // 后端 renderer 已保证章节唯一，不再需要前端去重 / 章节守卫
      const supplemented = useRecordStore.getState().recordContent
      const newContent = supplementSection
        ? supplemented.trimEnd() + '\n\n' + supplementSection
        : supplemented
      if (newContent !== supplemented) setRecordContent(newContent)

      message.success('补全完成，正在重新质控...')
      setIsSupplementing(false)
      await handleQC(newContent)
      return
    } catch (e) {
      const err = e as { name?: string; message?: string }
      if (err?.name === 'AbortError') return
      setRecordContent(original)
      message.error('补全失败，请重试')
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
    // 只关心 pendingGenerate flag 切到 true；handleGenerate / setPendingGenerate 加进
    // deps 会让 effect 在每次 render 都跑（handleGenerate 是 component-local 函数）
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
