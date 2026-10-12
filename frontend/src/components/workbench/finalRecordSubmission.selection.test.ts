/** 签发同类型多稿时保留请求身份，切走再切回不能接收旧签发结果。 */
import { beforeEach, expect, it, vi } from 'vitest'
import api from '@/services/api'
import { useRecordStore } from '@/store/recordStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { submitFinalRecord } from './finalRecordSubmission'

vi.mock('@/services/api', () => ({ default: { post: vi.fn() } }))
vi.mock('@/services/messageBridge', () => ({ message: { warning: vi.fn(), success: vi.fn() } }))

beforeEach(() => {
  vi.clearAllMocks()
  useRecordStore.getState().reset()
  useActiveEncounterStore.setState({ encounterId: 'enc' })
  useRecordStore.getState().selectRecord('course_record', 'A')
  useRecordStore.setState({ recordContent: '甲稿', recordLoading: false })
})

it('所选A精确提交，A→B→A后晚响应不得锁定重开的A', async () => {
  let finish!: (value: unknown) => void
  vi.mocked(api.post).mockImplementation(
    () =>
      new Promise(resolve => {
        finish = resolve
      })
  )
  const submitted = submitFinalRecord({
    recordType: 'course_record',
    recordContent: '甲稿',
    patientName: '',
    patientGender: '',
    patientAge: '',
    chiefComplaint: '',
  })
  expect(api.post).toHaveBeenCalledWith(
    '/medical-records/quick-save',
    expect.objectContaining({ record_id: 'A', content: '甲稿' })
  )
  useRecordStore.getState().selectRecord('course_record', 'B')
  useRecordStore.getState().selectRecord('course_record', 'A')
  finish({ submitted_at: '2026-10-12T12:00:00', patient_snapshot: { name: '旧快照' } })
  expect(await submitted).toBe(false)
  expect(useRecordStore.getState().isFinal).toBe(false)
  expect(useRecordStore.getState().patientSnapshot).toBeNull()
})

it('无接诊quick-start期间切A→B→A不得把新接诊和旧正文绑定回来', async () => {
  useRecordStore.getState().reset()
  useRecordStore.setState({ recordType: 'admission_note', recordContent: '提交原稿' })
  useActiveEncounterStore.setState({ encounterId: null, patientId: null })
  let finishStart!: (value: unknown) => void
  vi.mocked(api.post).mockImplementationOnce(
    () =>
      new Promise(resolve => {
        finishStart = resolve
      })
  )
  vi.mocked(api.post).mockResolvedValueOnce({ submitted_at: '2026-10-12T12:00:00' })
  const submitted = submitFinalRecord({
    recordType: 'admission_note',
    recordContent: '提交原稿',
    patientName: '合成患者',
    patientGender: 'male',
    patientAge: '30',
    chiefComplaint: '合成主诉',
  })
  useRecordStore.getState().setRecordType('course_record')
  useRecordStore.getState().setRecordType('admission_note')
  useRecordStore.getState().setRecordContent('切换后新编辑')
  finishStart({
    encounter_id: 'new-enc',
    patient: { id: 'new-p', name: '合成患者', gender: 'male' },
  })
  expect(await submitted).toBe(false)
  expect(useActiveEncounterStore.getState().encounterId).toBeNull()
  expect(useRecordStore.getState().recordContent).toBe('切换后新编辑')
  expect(useRecordStore.getState().isFinal).toBe(false)
})

it.each([false, true])('正常新建接诊后按当前选择接收签发结果（中途切换=%s）', async switched => {
  useRecordStore.getState().reset()
  useRecordStore.setState({ recordType: 'admission_note', recordContent: '提交原稿' })
  useActiveEncounterStore.setState({ encounterId: null, patientId: null })
  let finishSave!: (value: unknown) => void
  vi.mocked(api.post).mockResolvedValueOnce({
    encounter_id: 'new-enc',
    patient: { id: 'new-p', name: '合成患者', gender: 'male' },
  })
  vi.mocked(api.post).mockImplementationOnce(
    () =>
      new Promise(resolve => {
        finishSave = resolve
      })
  )
  const submitted = submitFinalRecord({
    recordType: 'admission_note',
    recordContent: '提交原稿',
    patientName: '合成患者',
    patientGender: 'male',
    patientAge: '30',
    chiefComplaint: '合成主诉',
  })
  await vi.waitFor(() => expect(finishSave).toBeTypeOf('function'))
  expect(useActiveEncounterStore.getState().encounterId).toBe('new-enc')
  // 接诊绑定引发的合法重置可继续签发，随后真实的选择切换必须使旧回包失效。
  if (switched) {
    useRecordStore.getState().setRecordType('course_record')
    useRecordStore.getState().setRecordType('admission_note')
    useRecordStore.getState().setRecordContent('切换后新编辑')
  }
  finishSave({ submitted_at: '2026-10-12T12:00:00' })
  expect(await submitted).toBe(!switched)
  expect(useRecordStore.getState().isFinal).toBe(!switched)
  expect(useRecordStore.getState().recordContent).toBe(switched ? '切换后新编辑' : '提交原稿')
})
