/**
 * AI 生成动作（hooks/recordEditor/useRecordGenerate.ts）
 *
 * 职责：病历"AI 生成"动作编排——
 *   - _doGenerate：组 payload（inquiry 子集 + profile + 患者/接诊上下文 +
 *     pull-forward 上一份病历）→ SSE 流式生成 → 回写左侧问诊字段
 *   - handleGenerate：入口守卫（主诉必填）
 *   - pendingGenerate 监听：外部置位标志后自动触发生成
 *
 * 拆分来源：2026-06-11 Round 5 从 hooks/useRecordEditor.ts（约 500 行）拆出，
 * 纯搬家不改逻辑。
 */
import { useEffect } from 'react'
import { message } from '@/services/messageBridge'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { usePatientCacheStore } from '@/store/patientCacheStore'
import { useActiveEncounterStore, useCurrentPatient } from '@/store/activeEncounterStore'
import {
  isCourseRecordType,
  pickInquiryByRecordType,
  type RecordType,
} from '@/store/inquiryFieldGroups'
import { PROFILE_FIELD_KEYS } from '@/domain/medical'
import type { RecordEditorShared } from './useRecordEditorShared'

export function useRecordGenerate(shared: RecordEditorShared) {
  const { runSSE, fetchLatestRecord, syncGeneratedRecordToInquiry } = shared
  const { inquiry } = useInquiryStore()
  const { recordType, setRecordContent, setGenerating, pendingGenerate, setPendingGenerate } =
    useRecordStore()
  const currentPatient = useCurrentPatient()
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const previousRecordContent = useActiveEncounterStore(s => s.previousRecordContent)

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
      // 指针守卫：流刚好在切患者瞬间正常结束时，runSSE 未必来得及 abort，
      // 这里再挡一次，避免把上一位患者的病历回写进新患者的问诊字段（P0）。
      if (useActiveEncounterStore.getState().encounterId !== currentEncounterId) return
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

  return { handleGenerate }
}
