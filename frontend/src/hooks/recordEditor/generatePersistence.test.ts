/** AI 正文完成但落库失败时保留成果、提示医生，并让自动保存继续接管。 */
import { act, renderHook } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { useRecordGenerate } from './useRecordGenerate'
import { useRecordEditorShared } from './useRecordEditorShared'
import { useRecordStore } from '@/store/recordStore'
import { useInquiryStore } from '@/store/inquiryStore'
import { useRecordAutoSaveTrigger } from '@/store/recordAutoSaveTrigger'
import { streamSSE } from '@/services/streamSSE'
import { message } from '@/services/messageBridge'

vi.mock('@/services/streamSSE', () => ({ streamSSE: vi.fn() }))
vi.mock('@/services/messageBridge', () => ({ message: { warning: vi.fn(), error: vi.fn() } }))

it('done.warning不当作生成错误回滚，也不伪造已保存基线', async () => {
  useInquiryStore
    .getState()
    .setInquiry({ ...useInquiryStore.getState().inquiry, chief_complaint: '测试主诉' })
  useRecordStore.getState().setRecordContent('旧正文')
  const baseline = useRecordAutoSaveTrigger.getState().baselineSignal
  const warning = '病历已生成，但草稿保存失败，请检查保存状态并重试'
  vi.mocked(streamSSE).mockImplementation(async (_url, _body, _token, handlers) => {
    handlers.onChunk?.('【主诉】\n生成正文')
    handlers.onEvent?.({ type: 'done', saved: false, warning })
  })
  const { result } = renderHook(() => useRecordGenerate(useRecordEditorShared()))
  await act(async () => {
    await result.current.handleGenerate()
  })
  expect(useRecordStore.getState().recordContent).toBe('【主诉】\n生成正文')
  expect(useRecordStore.getState().isGenerating).toBe(false)
  expect(useRecordAutoSaveTrigger.getState().baselineSignal).toBe(baseline)
  expect(message.warning).toHaveBeenCalledWith(warning)
  expect(message.error).not.toHaveBeenCalled()
})
