/** 保存问诊触发的自动生成必须等待文书读取完成，不能在加载门禁中被吞掉。 */
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
vi.mock('@/services/messageBridge', () => ({ message: { warning: vi.fn(), error: vi.fn() } }))
import { useRecordGenerate } from './useRecordGenerate'
import { useRecordStore } from '@/store/recordStore'
import { useInquiryStore } from '@/store/inquiryStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
afterEach(cleanup)
it('读取期间收到待生成请求，读取成功后自动继续生成', async () => {
  useRecordStore.getState().reset()
  useRecordStore.setState({
    recordType: 'admission_note',
    recordLoading: true,
    pendingGenerate: true,
  })
  useActiveEncounterStore.setState({
    encounterId: 'generate-loading',
    patientId: null,
    visitType: 'inpatient',
  })
  useInquiryStore.getState().reset()
  useInquiryStore
    .getState()
    .setInquiry({ ...useInquiryStore.getState().inquiry, chief_complaint: '合成主诉' })
  const runSSE = vi.fn().mockResolvedValue(undefined)
  renderHook(() =>
    useRecordGenerate({
      runSSE,
      fetchLatestRecord: vi.fn(),
      syncGeneratedRecordToInquiry: vi.fn(),
      token: null,
      buildRecordTaskPayload: vi.fn(),
    })
  )
  expect(runSSE).not.toHaveBeenCalled()
  await act(async () => {
    useRecordStore.setState({ recordLoading: false })
  })
  expect(runSSE).toHaveBeenCalledTimes(1)
  expect(runSSE.mock.calls[0][1]).toMatchObject({ chief_complaint: '合成主诉' })
})
