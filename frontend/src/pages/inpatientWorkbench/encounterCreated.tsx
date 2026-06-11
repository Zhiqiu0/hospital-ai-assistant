/**
 * 住院接诊创建成功处理（pages/inpatientWorkbench/encounterCreated.tsx）
 *
 * 2026-06-11 Round 5.5 拆分：从 InpatientWorkbenchPage.tsx 抽出（纯逻辑搬家，
 * 不改行为）。新建住院接诊成功后的全部副作用编排：
 *   - 重置工作台 store + 病历类型设回 admission_note
 *   - 写 patientCache、设置接诊指针 + 元信息（与门诊端对齐）
 *   - 复诊预填稳定问诊字段、跨医生未完成接诊警示（非阻断）
 *   - 续接（resumed）时拉 workspace snapshot 灌回 4 个 store
 *
 * 注：原页面用 useRecordStore/useInquiryStore 的 hook 选择器取 action，
 * zustand action 引用稳定，这里等价改用 getState() 直取，行为一致。
 */
import { App } from 'antd'
import { message } from '@/services/messageBridge'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { resetAllWorkbench, setCurrentEncounterFromPatient } from '@/store/activeEncounterStore'
import type { VisitType, Patient, Gender } from '@/domain/medical'
import {
  applyQuickStartResult,
  applySnapshotResult,
  type QuickStartResult,
  type SnapshotResult,
} from '@/store/encounterIntake'
import type { InquiryData } from '@/store/types'
import api from '@/services/api'

/** App.useApp() 返回的 modal 实例类型（能 consume 主题 context，勿用 Modal.info 静态方法） */
type ModalApi = ReturnType<typeof App.useApp>['modal']

/** 住院 quick-start 回调载荷：基础字段从 QuickStartResult 沿用，外加业务扩展字段。 */
export type InpatientEncounterCreatedRes = QuickStartResult & {
  resumed?: boolean
  is_first_visit?: boolean
  previous_inquiry?: Partial<InquiryData> | null
  pending_encounters?: Array<{
    doctor_name: string
    visit_type: string
    visited_at?: string
  }>
}

// 新建住院接诊成功回调（与门诊端对齐：写 patientCache、预填稳定字段、传递上次病历）
export function handleInpatientEncounterCreated(
  res: InpatientEncounterCreatedRes,
  modal: ModalApi
) {
  resetAllWorkbench()
  useRecordStore.getState().setRecordType('admission_note')
  applyQuickStartResult(res)
  // 后端 patient.gender 是 string | null；与 syncPatientToCache 同步规则一致——
  // 未知值统一归为 unknown，避免类型不匹配
  const normalizedGender: Gender =
    res.patient.gender === 'male' || res.patient.gender === 'female'
      ? res.patient.gender
      : 'unknown'
  const patientForActive: Patient = {
    ...res.patient,
    gender: normalizedGender,
  }
  // 一次性设置接诊指针 + 元信息（visitType / firstVisit / patientReused / previousRecordContent）
  setCurrentEncounterFromPatient(patientForActive, res.encounter_id, {
    visitType: (res.visit_type || 'inpatient') as VisitType,
    // 用后端权威 is_first_visit（避免续接未签发接诊被误标"复诊"）；fallback 兼容
    isFirstVisit:
      typeof res.is_first_visit === 'boolean' ? res.is_first_visit : !res.patient_reused,
    isPatientReused: !!res.patient_reused,
    previousRecordContent: res.previous_record_content || null,
  })
  // 复诊且非续接：预填上次的稳定问诊字段
  if (res.patient_reused && !res.resumed && res.previous_inquiry) {
    const current = useInquiryStore.getState().inquiry
    useInquiryStore.getState().updateInquiryFields({ ...current, ...res.previous_inquiry })
  }
  // 跨医生未完成接诊警示（非阻断），与门诊端一致
  if (Array.isArray(res.pending_encounters) && res.pending_encounters.length > 0) {
    modal.info({
      title: '该患者尚有未完成接诊',
      width: 480,
      content: (
        <div style={{ marginTop: 8 }}>
          <div style={{ marginBottom: 10, color: 'var(--text-3)', fontSize: 13 }}>
            建议联系下列医生处理后再继续，避免重复就诊：
          </div>
          <ul style={{ paddingLeft: 18, margin: 0, fontSize: 13, lineHeight: 2 }}>
            {res.pending_encounters.map(
              (e: { doctor_name: string; visit_type: string; visited_at?: string }, i: number) => (
                <li key={i}>
                  医生 <b>{e.doctor_name}</b>（
                  {e.visit_type === 'emergency'
                    ? '急诊'
                    : e.visit_type === 'inpatient'
                      ? '住院'
                      : '门诊'}
                  {e.visited_at ? `，${new Date(e.visited_at).toLocaleString('zh-CN')}` : ''}）
                </li>
              )
            )}
          </ul>
        </div>
      ),
      okText: '我已知悉，继续接诊',
    })
  }
  if (res.resumed) {
    message.info(`「${res.patient.name}」有未完成的住院接诊，已自动恢复`)
    // 与门诊路径一致：自动恢复时拉 snapshot 灌回 4 个 store
    void api
      .get(`/encounters/${res.encounter_id}/workspace`)
      .then(snapshot => {
        // 后端 workspace 接口返回形状已被 SnapshotResult 描述
        if (snapshot) applySnapshotResult(snapshot as SnapshotResult)
      })
      .catch(() => {
        /* 静默失败 */
      })
  } else {
    message.success(`已为「${res.patient.name}」开始住院接诊`)
  }
}
