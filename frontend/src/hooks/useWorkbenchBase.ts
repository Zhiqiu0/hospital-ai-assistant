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
import { message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { resetAllWorkbench, setCurrentEncounterFromPatient } from '@/store/activeEncounterStore'
import { applySnapshotResult } from '@/store/encounterIntake'
import api from '@/services/api'

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
  const [viewRecord, setViewRecord] = useState<any>(null)

  // Resume drawer
  const [resumeOpen, setResumeOpen] = useState(false)
  const [resumeList, setResumeList] = useState<any[]>([])
  const [resumeLoading, setResumeLoading] = useState(false)

  const openHistory = () => {
    setHistoryOpen(true)
  }

  const openResume = async () => {
    setResumeOpen(true)
    setResumeLoading(true)
    try {
      const data: any = await api.get('/encounters/my')
      const list = data || []
      setResumeList(
        visitTypeFilter ? list.filter((e: any) => e.visit_type === visitTypeFilter) : list
      )
    } catch {
      message.error('加载进行中接诊失败')
    } finally {
      setResumeLoading(false)
    }
  }

  const handleResume = async (item: any) => {
    setResumeLoading(true)
    try {
      const snapshot: any = await api.get(`/encounters/${item.encounter_id}/workspace`)
      if (snapshot.active_record?.status === 'submitted') {
        // 已签发病历不可继续编辑：不再让用户自己去找历史病历入口（住院端 PatientHistoryDrawer
        // 需要先选中病区患者才能查看，而签发后该患者已从"进行中"列表移除，会陷入死循环）。
        // 直接帮用户：① 把患者塞进 currentEncounter 让历史抽屉能识别 patientId
        //          ② 同步档案到本地缓存
        //          ③ 关续接诊抽屉、打开历史病历抽屉
        applySnapshotResult(snapshot)
        if (snapshot.patient) {
          setCurrentEncounterFromPatient(snapshot.patient, snapshot.encounter_id, {
            visitType: snapshot.visit_type,
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
      if (snapshot.patient) {
        setCurrentEncounterFromPatient(snapshot.patient, snapshot.encounter_id, {
          visitType: snapshot.visit_type,
          isFirstVisit: snapshot.is_first_visit,
          isPatientReused: snapshot.is_patient_reused,
          previousRecordContent: snapshot.previous_record_content,
        })
      }
      if (snapshot.inquiry) {
        setInquiry(snapshot.inquiry)
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
      message.success(resumeSuccessMsg(snapshot.patient?.name || item.patient?.name || ''))
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
    } catch (_) {}
    resetAllWorkbench()
    clearAuth()
    navigate('/login')
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
  }
}
