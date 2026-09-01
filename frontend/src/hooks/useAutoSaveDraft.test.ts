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

  // ── 文书类型切换（2026-08-21 第四轮走查）─────────────────────────────
  // 后端草稿按 (encounter, record_type) 分行，乐观锁基线必须跟着类型走；
  // 旧实现基线是单值，住院切文书后拿旧类型行的 updated_at 校验新类型的行 → 假 409
  it('切文书类型时：旧类型草稿用旧基线落对行，新类型首发不带过期基线', async () => {
    const inpatient = { ...base, recordType: 'admission_note' }
    const { rerender } = renderHook(props => useAutoSaveDraft(props), {
      initialProps: { ...inpatient },
    })
    // 写入院记录并等防抖落库（拿到 updated_at 基线）
    rerender({ ...inpatient, recordContent: '入院记录正文' })
    await act(async () => {
      vi.advanceTimersByTime(5_000)
    })
    // 切到首程接着写，再落库
    rerender({ ...inpatient, recordType: 'first_course_record', recordContent: '首程正文' })
    await act(async () => {
      vi.advanceTimersByTime(5_000)
    })

    const saved = postMock.mock.calls
      .filter(c => c[0] === '/medical-records/auto-save-draft')
      .map(
        c => c[1] as { record_type: string; content: string; expected_updated_at: string | null }
      )
    expect(saved).toHaveLength(2)
    expect(saved[0].record_type).toBe('admission_note')
    expect(saved[0].content).toBe('入院记录正文')
    // 首程首发绝不能带入院记录行的 updated_at 当乐观锁（那会假 409）
    expect(saved[1].record_type).toBe('first_course_record')
    expect(saved[1].content).toBe('首程正文')
    expect(saved[1].expected_updated_at).toBeNull()
  })

  it('生成完成同步基线后：相同内容不重发，后续编辑带落库基线（不假409）', async () => {
    const { useRecordAutoSaveTrigger } = await import('@/store/recordAutoSaveTrigger')
    const inpatient = { ...base, recordType: 'course_record' }
    const { rerender } = renderHook(props => useAutoSaveDraft(props), {
      initialProps: { ...inpatient },
    })
    // AI 流式生成把内容写进编辑器（防抖开始计时）……
    rerender({ ...inpatient, recordContent: 'AI 生成的病程全文' })
    // ……done 事件带回 save_ai_draft 的落库时间，同步基线
    await act(async () => {
      useRecordAutoSaveTrigger.getState().syncBaseline('2026-08-21T13:00:00', 'AI 生成的病程全文')
    })
    // 防抖到期：内容与已落库基线相同 → 不应重发
    await act(async () => {
      vi.advanceTimersByTime(5_000)
    })
    expect(savedPayloads()).toHaveLength(0)

    // 医生接着编辑 → 发出的请求必须带落库基线（旧基线会被后端判假 409）
    rerender({ ...inpatient, recordContent: 'AI 生成的病程全文，医生补了一句' })
    await act(async () => {
      vi.advanceTimersByTime(5_000)
    })
    const saved = postMock.mock.calls
      .filter(c => c[0] === '/medical-records/auto-save-draft')
      .map(c => c[1] as { expected_updated_at: string | null })
    expect(saved).toHaveLength(1)
    expect(saved[0].expected_updated_at).toBe('2026-08-21T13:00:00')
  })

  it('切文书类型时防抖中的旧类型内容被抢救落盘，不丢也不错行', async () => {
    const inpatient = { ...base, recordType: 'admission_note' }
    const { rerender } = renderHook(props => useAutoSaveDraft(props), {
      initialProps: { ...inpatient },
    })
    // 写了入院记录，5 秒防抖没到就切到日常病程
    rerender({ ...inpatient, recordContent: '还没落库的入院内容' })
    await act(async () => {
      rerender({ ...inpatient, recordType: 'course_record', recordContent: '' })
    })

    const saved = postMock.mock.calls
      .filter(c => c[0] === '/medical-records/auto-save-draft')
      .map(c => c[1] as { record_type: string; content: string })
    expect(saved).toHaveLength(1)
    expect(saved[0].record_type).toBe('admission_note')
    expect(saved[0].content).toBe('还没落库的入院内容')
  })
})

// ─── 400 视为永久性拒绝（2026-09-02 住院支线实测补）───────────────────────
//
// 给后端加了「文书类型必须与就诊类型相容」的守卫后，存量脏数据（住院接诊挂着
// outpatient 病历）立刻让 auto-save 每 5 秒 400 一次，而 400 当时不在永久拒绝
// 名单里 → 全部进重试队列 → 队列条目永远补发不成功，后续草稿全堵在它后面。
// 守卫本身是对的，但不配前端这一手，就等于把 2026-08-13 修过的「草稿链路被
// 永久毒化」又造了一遍。
describe('永久性拒绝不得进重试队列', () => {
  it('400 不入队列，并把后端说明透传给医生', async () => {
    const { enqueueDraft, removeDraftByKey } = await import('@/services/draftQueue')
    const { message } = await import('@/services/messageBridge')
    ;(enqueueDraft as ReturnType<typeof vi.fn>).mockClear()
    ;(message.warning as ReturnType<typeof vi.fn>).mockClear()
    postMock.mockRejectedValueOnce({
      status: 400,
      detail: '文书类型与就诊类型不符：这是一次住院接诊，不能写入「outpatient」类文书。',
    })

    const { rerender } = renderHook(p => useAutoSaveDraft(p), { initialProps: base })
    rerender({ ...base, recordContent: '医生写的内容' })
    await act(async () => {
      vi.advanceTimersByTime(6000)
      await Promise.resolve()
    })

    expect(enqueueDraft).not.toHaveBeenCalled()
    expect(removeDraftByKey).toHaveBeenCalled()
    const warned = (message.warning as ReturnType<typeof vi.fn>).mock.calls.flat().join(' ')
    expect(warned).toContain('文书类型与就诊类型不符')
  })

  it('网络类错误仍然入队列重试（不能误伤真正该重试的）', async () => {
    const { enqueueDraft } = await import('@/services/draftQueue')
    ;(enqueueDraft as ReturnType<typeof vi.fn>).mockClear()
    postMock.mockRejectedValueOnce({ status: 500 })

    const { rerender } = renderHook(p => useAutoSaveDraft(p), { initialProps: base })
    rerender({ ...base, recordContent: '断网时写的内容' })
    await act(async () => {
      vi.advanceTimersByTime(6000)
      await Promise.resolve()
    })

    expect(enqueueDraft).toHaveBeenCalled()
  })
})
