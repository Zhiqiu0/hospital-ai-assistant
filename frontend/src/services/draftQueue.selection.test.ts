/** 离线同类型多稿必须分别排队和补传，成功清理不能误删另一份。 */
import { afterEach, expect, it, vi } from 'vitest'
import { enqueueDraft, flushDraftQueue, removeDraftByKey } from './draftQueue'

afterEach(() => vi.unstubAllGlobals())

it('同接诊同类型两个ID各自重放，保留旧格式队列兼容', async () => {
  const rows = new Map<string, unknown>()
  // 最小 IDB 请求适配器只模拟异步事务，实际键生成、入队、补传均跑生产实现。
  const request = (result?: unknown) => {
    const req = { result, onsuccess: null as (() => void) | null }
    queueMicrotask(() => req.onsuccess?.())
    return req
  }
  const storage = {
    put: (row: { id: string }) => {
      rows.set(row.id, row)
      return request()
    },
    getAll: () => request([...rows.values()]),
    delete: (id: string) => {
      rows.delete(id)
      return request()
    },
  }
  vi.stubGlobal('indexedDB', {
    open: () => request({ transaction: () => ({ objectStore: () => storage }) }),
  })
  const base = { encounter_id: 'enc', record_type: 'course_record', expected_updated_at: null }
  await enqueueDraft({ ...base, record_id: 'A', content: '甲旧稿' })
  await enqueueDraft({ ...base, record_id: 'B', content: '乙稿' })
  await enqueueDraft({ ...base, record_id: 'A', content: '甲新稿' })
  await enqueueDraft({ ...base, content: '旧格式草稿' })
  expect(rows.size).toBe(3)
  await removeDraftByKey('enc', 'course_record', 'A')
  const sender = vi.fn().mockResolvedValue(true)
  await flushDraftQueue(sender)
  expect(sender).toHaveBeenCalledWith(expect.objectContaining({ record_id: 'B', content: '乙稿' }))
  expect(sender).toHaveBeenCalledWith(
    expect.objectContaining({ record_id: undefined, content: '旧格式草稿' })
  )
  expect(sender).toHaveBeenCalledTimes(2)
  expect(rows.size).toBe(0)
})
