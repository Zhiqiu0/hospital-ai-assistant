/** 读取签发状态期间卸载工作台，不得把尚未确认的缓存正文自动提交。 */
import { cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
vi.mock('@/services/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/services/draftQueue', () => ({
  enqueueDraft: vi.fn(),
  flushDraftQueue: vi.fn(),
  removeDraftByKey: vi.fn(),
}))
vi.mock('@/services/messageBridge', () => ({ message: { warning: vi.fn(), error: vi.fn() } }))
import api from '@/services/api'
import { useRecordStore } from '@/store/recordStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useAutoSaveDraft } from './useAutoSaveDraft'
import { useDraftByTypeLoader } from './useDraftByTypeLoader'
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.resetAllMocks()
})
it('签发状态读取未完成时卸载，不冲刷首次挂载遗留的缓存待保存项', () => {
  vi.useFakeTimers()
  vi.mocked(api.get).mockImplementation(() => new Promise(() => {}))
  vi.mocked(api.post).mockResolvedValue({})
  useRecordStore.getState().reset()
  useRecordStore.setState({ recordContent: '合成缓存正文', recordType: 'admission_note' })
  useActiveEncounterStore.setState({ encounterId: 'loading-test' })
  const { unmount } = renderHook(() => {
    const state = useRecordStore()
    // 调用顺序与 RecordEditor 一致，复现挂载时先排防抖再进入读取门禁。
    useAutoSaveDraft({
      encounterId: 'loading-test',
      recordType: state.recordType,
      recordContent: state.recordContent,
      isFinal: state.isFinal,
    })
    useDraftByTypeLoader('loading-test', state.recordType)
  })
  expect(useRecordStore.getState().recordLoading).toBe(true)
  unmount()
  expect(api.post).not.toHaveBeenCalled()
})
