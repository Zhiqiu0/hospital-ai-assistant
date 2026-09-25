/** 隔离审计：保存后自动生成输入完整性，以及占位符回填覆盖。 */
import { renderHook, act, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { FormInstance } from 'antd'
vi.mock('@/services/api', () => ({
  default: { put: vi.fn().mockResolvedValue({}), post: vi.fn().mockResolvedValue({}) },
}))
vi.mock('@/services/messageBridge', () => ({
  message: { warning: vi.fn(), error: vi.fn(), success: vi.fn() },
}))
vi.mock('@/sentry', () => ({ reportCaught: vi.fn() }))
import { useInquirySave } from '@/hooks/inquiryPanel/useInquirySave'
import { useRecordGenerate } from '@/hooks/recordEditor/useRecordGenerate'
import { useRecordEditorShared } from '@/hooks/recordEditor/useRecordEditorShared'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordStore } from '@/store/recordStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
const original = {
  chief_complaint: '审计主诉完整内容',
  history_present_illness: '审计现病史完整内容',
}
afterEach(cleanup)
it('保存后自动生成 payload 保留刚提交主诉和现病史', async () => {
  useInquiryStore.getState().reset()
  useRecordStore.setState({ recordContent: '', recordType: 'outpatient', pendingGenerate: false })
  useActiveEncounterStore.setState({ encounterId: 'audit-enc', patientId: null })
  const runSSE = vi.fn().mockResolvedValue(undefined)
  const { result } = renderHook(() => {
    const i = useInquiryStore()
    const r = useRecordStore()
    useRecordGenerate({
      runSSE,
      fetchLatestRecord: vi.fn(),
      syncGeneratedRecordToInquiry: vi.fn(),
      token: null,
      buildRecordTaskPayload: vi.fn(),
    })
    return useInquirySave({
      form: { setFieldsValue: vi.fn() } as unknown as FormInstance,
      inquiry: i.inquiry,
      setInquiry: i.setInquiry,
      currentEncounterId: 'audit-enc',
      recordContent: r.recordContent,
      setRecordContent: r.setRecordContent,
      setPendingGenerate: r.setPendingGenerate,
      isEmergency: false,
      isDirty: true,
      setIsDirty: vi.fn(),
      profileDirty: false,
      currentPatient: null,
    })
  })
  await act(async () => {
    await result.current.onSave(original)
  })
  expect(runSSE).toHaveBeenCalledTimes(1)
  expect(runSSE.mock.calls[0][1]).toMatchObject(original)
})
it('LLM占位符不得覆盖已填问诊或把污染值标为已保存', async () => {
  useInquiryStore.getState().setInquiry({ ...useInquiryStore.getState().inquiry, ...original })
  const { result } = renderHook(() => useRecordEditorShared())
  await act(async () => {
    result.current.syncGeneratedRecordToInquiry(
      '【主诉】\n[未填写，需补充]\n【现病史】\n[未填写，需补充]'
    )
  })
  const state = useInquiryStore.getState()
  const persisted = JSON.parse(localStorage.getItem('medassist-inquiry')!)
  expect(state.inquiry).toMatchObject(original)
  expect(persisted.state.inquiry).toMatchObject(original)
  expect(JSON.parse(state.lastSavedInquiryJson!)).toMatchObject(original)
})

it('真实生成内容可回填，但问诊保存时间与服务端基线不变', async () => {
  useInquiryStore.getState().setInquiry({ ...useInquiryStore.getState().inquiry, ...original })
  const before = useInquiryStore.getState()
  const { result } = renderHook(() => useRecordEditorShared())
  await act(async () => {
    result.current.syncGeneratedRecordToInquiry('【主诉】\n生成的新主诉')
  })
  const after = useInquiryStore.getState()
  expect(after.inquiry.chief_complaint).toBe('生成的新主诉')
  expect(after.lastSavedInquiryJson).toBe(before.lastSavedInquiryJson)
  expect(after.inquirySavedAt).toBe(before.inquirySavedAt)
})
