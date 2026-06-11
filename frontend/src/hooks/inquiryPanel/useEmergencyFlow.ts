/**
 * 急诊流转动作（hooks/inquiryPanel/useEmergencyFlow.ts）
 *
 * 从 useInquiryPanel.ts 拆出（2026-06-11 Round 5.5 拆分），逻辑一字未改：
 *   - handleAdmitToInpatient：急诊→住院（保留急诊病历作参考，创建住院接诊并跳转）
 *   - handleAddObservationNote：急诊留观追记（病历末尾插入带时间戳的追记块）
 */
import { message } from '@/services/messageBridge'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import type { Patient, Gender } from '@/domain/medical'
import { resetAllWorkbench, setCurrentEncounterFromPatient } from '@/store/activeEncounterStore'
import { applyQuickStartResult } from '@/store/encounterIntake'
import api from '@/services/api'
import type { QuickStartResult } from '@/store/encounterIntake'

interface EmergencyFlowParams {
  currentPatient: Patient | null
  recordContent: string
  setRecordContent: (content: string) => void
}

export function useEmergencyFlow({
  currentPatient,
  recordContent,
  setRecordContent,
}: EmergencyFlowParams) {
  const navigate = useNavigate()

  // 急诊→住院：保留急诊病历作参考，创建住院接诊并跳转
  const handleAdmitToInpatient = async () => {
    if (!currentPatient) return
    const emergencyRecord = recordContent
    try {
      const res = (await api.post('/encounters/quick-start', {
        patient_id: currentPatient.id,
        patient_name: currentPatient.name,
        visit_type: 'inpatient',
      })) as QuickStartResult
      resetAllWorkbench()
      // 1.6 数据接入：把住院 quick-start 的 patient + profile 写入新 store
      applyQuickStartResult(res)
      // 后端 patient.gender 是 string | null，domain Patient.gender 是 Gender 联合，
      // 与 encounterIntake.syncPatientToCache 同步逻辑保持一致——未知值统一归为 unknown
      const normalizedGender: Gender =
        res.patient.gender === 'male' || res.patient.gender === 'female'
          ? res.patient.gender
          : 'unknown'
      const patientForActive: Patient = {
        ...res.patient,
        gender: normalizedGender,
      }
      // 一次性写入接诊指针 + 元信息（visitType/firstVisit/previousRecordContent 全在 options 里）
      setCurrentEncounterFromPatient(patientForActive, res.encounter_id, {
        visitType: 'inpatient',
        isFirstVisit: false,
        previousRecordContent: emergencyRecord || null,
      })
      navigate('/inpatient')
      message.success(`已为「${res.patient.name}」创建住院接诊`)
    } catch {
      message.error('创建住院接诊失败，请稍后重试')
    }
  }

  // 急诊留观追记：在病历末尾插入带时间戳的追记块
  const handleAddObservationNote = () => {
    const timestamp = dayjs().format('YYYY-MM-DD HH:mm')
    const block = `\n\n【留观追记 ${timestamp}】\n[请在此记录病情变化及处理措施]`
    setRecordContent(recordContent + block)
    message.success('已在病历末尾添加留观追记，请在右侧编辑')
  }

  return { handleAdmitToInpatient, handleAddObservationNote }
}
