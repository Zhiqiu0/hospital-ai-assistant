/** 住院问诊回归：月经史完整传递、失败保留草稿、慢请求不污染新接诊。 */
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
const { formValues, form } = vi.hoisted(() => {
  const formValues: Record<string, unknown> = {}
  return {
    formValues,
    form: {
      setFieldsValue: (values: Record<string, unknown>) => Object.assign(formValues, values),
      setFieldValue: (key: string, value: unknown) => {
        formValues[key] = value
      },
      getFieldValue: (key: string) => formValues[key],
      getFieldsValue: () => ({ ...formValues }),
    },
  }
})
vi.mock('antd', () => ({ Form: { useForm: () => [form] } }))
vi.mock('@/services/api', () => ({ default: { put: vi.fn() } }))
vi.mock('@/services/messageBridge', () => ({
  message: {
    warning: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
  },
}))
import api from '@/services/api'
import { message } from '@/services/messageBridge'
import { useInpatientInquiryPanel } from './useInpatientInquiryPanel'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useDiagnosisEntriesStore } from '@/store/diagnosisEntriesStore'
import { buildInpatientInquiryData } from '@/utils/inpatientInquirySync'
import { useRecordGenerate } from '@/hooks/recordEditor/useRecordGenerate'

const values = {
  chief_complaint: '合成测试主诉',
  tcm_disease_diagnosis: '合成诊断',
  menstrual_history: '规律',
}
beforeEach(() => {
  vi.resetAllMocks()
  Object.keys(formValues).forEach(key => delete formValues[key])
  useInquiryStore.getState().reset()
  useDiagnosisEntriesStore.getState().setEntries([])
  useRecordStore.setState({ recordContent: '', pendingGenerate: false, isPolishing: false })
  useActiveEncounterStore.setState({ encounterId: 'test-a' })
  vi.mocked(api.put).mockResolvedValue({})
})
afterEach(cleanup)

it.each([false, true])(
  '保存期间切换同接诊文书，切回=%s，也不得触发当前文书生成',
  async returnToOriginal => {
    useRecordStore.setState({
      recordType: 'admission_note',
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
    const { result } = renderHook(useInpatientInquiryPanel)
    let saving!: Promise<void>
    act(() => {
      saving = result.current.onSave(values)
    })
    act(() => {
      useRecordStore.getState().selectRecord('admission_note', 'record-b')
      if (returnToOriginal) useRecordStore.getState().selectRecord('admission_note', 'record-a')
      useRecordStore.setState({ recordContent: '当前所选文书已有正文', recordLoading: false })
    })
    await act(async () => {
      finish({})
      await saving
    })
    expect(useRecordStore.getState().pendingGenerate).toBe(false)
    expect(useRecordStore.getState().recordContent).toBe('当前所选文书已有正文')
    // 问诊仍归属同一接诊，应正常保存；只禁止旧文书的后续联动。
    expect(useInquiryStore.getState().inquirySavedAt).toBeGreaterThan(0)
  }
)

it('保存旧文书问诊期间切换文书，不把旧章节同步覆盖到新正文', async () => {
  useRecordStore.setState({
    recordContent: '【主诉】\n旧正文',
    recordType: 'admission_note',
    selectedRecordId: 'record-a',
  })
  let finish!: (value: unknown) => void
  vi.mocked(api.put).mockImplementationOnce(
    () =>
      new Promise(resolve => {
        finish = resolve
      })
  )
  const { result } = renderHook(useInpatientInquiryPanel)
  let saving!: Promise<void>
  act(() => {
    saving = result.current.onSave(values)
  })
  act(() => {
    useRecordStore.getState().selectRecord('admission_note', 'record-b')
    useRecordStore.setState({ recordContent: '新文书正文', recordLoading: false })
  })
  await act(async () => {
    finish({})
    await saving
  })
  expect(useRecordStore.getState().recordContent).toBe('新文书正文')
})

it('保存月经史后实际生成请求包含该字段，并可从服务端快照恢复回显', async () => {
  useRecordStore.setState({ recordType: 'admission_note' })
  useActiveEncounterStore.setState({ patientId: null, visitType: 'inpatient' })
  const runSSE = vi.fn().mockResolvedValue(undefined)
  const { result, unmount } = renderHook(() => {
    useRecordGenerate({
      runSSE,
      fetchLatestRecord: vi.fn(),
      syncGeneratedRecordToInquiry: vi.fn(),
      token: null,
      buildRecordTaskPayload: vi.fn(),
    })
    return useInpatientInquiryPanel()
  })
  await act(async () => {
    await result.current.onSave(values)
  })
  expect(api.put).toHaveBeenCalledWith(
    '/encounters/test-a/inquiry',
    expect.objectContaining({ menstrual_history: '规律' })
  )
  expect(runSSE).toHaveBeenCalledTimes(1)
  expect(runSSE.mock.calls[0][1]).toMatchObject({
    menstrual_history: '规律',
    record_type: 'admission_note',
  })
  // 用实际请求字段模拟服务端快照，重挂面板验证完整恢复路径。
  const snapshot = useInquiryStore.getState().inquiry
  unmount()
  useInquiryStore.getState().reset()
  useInquiryStore.getState().applyServerInquiry(snapshot)
  renderHook(useInpatientInquiryPanel)
  expect(formValues.menstrual_history).toBe('规律')
})

it('请求期间继续编辑时保留新输入和未保存提示', async () => {
  let resolve!: (value: unknown) => void
  vi.mocked(api.put).mockImplementationOnce(
    () =>
      new Promise(done => {
        resolve = done
      })
  )
  const { result } = renderHook(useInpatientInquiryPanel)
  let saving!: Promise<void>
  act(() => {
    form.setFieldsValue(values)
    saving = result.current.onSave(values)
  })
  act(() => {
    form.setFieldValue('menstrual_history', '新编辑')
    result.current.setIsDirty(true)
  })
  await act(async () => {
    resolve({})
    await saving
  })
  expect(formValues.menstrual_history).toBe('新编辑')
  expect(result.current.isDirty).toBe(true)
  expect(useRecordStore.getState().pendingGenerate).toBe(false)
})

it('构建保存请求时保留月经史，清空值也明确传递', () => {
  expect(buildInpatientInquiryData(values)).toHaveProperty('menstrual_history', '规律')
  expect(buildInpatientInquiryData({ menstrual_history: null })).toHaveProperty(
    'menstrual_history',
    ''
  )
})
it('恢复接诊时回显月经史，切换空白接诊时清除旧值', () => {
  useInquiryStore
    .getState()
    .updateInquiryFields({ ...useInquiryStore.getState().inquiry, menstrual_history: '规律' })
  renderHook(useInpatientInquiryPanel)
  expect(formValues.menstrual_history).toBe('规律')
  act(() => {
    useInquiryStore.getState().reset()
    useActiveEncounterStore.setState({ encounterId: 'test-b' })
  })
  expect(formValues.menstrual_history).toBe('')
})
it('语音月经史写入问诊草稿', () => {
  const { result } = renderHook(useInpatientInquiryPanel)
  act(() => result.current.applyVoiceInquiry({ menstrual_history: '规律' }))
  expect(useInquiryStore.getState().inquiry.menstrual_history).toBe('规律')
})
it.each([1, 2])('第 %s 个保存接口失败时不推进保存基线，并可重试', async failureAt => {
  const { result } = renderHook(useInpatientInquiryPanel)
  act(() => result.current.setIsDirty(true))
  if (failureAt === 2) vi.mocked(api.put).mockResolvedValueOnce({})
  vi.mocked(api.put).mockRejectedValueOnce(new Error('合成网络错误'))
  await act(async () => result.current.onSave(values))
  expect(useInquiryStore.getState().inquirySavedAt).toBe(0)
  expect(useInquiryStore.getState().lastSavedInquiryJson).toBeNull()
  expect(useInquiryStore.getState().inquiry.chief_complaint).toBe(values.chief_complaint)
  expect(result.current.isDirty).toBe(true)
  expect(message.success).not.toHaveBeenCalled()
  await act(async () => result.current.onSave(values))
  expect(useInquiryStore.getState().inquirySavedAt).toBeGreaterThan(0)
  expect(result.current.isDirty).toBe(false)
})
it('切换接诊后旧保存成功不得触发新接诊生成或推进基线', async () => {
  let resolve!: (value: unknown) => void
  vi.mocked(api.put).mockImplementationOnce(
    () =>
      new Promise(done => {
        resolve = done
      })
  )
  const { result } = renderHook(useInpatientInquiryPanel)
  let saving!: Promise<void>
  act(() => {
    saving = result.current.onSave(values)
  })
  act(() => {
    useInquiryStore.getState().reset()
    useActiveEncounterStore.setState({ encounterId: 'test-b' })
  })
  await act(async () => {
    resolve({})
    await saving
  })
  expect(useInquiryStore.getState().inquirySavedAt).toBe(0)
  expect(useRecordStore.getState().pendingGenerate).toBe(false)
  expect(message.success).not.toHaveBeenCalled()
})
