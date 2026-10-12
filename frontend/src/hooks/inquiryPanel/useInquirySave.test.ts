/** 门急诊保存回归：失败不能标记已保存，慢响应不能覆盖切换或继续编辑后的表单。 */
import { act, cleanup, renderHook } from '@testing-library/react'
import type { FormInstance } from 'antd'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
vi.mock('@/services/api', () => ({ default: { put: vi.fn(), post: vi.fn() } }))
vi.mock('@/services/messageBridge', () => ({ message: { success: vi.fn(), error: vi.fn() } }))
import api from '@/services/api'
import { message } from '@/services/messageBridge'
import { useInquirySave } from './useInquirySave'
import { useInquiryStore } from '@/store/inquiryStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useDiagnosisEntriesStore } from '@/store/diagnosisEntriesStore'
import { useRecordStore } from '@/store/recordStore'

const values = { chief_complaint: '合成主诉', western_diagnosis: '合成诊断' }
let formValues: Record<string, unknown>
const form = {
  getFieldsValue: () => ({ ...formValues }),
  setFieldsValue: (data: Record<string, unknown>) => Object.assign(formValues, data),
  // 本组测试仅使用读写值接口，其余 antd 表单能力不参与保存链路。
} as unknown as FormInstance
const setIsDirty = vi.fn()
const setPendingGenerate = vi.fn()
const setRecordContent = vi.fn()
// 订阅真实 store，让切接诊和基线写入引起的重渲染与工作台一致。
function useTestSave(recordContent = '') {
  const { inquiry, setInquiry } = useInquiryStore()
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  return useInquirySave({
    form,
    inquiry,
    setInquiry,
    currentEncounterId,
    recordContent,
    setRecordContent,
    setPendingGenerate,
    isEmergency: false,
    isDirty: true,
    setIsDirty,
    profileDirty: false,
    currentPatient: null,
  })
}
beforeEach(() => {
  vi.resetAllMocks()
  formValues = { ...values }
  useInquiryStore.getState().reset()
  useActiveEncounterStore.setState({ encounterId: 'test-a' })
  useDiagnosisEntriesStore.getState().setEntries([])
  vi.mocked(api.put).mockResolvedValue({})
  vi.mocked(api.post).mockResolvedValue({})
})
afterEach(cleanup)

it.each([false, true])(
  '保存中切换文书，切回=%s，不触发新选择的正文联动',
  async returnToOriginal => {
    useRecordStore.setState({
      recordType: 'outpatient',
      selectedRecordId: 'record-a',
      selectionVersion: 0,
    })
    let finish!: (value: unknown) => void
    vi.mocked(api.put).mockImplementationOnce(
      () =>
        new Promise(resolve => {
          finish = resolve
        })
    )
    const { result } = renderHook(() => useTestSave())
    let saving!: Promise<void>
    act(() => {
      saving = result.current.onSave(values)
    })
    act(() => {
      useRecordStore.getState().selectRecord('outpatient', 'record-b')
      if (returnToOriginal) useRecordStore.getState().selectRecord('outpatient', 'record-a')
    })
    await act(async () => {
      finish({})
      await saving
    })
    expect(setPendingGenerate).not.toHaveBeenCalled()
    expect(setRecordContent).not.toHaveBeenCalled()
    expect(useInquiryStore.getState().inquirySavedAt).toBeGreaterThan(0)
  }
)

it('规范化与保存期间切换文书，不同步旧文书章节到当前选择', async () => {
  useRecordStore.setState({ recordType: 'outpatient', selectedRecordId: 'record-a' })
  let finish!: (value: unknown) => void
  vi.mocked(api.put).mockImplementationOnce(
    () =>
      new Promise(resolve => {
        finish = resolve
      })
  )
  const { result } = renderHook(() => useTestSave('【主诉】\n旧正文'))
  let saving!: Promise<void>
  await act(async () => {
    saving = result.current.onSave(values)
  })
  act(() => {
    useRecordStore.getState().selectRecord('outpatient', 'record-b')
  })
  await act(async () => {
    finish({})
    await saving
  })
  expect(setRecordContent).not.toHaveBeenCalled()
})

it.each([1, 2])('第 %s 个保存接口失败保留草稿，重试后才更新基线', async failureAt => {
  const { result } = renderHook(() => useTestSave())
  if (failureAt === 2) vi.mocked(api.put).mockResolvedValueOnce({})
  vi.mocked(api.put).mockRejectedValueOnce(new Error('合成错误'))
  await act(async () => result.current.onSave(values))
  expect(useInquiryStore.getState().inquirySavedAt).toBe(0)
  expect(useInquiryStore.getState().lastSavedInquiryJson).toBeNull()
  expect(useInquiryStore.getState().inquiry.chief_complaint).toBe(values.chief_complaint)
  expect(setIsDirty).not.toHaveBeenCalledWith(false)
  await act(async () => result.current.onSave(values))
  expect(useInquiryStore.getState().inquirySavedAt).toBeGreaterThan(0)
})
it('规范化晚响应不得写入另一个接诊的表单', async () => {
  let resolve!: (value: unknown) => void
  vi.mocked(api.post).mockImplementationOnce(
    () =>
      new Promise(done => {
        resolve = done
      })
  )
  const { result } = renderHook(() => useTestSave('【主诉】旧正文'))
  let saving!: Promise<void>
  act(() => {
    saving = result.current.onSave(values)
  })
  act(() => {
    useActiveEncounterStore.setState({ encounterId: 'test-b' })
    formValues = { chief_complaint: '新接诊内容' }
  })
  await act(async () => {
    resolve({ fields: { chief_complaint: '旧接诊规范化' } })
    await saving
  })
  expect(formValues.chief_complaint).toBe('新接诊内容')
  expect(api.put).not.toHaveBeenCalled()
})
it('保存期间继续编辑不能清除未保存标记或触发生成', async () => {
  let resolve!: (value: unknown) => void
  vi.mocked(api.put).mockImplementationOnce(
    () =>
      new Promise(done => {
        resolve = done
      })
  )
  const { result } = renderHook(() => useTestSave())
  let saving!: Promise<void>
  act(() => {
    saving = result.current.onSave(values)
  })
  formValues.chief_complaint = '继续编辑的主诉'
  await act(async () => {
    resolve({})
    await saving
  })
  expect(setIsDirty).not.toHaveBeenCalledWith(false)
  expect(setPendingGenerate).not.toHaveBeenCalled()
  expect(useInquiryStore.getState().inquirySavedAt).toBe(0)
})
it('切接诊后旧保存失败不在新接诊弹出错误', async () => {
  let reject!: (value: unknown) => void
  vi.mocked(api.put).mockImplementationOnce(
    () =>
      new Promise((_done, fail) => {
        reject = fail
      })
  )
  const { result } = renderHook(() => useTestSave())
  let saving!: Promise<void>
  act(() => {
    saving = result.current.onSave(values)
  })
  act(() => {
    useActiveEncounterStore.setState({ encounterId: 'test-b' })
  })
  await act(async () => {
    reject({ status: 422, detail: '旧接诊字段错误' })
    await saving
  })
  expect(message.error).not.toHaveBeenCalled()
})
