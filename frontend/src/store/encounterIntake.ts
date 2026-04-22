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
import type { PatientProfile, VisitType } from '@/domain/medical'

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
export type SnapshotResult = EncounterIntakePayload

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
 * 处理 workspace snapshot 响应：写患者缓存 + 设置 activeEncounterStore。
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
}
