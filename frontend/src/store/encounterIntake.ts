/**
 * 接诊响应统一接入工具（store/encounterIntake.ts）
 *
 * 后端 `quick-start` 与 `workspace snapshot` 接口都返回 `patient` + `patient_profile`
 * 两段数据。前端有 4 处入口需要把这两段数据同步到 patientCacheStore：
 *   1. WorkbenchPage.handleEncounterCreated  （门诊/急诊新建/复诊）
 *   2. useInquiryPanel.handleAdmitToInpatient（急诊→住院转入）
 *   3. NewInpatientEncounterModal.handleSubmit（住院新建）
 *   4. useWorkbenchBase.handleResume         （从未完成接诊恢复）
 *
 * 把这段重复逻辑收口到本文件，调用方只需一行 `applyQuickStartResult(res)`，
 * 既避免了 4 处实现分叉，也方便后续扩展（如增加埋点 / 缓存预热）。
 *
 * 注意：本文件不操作 workbenchStore。activeEncounterStore 与 workbenchStore 的
 * 老指针字段（currentPatient / currentEncounterId）目前并存，前者由本工具写，
 * 后者仍由调用方各自显式调用 setCurrentEncounter，等 1.6 后续迁移完整再删旧字段。
 */

import { usePatientCacheStore } from './patientCacheStore'
import { useActiveEncounterStore } from './activeEncounterStore'
import { useInquiryStore } from './inquiryStore'
import { useRecordStore } from './recordStore'
import { useQCStore } from './qcStore'
import { useAISuggestionStore } from './aiSuggestionStore'
import type { PatientProfile, VisitType } from '@/domain/medical'
import type { InquiryData, QCIssue } from './types'

/** quick-start 与 snapshot 共有的最小字段集合 */
export interface EncounterIntakePayload {
  encounter_id?: string | null
  patient?: {
    id: string
    name: string
    gender?: string | null
    age?: number | null
    phone?: string | null
    birth_date?: string | null
  } | null
  /** 后端 patient_profile 含 8 个 profile_* 字段 + updated_at；可为 null */
  patient_profile?: (PatientProfile & { updated_at?: string | null }) | null
  visit_type?: string | null
  patient_reused?: boolean
  previous_record_content?: string | null
}

/** quick-start 响应专用：含初诊/复诊判断、上次病历参考 */
export interface QuickStartResult extends EncounterIntakePayload {
  encounter_id: string
  patient: NonNullable<EncounterIntakePayload['patient']>
  resumed?: boolean
}

/** snapshot 响应专用：含 active_record / inquiry，可能 inquiry 为 null */
export interface SnapshotResult extends EncounterIntakePayload {
  /** 接诊问诊数据（医生填的字段） */
  inquiry?: Partial<InquiryData> | null
  /** 当前活跃病历的最新版本（含 content 文本） */
  active_record?: {
    record_id?: string
    record_type?: string
    status?: string
    content?: string
    /** ISO 字符串，后端 _serialize_record 返回，用于状态条显示"X 分钟前保存" */
    updated_at?: string | null
  } | null
  /** 最新 QC 跑出来的问题列表（logout 重登也能恢复） */
  latest_qc_issues?: QCIssue[] | null
  /** 各类 AI 建议产物（追问 / 检查 / 诊断），key=task_type */
  latest_ai_suggestions?: {
    inquiry?: { suggestions?: any[] }
    exam?: { suggestions?: any[] }
    diagnosis?: { diagnoses?: any[] }
  } | null
}

/**
 * 把后端 patient + patient_profile 写入 patientCacheStore。
 * patient 缺失时整体跳过，避免悬空 profile。
 */
function syncPatientToCache(payload: EncounterIntakePayload): void {
  const patient = payload.patient
  if (!patient) return
  const cache = usePatientCacheStore.getState()
  // 把后端 patient 形状收敛到 domain 层 Patient 类型
  cache.upsertPatient({
    id: patient.id,
    name: patient.name,
    gender: patient.gender === 'male' || patient.gender === 'female' ? patient.gender : 'unknown',
    age: patient.age ?? null,
    phone: patient.phone ?? null,
    birth_date: patient.birth_date ?? null,
  })
  if (payload.patient_profile) {
    // 剥离 updated_at 之外仍写入；patientCache 的 PatientProfile 类型本身允许 updated_at
    cache.upsertProfile(patient.id, payload.patient_profile)
  }
}

/**
 * 把后端 visit_type 字符串收敛到 VisitType 联合类型。
 * 未知值默认归为 outpatient，避免类型不匹配造成路由分支错乱。
 */
function normalizeVisitType(raw?: string | null): VisitType {
  if (raw === 'emergency' || raw === 'inpatient' || raw === 'outpatient') return raw
  return 'outpatient'
}

/**
 * 处理 quick-start 响应：写患者缓存 + 设置 activeEncounterStore。
 * 调用方在此之后仍可继续操作 workbenchStore（reset/setCurrentEncounter 等），
 * 本函数不与之耦合。
 */
export function applyQuickStartResult(res: QuickStartResult): void {
  syncPatientToCache(res)
  useActiveEncounterStore.getState().setActive({
    patientId: res.patient.id,
    encounterId: res.encounter_id,
    visitType: normalizeVisitType(res.visit_type),
    // patient_reused=true 表示复诊，对应 isFirstVisit=false
    isFirstVisit: !res.patient_reused,
    isPatientReused: !!res.patient_reused,
    previousRecordContent: res.previous_record_content ?? null,
  })
}

/**
 * 处理 workspace snapshot 响应：写所有相关 store + 患者缓存 + activeEncounterStore。
 *
 * ★ 治本：兑现"snapshot 恢复 = 把所有 store 灌满"的承诺。
 *   过去的实现只填了 patientCache + activeEncounter，logout 重登时
 *   inquiry / record / qc / aiSuggestion 4 个 store 全是空的——给医生
 *   "数据丢了"的错觉。
 *
 *   现在把后端 snapshot 返回的 inquiry / active_record /
 *   latest_qc_issues / latest_ai_suggestions 一并灌回前端 store，
 *   做到"DB 有什么 → 前端就显示什么"。
 *
 * 与 applyQuickStartResult 相比，snapshot 没有 patient_reused 概念，
 * 这里默认按"复诊场景"处理（isFirstVisit=false），等待调用方按业务再修正。
 */
export function applySnapshotResult(res: SnapshotResult): void {
  syncPatientToCache(res)
  if (res.encounter_id && res.patient) {
    useActiveEncounterStore.getState().setActive({
      patientId: res.patient.id,
      encounterId: res.encounter_id,
      visitType: normalizeVisitType(res.visit_type),
      // 恢复接诊时无法判定初诊/复诊，沿用最保守的复诊态，避免误清空 previous_record
      isFirstVisit: false,
      isPatientReused: true,
      previousRecordContent: null,
    })
  }

  // ── 灌回 4 个工作台 store（业务核心数据） ────────────────────────
  // inquiry：医生填的问诊字段
  if (res.inquiry) {
    // updateInquiryFields 用部分字段补丁覆盖，不打"已保存"标记
    // （未保存状态由用户编辑触发，不由恢复触发）
    useInquiryStore.getState().updateInquiryFields(res.inquiry as InquiryData)
  }

  // record：当前活跃病历的内容
  if (res.active_record) {
    const recordStore = useRecordStore.getState()
    if (res.active_record.record_type) {
      recordStore.setRecordType(res.active_record.record_type)
    }
    recordStore.setRecordContent(res.active_record.content || '')
    recordStore.setFinal(res.active_record.status === 'submitted')
    // 把 DB 里的 updated_at 灌回 recordSavedAt——logout 重登 / 切设备时
    // 状态条立即显示"病历 X 分钟前保存"，而不是误报"草稿未保存"
    if (res.active_record.updated_at) {
      const ts = Date.parse(res.active_record.updated_at)
      if (!isNaN(ts)) recordStore.setRecordSavedAt(ts)
    }
  }

  // qc：最新一次 QC 跑出来的问题列表
  // ⚠️ 只在前端 store 为空时灌入——刷新时 zustand persist 已经从 localStorage
  // 恢复了 qcFixTexts（医生编辑的修复内容）和 qcWrittenIndices（已写入标记），
  // 直接 setQCResult 会触发 startQCRun 等价动作把这些临时编辑全冲掉。
  if (res.latest_qc_issues && res.latest_qc_issues.length > 0) {
    const qcStore = useQCStore.getState()
    if (qcStore.qcIssues.length === 0) {
      // pass 不能硬编码 false：
      //   后端 qc_stream_service.py 的判定是 blocking_count == 0
      //   （source='rule' / 'insurance' 才算 blocking，LLM 质量建议不算）。
      //   恢复时用同样口径重算，否则只剩 4 条 LLM 质量建议时
      //   左侧 toolbar 错误显示"结构未通过"，与右侧面板"必须修复 0 项"矛盾。
      const blockingCount = res.latest_qc_issues.filter(
        i => i.source === 'rule' || i.source == null
      ).length
      qcStore.setQCResult(res.latest_qc_issues, '', blockingCount === 0, null)
    }
  }

  // aiSuggestion：追问 / 检查 / 诊断三类建议
  // ⚠️ 合并而非覆盖——保留医生临时勾选状态：
  //   - examSuggestions.isOrdered（医生勾的"已开单"）
  //   - inquirySuggestions.selectedOptions（医生选的追问选项）
  // 后端 snapshot 拿不到这些临时状态（只存 LLM 原始 output），如果直接覆盖
  // 医生每次刷新 / 复诊点击都会丢勾选——这是用户报告的"举一反三"问题。
  const aiSug = res.latest_ai_suggestions
  if (aiSug) {
    const store = useAISuggestionStore.getState()

    // 追问：按 text 匹配前端已有项，保留 selectedOptions
    if (aiSug.inquiry?.suggestions) {
      const existingByText = new Map(store.inquirySuggestions.map(s => [s.text, s]))
      store.setInquirySuggestions(
        aiSug.inquiry.suggestions.map((s: any, idx: number) => {
          const existing = existingByText.get(s.text)
          return {
            ...s,
            id: existing?.id ?? `restored-${idx}`,
            options: s.options || [],
            // 保留医生已选的选项；前端无该项时初始化空数组
            selectedOptions: existing?.selectedOptions ?? [],
          }
        })
      )
    }

    // 检查建议：按 exam_name 匹配前端已有项，保留 isOrdered
    if (aiSug.exam?.suggestions) {
      const existingByName = new Map(store.examSuggestions.map(s => [s.exam_name, s]))
      store.setExamSuggestions(
        aiSug.exam.suggestions.map((s: any) => ({
          ...s,
          // 保留医生标记的"已开单"状态，后端不存这个，前端独立维护
          isOrdered: existingByName.get(s.exam_name)?.isOrdered ?? s.isOrdered,
        }))
      )
    }

    // 诊断：直接灌（diagnoses 列表本身没有"局部勾选"状态，
    // appliedDiagnosis 是单独字段，不在此 list 里，不会被冲掉）
    if (aiSug.diagnosis?.diagnoses) {
      store.setDiagnosisSuggestions(aiSug.diagnosis.diagnoses)
    }
  }
}
