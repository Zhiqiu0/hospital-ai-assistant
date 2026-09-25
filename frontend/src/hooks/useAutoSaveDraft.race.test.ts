/** 临时审计回归：旧文书保存晚返回时，不得污染同接诊新文书。 */
import { renderHook, act, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
vi.mock('@/services/api', () => ({ default: { post: vi.fn() } }))
vi.mock('@/services/draftQueue', () => ({
  enqueueDraft: vi.fn(),
  flushDraftQueue: vi.fn(),
  removeDraftByKey: vi.fn(),
}))
vi.mock('@/services/messageBridge', () => ({ message: { warning: vi.fn() } }))
import api from '@/services/api'
import { useAutoSaveDraft } from '@/hooks/useAutoSaveDraft'
import { useRecordStore } from '@/store/recordStore'
import { enqueueDraft } from '@/services/draftQueue'
const post = vi.mocked(api.post)
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.resetAllMocks()
})
it('旧入院记录响应晚到时，首程下一次保存不携带入院记录基线', async () => {
  vi.useFakeTimers()
  let finishOld!: (value: unknown) => void
  post.mockImplementationOnce(
    () =>
      new Promise(resolve => {
        finishOld = resolve
      })
  )
  post.mockResolvedValue({ updated_at: 'first-course-time' })
  const base = {
    encounterId: 'audit-enc',
    recordType: 'admission_note',
    recordContent: '',
    isFinal: false,
  }
  const { rerender, result } = renderHook(props => useAutoSaveDraft(props), { initialProps: base })
  rerender({ ...base, recordContent: '审计入院记录' })
  await act(async () => {
    vi.advanceTimersByTime(5000)
  })
  // 入院保存请求仍在途中，切换到同一接诊首程。
  rerender({ ...base, recordType: 'first_course_record', recordContent: '审计首程' })
  await act(async () => {
    finishOld({ updated_at: 'old-admission-time' })
  })
  expect(result.current.savingState).toBe('idle')
  expect(useRecordStore.getState().lastSavedContent).not.toBe('审计入院记录')
  // 继续编辑首程，观察新请求基线是否仍是旧入院文书。
  rerender({ ...base, recordType: 'first_course_record', recordContent: '审计首程继续编辑' })
  await act(async () => {
    vi.advanceTimersByTime(5000)
  })
  const next = post.mock.calls[1][1]
  if (!next) throw new Error('首程未发送保存请求')
  expect(next).toMatchObject({ record_type: 'first_course_record', expected_updated_at: null })
})

it.each([409, 403, 500, 'queue-failed'])(
  '旧文书失败 %s 不改当前保存状态与强制覆盖标记',
  async status => {
    vi.useFakeTimers()
    let rejectOld!: (reason: unknown) => void
    post.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectOld = reject
        })
    )
    post.mockResolvedValue({ updated_at: 'new-time' })
    if (status === 'queue-failed')
      vi.mocked(enqueueDraft).mockRejectedValueOnce(new Error('本机队列失败'))
    const base = {
      encounterId: 'race-enc',
      recordType: 'admission_note',
      recordContent: '旧入院记录',
      isFinal: false,
    }
    const { rerender, result } = renderHook(props => useAutoSaveDraft(props), {
      initialProps: base,
    })
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    rerender({ ...base, recordType: 'first_course_record', recordContent: '新首程' })
    await act(async () => {
      rejectOld({ status: typeof status === 'number' ? status : 500 })
    })
    expect(result.current.savingState).toBe('idle')
    expect(result.current.savedAt).toBe(0)
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    expect(post.mock.calls[1][1]).toMatchObject({
      record_type: 'first_course_record',
      force_overwrite: false,
      expected_updated_at: null,
    })
    if (status === 500 || status === 'queue-failed')
      expect(enqueueDraft).toHaveBeenCalledWith(
        expect.objectContaining({ record_type: 'admission_note' })
      )
  }
)
