/**
 * 工作台基础逻辑 Hook（hooks/useWorkbenchBase.ts）
 *
 * 提取三个工作台页面（门诊/急诊/住院）共同的逻辑：
 *   - 历史病历抽屉开关（historyOpen/openHistory）—— 数据由 PatientHistoryDrawer 自拉
 *   - 续接诊面板（resumeOpen/openResume/handleResume）
 *   - 登出操作（handleLogout）
 *
 * 通过 options 参数定制各工作台的差异行为：
 *   visitTypeFilter:   续接诊列表只显示特定类型（住院页只显示 inpatient 接诊）
 *   defaultRecordType: 恢复接诊时若无 active_record 用的默认病历类型
 *   resumeSuccessMsg:  恢复成功提示文本（可接收患者姓名参数）
 *   resumeErrorMsg:    恢复失败提示文本
 *
 * 恢复接诊（handleResume）流程：
 *   1. 调用 GET /encounters/{id}/workspace 获取完整快照
 *   2. 若病历已签发（status='submitted'），打开历史病历抽屉而非编辑器
 *   3. 否则依次恢复：reset → setCurrentEncounter → setInquiry → setRecordContent/Type
 */

import { useState } from 'react'
import { message } from '@/services/messageBridge'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import {
  resetAllWorkbench,
  setCurrentEncounterFromPatient,
  useActiveEncounterStore,
} from '@/store/activeEncounterStore'
import { applySnapshotResult, type SnapshotResult } from '@/store/encounterIntake'
import api from '@/services/api'
import type { Gender, Patient, VisitType } from '@/domain/medical'

/**
 * 历史病历抽屉 / 详情弹窗共用的"可视记录"形状。
 * - 与 RecordList.RecordListItem（id 可选）保持兼容，确保 onView={setViewRecord} 类型可接
 * - 也满足 RecordViewModal.ViewableRecord 字段集
 * 与 domain.MedicalRecord 解耦——后端联表 patient 后字段更多，且查询接口不一定回 current_version
 */
export interface WorkbenchViewableRecord {
  id?: string
  record_type: string
  status?: string
  visit_type?: string
  visit_sequence?: number
  content?: string
  content_preview?: string
  submitted_at?: string | null
  patient_name?: string
  patient_gender?: string
  patient_age?: number | null
  doctor_name?: string | null
  submitted_by_name?: string | null
  /** 后端可能携带的额外字段允许透传 */
  [key: string]: unknown
}

/**
 * /encounters/my 返回的"进行中接诊"列表项（前端实际用到的字段子集）。
 * 后端字段更多，但本 hook 只读必要字段；其他字段允许透传到 handleResume。
 */
interface ResumeEncounterItem {
  encounter_id: string
  visit_type?: string
  patient?: { name?: string } | null
  /** 允许后端额外字段透传（用 unknown 而非 any） */
  [key: string]: unknown
}

/** snapshot.visit_type 来自后端是宽字符串，收敛到 VisitType 联合或 undefined。 */
function toVisitType(raw: unknown): VisitType | undefined {
  return raw === 'emergency' || raw === 'inpatient' || raw === 'outpatient' ? raw : undefined
}

/** 后端 patient.gender 字符串 → domain Gender；未知值统一归为 unknown。 */
function toDomainPatient(p: NonNullable<SnapshotResult['patient']>): Patient {
  const g: Gender = p.gender === 'male' || p.gender === 'female' ? p.gender : 'unknown'
  return {
    id: p.id,
    name: p.name,
    gender: g,
    age: p.age ?? null,
    phone: p.phone ?? null,
    birth_date: p.birth_date ?? null,
  }
}

interface UseWorkbenchBaseOptions {
  /** 续接诊列表是否只加载特定类型，如 'inpatient' */
  visitTypeFilter?: string
  /** 恢复接诊时的默认病历类型 */
  defaultRecordType?: string
  /** 成功恢复接诊的提示文本，接收患者姓名 */
  resumeSuccessMsg?: (name: string) => string
  /** 恢复接诊失败的提示文本 */
  resumeErrorMsg?: string
}

export function useWorkbenchBase({
  visitTypeFilter,
  defaultRecordType = 'outpatient',
  resumeSuccessMsg = name => `已恢复「${name}」的接诊工作台`,
  resumeErrorMsg = '恢复接诊失败，请重试',
}: UseWorkbenchBaseOptions = {}) {
  const navigate = useNavigate()
  const { clearAuth } = useAuthStore()
  const setInquiry = useInquiryStore(s => s.setInquiry)
  const { setRecordContent, setRecordType, setFinal } = useRecordStore()

  // History drawer 开关（数据由 PatientHistoryDrawer 自己拉，不再走本 hook）
  const [historyOpen, setHistoryOpen] = useState(false)
  // 历史病历抽屉点击某条记录时打开的弹窗，传入的是后端 medical_records 行；
  // 与 PatientHistoryDrawer.HistoryRecord / RecordViewModal.ViewableRecord 取并集
  const [viewRecord, setViewRecord] = useState<WorkbenchViewableRecord | null>(null)

  // Resume drawer
  const [resumeOpen, setResumeOpen] = useState(false)
  const [resumeList, setResumeList] = useState<ResumeEncounterItem[]>([])
  const [resumeLoading, setResumeLoading] = useState(false)

  const openHistory = () => {
    setHistoryOpen(true)
  }

  const openResume = async () => {
    setResumeOpen(true)
    setResumeLoading(true)
    try {
      const data = (await api.get('/encounters/my')) as ResumeEncounterItem[] | null
      const list: ResumeEncounterItem[] = data || []
      setResumeList(visitTypeFilter ? list.filter(e => e.visit_type === visitTypeFilter) : list)
    } catch {
      message.error('加载进行中接诊失败')
    } finally {
      setResumeLoading(false)
    }
  }

  /**
   * 恢复某条进行中接诊。
   *
   * 入参允许是 ResumeEncounterItem（resumeList 元素），也允许调用方仅构造最小
   * 载荷 { encounter_id, patient_name } 直接走恢复流程（如住院端从病区列表
   * 选患者）—— 形状灵活，但 encounter_id 必填。
   */
  const handleResume = async (item: {
    encounter_id: string
    patient_name?: string
    patient?: { name?: string } | null
  }) => {
    setResumeLoading(true)
    try {
      const snapshot = (await api.get(
        `/encounters/${item.encounter_id}/workspace`
      )) as SnapshotResult & {
        is_first_visit?: boolean
        is_patient_reused?: boolean
      }
      if (snapshot.active_record?.status === 'submitted') {
        // 已签发病历不可继续编辑：不再让用户自己去找历史病历入口（住院端 PatientHistoryDrawer
        // 需要先选中病区患者才能查看，而签发后该患者已从"进行中"列表移除，会陷入死循环）。
        // 直接帮用户：① 把患者塞进 currentEncounter 让历史抽屉能识别 patientId
        //          ② 同步档案到本地缓存
        //          ③ 关续接诊抽屉、打开历史病历抽屉
        applySnapshotResult(snapshot)
        if (snapshot.patient && snapshot.encounter_id) {
          setCurrentEncounterFromPatient(toDomainPatient(snapshot.patient), snapshot.encounter_id, {
            visitType: toVisitType(snapshot.visit_type),
            isFirstVisit: snapshot.is_first_visit,
            isPatientReused: snapshot.is_patient_reused,
            previousRecordContent: snapshot.previous_record_content,
          })
        }
        setResumeOpen(false)
        setHistoryOpen(true)
        message.info(`「${snapshot.patient?.name || ''}」的本次病历已签发，已为您打开历史病历`)
        return
      }
      resetAllWorkbench()
      // 1.6 数据接入：snapshot 同样含 patient + patient_profile，写入 patientCache
      applySnapshotResult(snapshot)
      if (snapshot.patient && snapshot.encounter_id) {
        setCurrentEncounterFromPatient(toDomainPatient(snapshot.patient), snapshot.encounter_id, {
          visitType: toVisitType(snapshot.visit_type),
          isFirstVisit: snapshot.is_first_visit,
          isPatientReused: snapshot.is_patient_reused,
          previousRecordContent: snapshot.previous_record_content,
        })
      }
      if (snapshot.inquiry) {
        // snapshot.inquiry 是 Partial<InquiryData>；store.setInquiry 期待完整 InquiryData，
        // 沿用旧实现"直接灌 partial"行为，用 unknown 桥接以消除 any 噪音
        setInquiry(snapshot.inquiry as unknown as Parameters<typeof setInquiry>[0])
      }
      if (snapshot.active_record) {
        setRecordType(snapshot.active_record.record_type || defaultRecordType)
        setRecordContent(snapshot.active_record.content || '')
        setFinal(false)
      } else {
        setRecordType(defaultRecordType)
        setRecordContent('')
        setFinal(false)
      }
      message.success(
        resumeSuccessMsg(snapshot.patient?.name || item.patient?.name || item.patient_name || '')
      )
      setResumeOpen(false)
    } catch {
      message.error(resumeErrorMsg)
    } finally {
      setResumeLoading(false)
    }
  }

  const handleLogout = async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      // logout 失败也要继续清本地态（token 可能已过期，server 拒绝是正常的）
    }
    resetAllWorkbench()
    clearAuth()
    navigate('/login')
  }

  // ── 取消接诊（2026-05-03 加）───────────────────────────────────────────────
  // CancelEncounterModal 的开关 + 提交回调；调后端软取消 + 清前端工作台。
  // 失败时（如已签发病历返 403）展示错误，不清前端，方便医生看到原因。
  const [cancelOpen, setCancelOpen] = useState(false)
  const openCancel = () => setCancelOpen(true)
  const closeCancel = () => setCancelOpen(false)
  const handleCancelEncounter = async (cancelReason: string) => {
    const encounterId = useActiveEncounterStore.getState().encounterId
    if (!encounterId) {
      message.warning('当前没有进行中的接诊')
      setCancelOpen(false)
      return
    }
    try {
      await api.post(`/encounters/${encounterId}/cancel`, { cancel_reason: cancelReason })
      // 成功：清空所有工作台 store（跟登出走同一路径，确保 4 个子 store + active 全清）
      resetAllWorkbench()
      message.success('已取消本次接诊，数据已留档')
      setCancelOpen(false)
    } catch (err: unknown) {
      // axios 拦截器已弹通用 toast，这里再打一条带 detail 的，方便医生看具体原因
      const detail = (err as { detail?: string })?.detail
      if (detail) message.error(detail)
      // 不关弹窗，让医生看到错误后自行决定（如已签发病历需走作废流程）
    }
  }

  return {
    // History drawer 开关（PatientHistoryDrawer 共用此开关）
    historyOpen,
    setHistoryOpen,
    openHistory,
    // View record
    viewRecord,
    setViewRecord,
    // Resume
    resumeOpen,
    setResumeOpen,
    resumeList,
    resumeLoading,
    openResume,
    handleResume,
    // Auth
    handleLogout,
    // 取消接诊
    cancelOpen,
    openCancel,
    closeCancel,
    handleCancelEncounter,
  }
}
