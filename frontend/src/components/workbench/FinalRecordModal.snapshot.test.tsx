/** 签发响应中的冻结首页必须立即用于导出，且迟到响应不得污染其他接诊。 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import FinalRecordModal from './FinalRecordModal'
import api from '@/services/api'
import { useRecordStore } from '@/store/recordStore'
import { useQCStore } from '@/store/qcStore'
import {
  setCurrentEncounterFromPatient,
  useActiveEncounterStore,
} from '@/store/activeEncounterStore'
import { message } from '@/services/messageBridge'

vi.mock('@/services/api', () => ({ default: { post: vi.fn() } }))
vi.mock('@/services/messageBridge', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

beforeEach(() => {
  vi.resetAllMocks()
  setCurrentEncounterFromPatient(
    { id: 'snapshot-p', name: '测试患者', gender: 'unknown' },
    'snapshot-e',
    { visitType: 'outpatient' }
  )
  useRecordStore.getState().reset()
  useRecordStore.getState().setRecordContent('已核实正文')
  useQCStore.setState({ qcPass: true, qcIssues: [], gradeScore: null })
})

it('签发后立即采用服务器冻结快照与服务器签发时间', async () => {
  const snapshot = { name: '冻结姓名', visit_type: 'outpatient' }
  vi.mocked(api.post).mockResolvedValue({
    submitted_at: '2026-09-26T01:00:00',
    patient_snapshot: snapshot,
  })
  render(<FinalRecordModal open onCancel={vi.fn()} />)
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: /确认签发/ }))
  await waitFor(() => expect(useRecordStore.getState().isFinal).toBe(true))
  expect(useRecordStore.getState().patientSnapshot).toEqual(snapshot)
  expect(new Date(useRecordStore.getState().finalizedAt!).getTime()).toBe(
    new Date('2026-09-26T01:00:00').getTime()
  )
})

it('签发期间切到其他接诊，旧响应不得冻结新患者编辑器', async () => {
  let finish!: (response: unknown) => void
  vi.mocked(api.post).mockImplementation(
    () =>
      new Promise(resolve => {
        finish = resolve
      })
  )
  render(<FinalRecordModal open onCancel={vi.fn()} />)
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: /确认签发/ }))
  act(() =>
    setCurrentEncounterFromPatient(
      { id: 'other-p', name: '下一患者', gender: 'unknown' },
      'other-e',
      { visitType: 'outpatient' }
    )
  )
  await act(async () => {
    finish({ submitted_at: '2026-09-26T01:00:00', patient_snapshot: { name: '旧患者' } })
  })
  expect(useRecordStore.getState().isFinal).toBe(false)
  expect(useRecordStore.getState().patientSnapshot).toBeNull()
})

it('签发请求提交后不能取消，避免误以为服务端签发已撤销', async () => {
  let finish!: (response: unknown) => void
  vi.mocked(api.post).mockImplementation(
    () =>
      new Promise(resolve => {
        finish = resolve
      })
  )
  const onCancel = vi.fn()
  render(<FinalRecordModal open onCancel={onCancel} />)
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: /确认签发/ }))
  const cancel = screen.getByRole('button', { name: /取\s*消/ })
  expect(cancel).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Close' })).toBeNull()
  fireEvent.click(cancel)
  expect(onCancel).not.toHaveBeenCalled()
  await act(async () => {
    finish({ submitted_at: '2026-09-26T01:00:00' })
  })
  expect(useRecordStore.getState().isFinal).toBe(true)
  expect(onCancel).toHaveBeenCalledTimes(1)
})

it('同文书发生外部变化时，签发成功必须展示实际已提交正文', async () => {
  let finish!: (response: unknown) => void
  vi.mocked(api.post).mockImplementation(
    () =>
      new Promise(resolve => {
        finish = resolve
      })
  )
  const { rerender } = render(<FinalRecordModal open onCancel={vi.fn()} />)
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: /确认签发/ }))
  // 模拟父组件关闭弹窗或切换文书后回来；迟到响应必须绑定提交时正文。
  rerender(<FinalRecordModal open={false} onCancel={vi.fn()} />)
  act(() => useRecordStore.getState().setRecordContent('未提交的正文B'))
  await act(async () => {
    finish({ submitted_at: '2026-09-26T01:00:00', patient_snapshot: { name: '冻结姓名' } })
  })
  expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ content: '已核实正文' })
  expect(useRecordStore.getState().isFinal).toBe(true)
  expect(useRecordStore.getState().recordContent).toBe('已核实正文')
  expect(useRecordStore.getState().patientSnapshot).toEqual({ name: '冻结姓名' })
  expect(message.warning).toHaveBeenCalled()
})

/** 真实无接诊界面通过必填姓名、性别、年龄后允许发起签发。 */
function startUnboundSubmission(recordType: string) {
  useActiveEncounterStore.getState().clearActive()
  useRecordStore.setState({ recordType, recordContent: '待创建接诊并签发的正文', isFinal: false })
  render(<FinalRecordModal open onCancel={vi.fn()} />)
  fireEvent.change(screen.getByPlaceholderText('患者姓名（必填）'), {
    target: { value: '无接诊测试患者' },
  })
  fireEvent.click(screen.getByRole('radio', { name: '男' }))
  fireEvent.change(screen.getByPlaceholderText('如：35'), { target: { value: '35' } })
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: /确认签发/ }))
}

it.each(['outpatient', 'emergency'])('无接诊%s文书签发时创建对应类型的接诊', async recordType => {
  vi.mocked(api.post)
    .mockResolvedValueOnce({
      encounter_id: 'new-final-e',
      patient: { id: 'new-final-p', name: '患者', gender: 'male' },
    })
    .mockResolvedValueOnce({ submitted_at: '2026-09-26T01:00:00' })
  startUnboundSubmission(recordType)
  await waitFor(() => expect(useRecordStore.getState().isFinal).toBe(true))
  expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ visit_type: recordType })
  expect(vi.mocked(api.post).mock.calls[1][1]).toMatchObject({
    record_type: recordType,
    encounter_id: 'new-final-e',
  })
})

it('创建接诊期间切到其他患者，不夺回当前指针但仍完成原先授权的签发', async () => {
  let finishStart!: (value: unknown) => void
  vi.mocked(api.post)
    .mockImplementationOnce(
      () =>
        new Promise(resolve => {
          finishStart = resolve
        })
    )
    .mockResolvedValueOnce({
      submitted_at: '2026-09-26T01:00:00',
      patient_snapshot: { name: '原患者' },
    })
  startUnboundSubmission('outpatient')
  act(() => {
    setCurrentEncounterFromPatient(
      { id: 'next-p', name: '下一患者', gender: 'unknown' },
      'next-e',
      { visitType: 'outpatient' }
    )
    useRecordStore.getState().setRecordContent('下一患者正文')
  })
  await act(async () => {
    finishStart({
      encounter_id: 'late-created-e',
      patient: { id: 'late-p', name: '原患者', gender: 'male' },
    })
  })
  expect(vi.mocked(api.post).mock.calls[1][1]).toMatchObject({
    encounter_id: 'late-created-e',
    content: '待创建接诊并签发的正文',
  })
  expect(useActiveEncounterStore.getState().encounterId).toBe('next-e')
  expect(useRecordStore.getState().recordContent).toBe('下一患者正文')
  expect(useRecordStore.getState().isFinal).toBe(false)
})
