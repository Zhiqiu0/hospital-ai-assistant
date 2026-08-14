/**
 * 病历草稿 auto-save 抢救路径回归测试（2026-08-14 第七轮审计 #32）
 *
 * 修复前只有 5 秒尾防抖这一条路：医生敲完最后一个字的 5 秒内，只要切患者 /
 * 关标签页 / 退出登录，这段内容**从未被发出去过**——连失败队列都进不去
 * （入队发生在 performSave 失败时，而它压根没被调用）。
 * 查房时写完一个患者直接点下一个是常态，这个 5 秒窗口天天在踩。
 */
import { renderHook, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/services/api', () => ({
  default: {
    post: vi.fn(() => Promise.resolve({ updated_at: '2026-08-14T10:00:00' })),
    get: vi.fn(() => Promise.resolve({})),
  },
}))
vi.mock('@/services/draftQueue', () => ({
  enqueueDraft: vi.fn(() => Promise.resolve()),
  flushDraftQueue: vi.fn(() => Promise.resolve()),
  removeDraftByKey: vi.fn(() => Promise.resolve()),
}))
vi.mock('@/services/messageBridge', () => ({
  message: { warning: vi.fn(), error: vi.fn(), success: vi.fn(), info: vi.fn() },
}))

import api from '@/services/api'
import { useAutoSaveDraft } from './useAutoSaveDraft'

const postMock = api.post as unknown as ReturnType<typeof vi.fn>

/** 取所有落到 auto-save-draft 端点的请求体 */
function savedPayloads() {
  return postMock.mock.calls
    .filter(c => c[0] === '/medical-records/auto-save-draft')
    .map(c => c[1] as { encounter_id: string; content: string })
}

const base = {
  encounterId: 'enc-1',
  recordType: 'outpatient',
  recordContent: '',
  isFinal: false,
}

beforeEach(() => {
  postMock.mockClear()
  vi.useFakeTimers()
})

describe('useAutoSaveDraft 的抢救落盘', () => {
  it('切接诊时把上一份草稿存到上一个接诊，而不是新接诊', async () => {
    const { rerender } = renderHook(props => useAutoSaveDraft(props), {
      initialProps: { ...base },
    })
    // 医生写了内容，还没到 5 秒就点了下一个患者
    rerender({ ...base, recordContent: '张三的病历正文' })
    await act(async () => {
      rerender({ ...base, encounterId: 'enc-2', recordContent: '' })
    })

    const saved = savedPayloads()
    expect(saved).toHaveLength(1)
    expect(saved[0].encounter_id).toBe('enc-1')
    expect(saved[0].content).toBe('张三的病历正文')
  })

  it('关标签页（pagehide）时立即落盘', async () => {
    const { rerender } = renderHook(props => useAutoSaveDraft(props), {
      initialProps: { ...base },
    })
    rerender({ ...base, recordContent: '关页面前写的内容' })

    await act(async () => {
      window.dispatchEvent(new Event('pagehide'))
    })

    const saved = savedPayloads()
    expect(saved).toHaveLength(1)
    expect(saved[0].content).toBe('关页面前写的内容')
  })

  it('卸载（退出登录/路由跳走）时立即落盘', async () => {
    const { rerender, unmount } = renderHook(props => useAutoSaveDraft(props), {
      initialProps: { ...base },
    })
    rerender({ ...base, recordContent: '退出登录前写的内容' })

    await act(async () => {
      unmount()
    })

    const saved = savedPayloads()
    expect(saved).toHaveLength(1)
    expect(saved[0].content).toBe('退出登录前写的内容')
  })

  it('正常防抖仍然只发一次，不因抢救逻辑变成两次', async () => {
    const { rerender } = renderHook(props => useAutoSaveDraft(props), {
      initialProps: { ...base },
    })
    rerender({ ...base, recordContent: '慢慢写完的内容' })

    await act(async () => {
      vi.advanceTimersByTime(5_000)
    })

    expect(savedPayloads()).toHaveLength(1)
  })

  it('已签发的病历任何路径都不落盘', async () => {
    const { rerender, unmount } = renderHook(props => useAutoSaveDraft(props), {
      initialProps: { ...base, isFinal: true },
    })
    rerender({ ...base, recordContent: '签发后的改动', isFinal: true })
    await act(async () => {
      unmount()
    })

    expect(savedPayloads()).toHaveLength(0)
  })
})
