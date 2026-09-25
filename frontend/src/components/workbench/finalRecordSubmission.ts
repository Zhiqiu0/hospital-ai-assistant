/** 签发提交及结果落入工作台；独立于弹窗表单状态，避免界面组件承载异步身份切换。 */
import { message } from '@/services/messageBridge'
import { useRecordStore } from '@/store/recordStore'
import {
  useActiveEncounterStore,
  setCurrentEncounterFromPatient,
} from '@/store/activeEncounterStore'
import api from '@/services/api'
import type { Patient } from '@/domain/medical'

interface FinalRecordSubmission {
  recordType: string
  recordContent: string
  patientName: string
  patientGender: string
  patientAge: string
  chiefComplaint: string
}

/** 返回值表示签发结果是否应用于当前编辑器；切患者后仍完成原提交但不改当前文书。 */
export async function submitFinalRecord({
  recordType,
  recordContent,
  patientName,
  patientGender,
  patientAge,
  chiefComplaint,
}: FinalRecordSubmission): Promise<boolean> {
  let encounterId = useActiveEncounterStore.getState().encounterId
  const startEncounterId = encounterId
  const inferredVisitType =
    recordType === 'outpatient' || recordType === 'emergency' ? recordType : 'inpatient'

  if (!encounterId) {
    const pName = patientName.trim() || chiefComplaint.slice(0, 6) + '患者' || '未知患者'
    // quick-start 返回结构：本组件仅消费 encounter_id + patient，其余字段透传
    const res = (await api.post('/encounters/quick-start', {
      patient_name: pName,
      gender: patientGender || 'unknown',
      age: patientAge.trim() ? parseInt(patientAge.trim()) : undefined,
      visit_type: inferredVisitType,
    })) as { encounter_id: string; patient: Patient }
    const newEncounterId: string = res.encounter_id
    encounterId = newEncounterId
    // 通过聚合 helper 一次性 upsert 到 patientCacheStore + setActive 到指针 store
    // 创建在途时可能已切到另一患者/文书，旧回包不能夺回当前工作台。
    // 原签发仍使用新建ID继续完成；只有原编辑上下文未变才绑定该接诊。
    if (
      useActiveEncounterStore.getState().encounterId === startEncounterId &&
      useRecordStore.getState().recordType === recordType
    ) {
      setCurrentEncounterFromPatient(res.patient, newEncounterId, {
        visitType: inferredVisitType,
      })
      // setActive会清空无接诊正文，此处保留医生已经确认提交的版本。
      useRecordStore.getState().setRecordContent(recordContent)
    }
  }

  const saveRes = (await api.post('/medical-records/quick-save', {
    encounter_id: encounterId,
    record_type: recordType,
    content: recordContent,
  })) as { submitted_at?: string | null; patient_snapshot?: Record<string, unknown> | null }

  // 签发响应只锁定发起时的文书，切患者或切文书后的迟到回包不能污染新编辑器。
  if (
    useActiveEncounterStore.getState().encounterId !== encounterId ||
    useRecordStore.getState().recordType !== recordType
  )
    return false
  // 服务端签发的是请求发出时的正文；外部状态恢复或切文书再返回可能改变
  // 当前正文，不能让新正文冒用旧签名。成功后明确展示实际签发版本。
  if (useRecordStore.getState().recordContent !== recordContent) {
    useRecordStore.getState().setRecordContent(recordContent)
    message.warning('签发期间正文发生变化，已恢复实际签发版本；如需更正请走病历修订')
  }
  // 使用签名时服务器冻结的首页；无需另发请求，避免已签发却因读取失败提示重试。
  useRecordStore.getState().setPatientSnapshot(saveRes.patient_snapshot ?? null)

  // 标记本地 isFinal=true：编辑器只读、auto-save 停摆，但接诊上下文保留
  // 不再 resetAllWorkbench——A 方案下转住院要求"先签发"，签发后立刻 reset
  // 会让医生失去转住院入口，形成"必须先签发→签发就清空→无法转住院"死循环。
  // 让医生显式选择下一步动作（转住院 / 新建接诊 / 登出），各动作自带 reset。
  // 签发时刻用服务器真值（2026-08-28 时间审计）：原空参回退 new Date()
  // ——医生电脑时钟错 1 小时，打印件"签发时间"就与签名哈希链锁定的
  // 法定时刻差 1 小时
  useRecordStore.getState().setFinal(true, saveRes.submitted_at ?? null)
  message.success('病历已签发，可继续转住院或开始下一位接诊')
  return true
}
