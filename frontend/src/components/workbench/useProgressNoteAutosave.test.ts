/**
 * 病程记录自动保存回归测试（2026-08-14 第七轮审计 #34）
 *
 * 最容易写错的一点：切换时间轴条目时，要把**上一条**的正文存到**上一条**的 id 上。
 * 如果用闭包捕获而不是 ref，那一刻组件的 content 已经被 useEffect 重置成新条目的
 * 内容了，自动保存会把新条目的正文写进旧条目——比不保存还糟。
 */
import { renderHook, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useProgressNoteAutosave } from './useProgressNoteAutosave'

vi.mock('@/services/api', () => ({
  default: { patch: vi.fn(() => Promise.resolve({})) },
}))

import api from '@/services/api'

const patchMock = api.patch as unknown as ReturnType<typeof vi.fn>

const base = {
  encounterId: 'enc-1',
  itemId: 'note-1',
  content: '',
  recordedAt: null,
  disabled: false,
}

beforeEach(() => {
  patchMock.mockClear()
  vi.useFakeTimers()
})

describe('useProgressNoteAutosave', () => {
  it('首次水合不触发回写', () => {
    renderHook(() => useProgressNoteAutosave({ ...base, content: '已有正文' }))
    act(() => {
      vi.advanceTimersByTime(10_000)
    })
    expect(patchMock).not.toHaveBeenCalled()
  })

  it('正文变化后 5 秒自动落库', async () => {
    const { rerender } = renderHook(props => useProgressNoteAutosave(props), {
      initialProps: { ...base, content: '初始' },
    })
    rerender({ ...base, content: '医生新写的内容' })

    await act(async () => {
      vi.advanceTimersByTime(5_000)
    })

    expect(patchMock).toHaveBeenCalledTimes(1)
    expect(patchMock.mock.calls[0][0]).toBe('/encounters/enc-1/progress-notes/note-1')
    expect(patchMock.mock.calls[0][1]).toMatchObject({ content: '医生新写的内容' })
  })

  it('连续输入只在停下来之后落一次（尾防抖）', async () => {
    const { rerender } = renderHook(props => useProgressNoteAutosave(props), {
      initialProps: { ...base, content: '初始' },
    })
    rerender({ ...base, content: '一' })
    act(() => vi.advanceTimersByTime(2_000))
    rerender({ ...base, content: '一二' })
    act(() => vi.advanceTimersByTime(2_000))
    rerender({ ...base, content: '一二三' })

    await act(async () => {
      vi.advanceTimersByTime(5_000)
    })

    expect(patchMock).toHaveBeenCalledTimes(1)
    expect(patchMock.mock.calls[0][1]).toMatchObject({ content: '一二三' })
  })

  it('切换条目时把上一条的正文存到上一条的 id 上', async () => {
    const { rerender } = renderHook(props => useProgressNoteAutosave(props), {
      initialProps: { ...base, content: '初始' },
    })
    // 医生在 note-1 里写了东西，还没到 5 秒就点了时间轴上的另一份文书
    rerender({ ...base, content: 'note-1 写了一半的内容' })
    await act(async () => {
      rerender({ ...base, itemId: 'note-2', content: 'note-2 的原有内容' })
    })

    expect(patchMock).toHaveBeenCalledTimes(1)
    expect(patchMock.mock.calls[0][0]).toBe('/encounters/enc-1/progress-notes/note-1')
    expect(patchMock.mock.calls[0][1]).toMatchObject({
      content: 'note-1 写了一半的内容',
    })
  })

  it('卸载时立即 flush，不等防抖', async () => {
    const { rerender, unmount } = renderHook(props => useProgressNoteAutosave(props), {
      initialProps: { ...base, content: '初始' },
    })
    rerender({ ...base, content: '关标签页前写的内容' })

    await act(async () => {
      unmount()
    })

    expect(patchMock).toHaveBeenCalledTimes(1)
    expect(patchMock.mock.calls[0][1]).toMatchObject({
      content: '关标签页前写的内容',
    })
  })

  it('只读（已签发）时完全不落库', async () => {
    const { rerender } = renderHook(props => useProgressNoteAutosave(props), {
      initialProps: { ...base, content: '初始', disabled: true },
    })
    rerender({ ...base, content: '改动', disabled: true })

    await act(async () => {
      vi.advanceTimersByTime(10_000)
    })

    expect(patchMock).not.toHaveBeenCalled()
  })

  it('内容没变不重复回写', async () => {
    const { rerender } = renderHook(props => useProgressNoteAutosave(props), {
      initialProps: { ...base, content: '初始' },
    })
    rerender({ ...base, content: '改过一次' })
    await act(async () => {
      vi.advanceTimersByTime(5_000)
    })
    expect(patchMock).toHaveBeenCalledTimes(1)

    // 再触发一次渲染但内容不变
    rerender({ ...base, content: '改过一次' })
    await act(async () => {
      vi.advanceTimersByTime(5_000)
    })
    expect(patchMock).toHaveBeenCalledTimes(1)
  })
})
