/** 诊断预览的请求归属、确认失效和医院回写限制。 */
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
vi.mock('@/services/api', () => ({ default: { post: vi.fn() } }))
import api from '@/services/api'
import { useDiagnosisConfirmation } from './useDiagnosisConfirmation'

const preview = {
  diagnoses: [{ name: '合成诊断', category: 'western', is_primary: true, code: 'A01' }],
  requires_confirmation: true,
  projection_error: null,
  his_writeback_required: true,
}
const input = {
  open: true,
  content: '【诊断】合成诊断',
  recordType: 'outpatient',
  encounterId: 'a',
  recordId: 'r',
  selectionVersion: 0,
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.useFakeTimers()
  vi.mocked(api.post).mockResolvedValue(preview)
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})
// 仅推进预览输入合并的定时器，不依赖真实时间等待。
async function load() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(250)
  })
}

it('已匹配主诊断仍需手动确认，改变主诊断会再次清除确认', async () => {
  const { result } = renderHook(() => useDiagnosisConfirmation(input))
  await load()
  expect(result.current.primary).toBe(0)
  expect(result.current.canSubmit).toBe(false)
  act(() => result.current.setConfirmed(true))
  expect(result.current.canSubmit).toBe(true)
  expect(result.current.diagnoses).toEqual([
    { name: '合成诊断', category: 'western', is_primary: true },
  ])
  act(() => result.current.selectPrimary(0))
  expect(result.current.canSubmit).toBe(false)
})
it('有诊断但没有主诊断时不能确认，选择后才可提交', async () => {
  vi.mocked(api.post).mockResolvedValue({
    ...preview,
    diagnoses: [{ ...preview.diagnoses[0], is_primary: false }],
  })
  const { result } = renderHook(() => useDiagnosisConfirmation(input))
  await load()
  expect(result.current.canConfirm).toBe(false)
  act(() => {
    result.current.selectPrimary(0)
    result.current.setConfirmed(true)
  })
  expect(result.current.canSubmit).toBe(true)
})
it.each([true, false])('正文无法解析时，医院来源=%s 的提交限制准确', async his => {
  vi.mocked(api.post).mockResolvedValue({
    ...preview,
    diagnoses: [],
    projection_error: '请补充诊断标题',
    his_writeback_required: his,
  })
  const { result } = renderHook(() => useDiagnosisConfirmation(input))
  await load()
  act(() => result.current.setConfirmed(true))
  expect(result.current.canSubmit).toBe(!his)
  expect(result.current.diagnoses).toBeUndefined()
})
it('预览失败必须重试成功并重新确认', async () => {
  vi.mocked(api.post).mockRejectedValueOnce(new Error('合成断网'))
  const { result } = renderHook(() => useDiagnosisConfirmation(input))
  await load()
  expect(result.current.error).toContain('失败')
  expect(result.current.canSubmit).toBe(false)
  act(() => result.current.reload())
  await load()
  expect(result.current.error).toBe('')
  expect(result.current.canSubmit).toBe(false)
})
it('切走再返回相同文书后，旧预览晚返回也不能覆盖新结果', async () => {
  let finish!: (value: unknown) => void
  vi.mocked(api.post).mockImplementationOnce(
    () =>
      new Promise(resolve => {
        finish = resolve
      })
  )
  const { result, rerender } = renderHook(props => useDiagnosisConfirmation(props), {
    initialProps: input,
  })
  await load()
  rerender({ ...input, encounterId: 'b', selectionVersion: 1 })
  await load()
  rerender({ ...input, selectionVersion: 2 })
  await load()
  act(() => result.current.setConfirmed(true))
  await act(async () =>
    finish({ ...preview, diagnoses: [{ name: '旧预览诊断', is_primary: true }] })
  )
  expect(result.current.diagnoses?.[0].name).toBe('合成诊断')
  expect(result.current.canSubmit).toBe(true)
})
