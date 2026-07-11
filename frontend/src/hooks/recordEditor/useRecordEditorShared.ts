/**
 * 病历编辑器共享基础设施（hooks/recordEditor/useRecordEditorShared.ts）
 *
 * 职责：为生成 / 润色 / 质控 / 补全四个动作 hook 提供共用能力——
 *   - runSSE：统一的 SSE 调用入口（衔接 AbortController，卸载时中止）
 *   - buildRecordTaskPayload：构造 quick-supplement / quick-polish 共享 payload
 *   - fetchLatestRecord：病程类病历的 pull-forward 拉取
 *   - syncGeneratedRecordToInquiry：生成结果回写左侧问诊字段
 *
 * 拆分来源：2026-06-11 Round 5 从 hooks/useRecordEditor.ts（约 500 行）拆出，
 * 纯搬家不改逻辑；useRecordEditor.ts 退化为门面（组合聚合）。
 */
import { useRef, useEffect } from 'react'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { useAuthStore } from '@/store/authStore'
import { usePatientCacheStore } from '@/store/patientCacheStore'
import { useActiveEncounterStore, useCurrentPatient } from '@/store/activeEncounterStore'
import { pickInquiryByRecordType, type RecordType } from '@/store/inquiryFieldGroups'
import { PROFILE_FIELD_KEYS } from '@/domain/medical'
import { streamSSE } from '@/services/streamSSE'
import { parseGeneratedSectionsToInquiry } from '@/utils/recordSections'

/** 四个动作 hook 共用的依赖集合（由 useRecordEditorShared 产出，门面注入） */
export interface RecordEditorShared {
  /** 当前登录 token（供需要手写 fetch 的动作使用，如补全） */
  token: string | null
  /** 统一 SSE 调用：每次新调用前换一个 AbortController */
  runSSE: (url: string, body: object, handlers: Parameters<typeof streamSSE>[3]) => Promise<void>
  /** 构造发往 quick-supplement / quick-polish 的共享 payload */
  buildRecordTaskPayload: (currentContent: string) => Record<string, unknown>
  /** 病程类病历生成前，从后端拉取最新病历作为参考（pull-forward 机制） */
  fetchLatestRecord: () => Promise<string | undefined>
  /** 生成完成后，把病历各段落解析回左侧问诊字段，确保左右一致 */
  syncGeneratedRecordToInquiry: (content: string) => void
}

export function useRecordEditorShared(): RecordEditorShared {
  // 各域字段从对应子 store 取（仅取共享能力需要的切片）
  const { inquiry, setInquiry } = useInquiryStore()
  const { recordType } = useRecordStore()
  const currentPatient = useCurrentPatient()
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const { token } = useAuthStore()
  const abortRef = useRef<AbortController | null>(null)

  // 把 abortRef 与 streamSSE 衔接：每次新调用前换一个 AbortController，
  // 卸载或主动取消时 abortRef.current?.abort() 触发流中止。
  //
  // 接诊指针守卫（P0）：编辑器组件切换患者时不卸载、只 reset store，卸载时才 abort
  // 的旧机制挡不住"生成中途切患者"——上一位患者的流会继续把 chunk 追加进新患者的
  // 编辑器，5 秒后还会以新患者的 encounter_id 落库。这里捕获发起时的 encounterId，
  // 把 handlers 包一层：一旦指针变化立刻 abort 并停止写入，从根上杜绝跨患者串数据。
  const runSSE = async (url: string, body: object, handlers: Parameters<typeof streamSSE>[3]) => {
    const ctrl = new AbortController()
    abortRef.current = ctrl
    const startEncounterId = useActiveEncounterStore.getState().encounterId
    const stillSameEncounter = () =>
      useActiveEncounterStore.getState().encounterId === startEncounterId
    const guarded: typeof handlers = {
      onChunk: text => {
        if (!stillSameEncounter()) {
          ctrl.abort()
          return
        }
        handlers.onChunk?.(text)
      },
      onEvent: event => {
        if (!stillSameEncounter()) {
          ctrl.abort()
          return
        }
        handlers.onEvent?.(event)
      },
    }
    return streamSSE(url, body, token || '', guarded, { signal: ctrl.signal })
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

  // 组件卸载时中止当前请求
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  return {
    token,
    runSSE,
    buildRecordTaskPayload,
    fetchLatestRecord,
    syncGeneratedRecordToInquiry,
  }
}
