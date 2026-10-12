/**
 * 多设备乐观锁基线回归（2026-09-02 并发实测）
 *
 * 原实现在「本地已有内容」时直接 return，那台设备根本不知道服务端版本号，
 * 乐观锁基线为 null，而后端对 expected_updated_at 为空的请求跳过校验直接
 * UPSERT。生产实测复现：诊室电脑写好整份病历并保存，平板（本地缓存里只有
 * 两个字）一次自动保存就把它整份顶掉，两边都是 200，医生毫无察觉。
 *
 * 「本地优先」是对的——不能打断正在写字的医生；但本地优先不等于不知道服务端
 * 到哪一版了。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))
vi.mock('@/services/messageBridge', () => ({
  message: { warning: vi.fn(), error: vi.fn(), success: vi.fn(), info: vi.fn() },
}))

import api from '@/services/api'
import { useDraftByTypeLoader } from './useDraftByTypeLoader'
import { useRecordStore } from '@/store/recordStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useRecordAutoSaveTrigger } from '@/store/recordAutoSaveTrigger'
import { useAutoSaveDraft } from './useAutoSaveDraft'

const getMock = api.get as unknown as ReturnType<typeof vi.fn>

const SERVER_DRAFT = {
  exists: true,
  record_id: 'rec-1',
  status: 'editing',
  content: '诊室电脑写的完整病历：主诉现病史既往史体格检查诊断处理意见',
  updated_at: '2026-09-02T03:45:01',
  submitted_at: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  useRecordStore.getState().reset()
  getMock.mockResolvedValue(SERVER_DRAFT)
  useActiveEncounterStore.setState({ encounterId: 'enc-1' })
  useRecordStore.setState({ recordContent: '', recordType: 'outpatient', isGenerating: false })
  useRecordAutoSaveTrigger.setState({ baselineSignal: 0, baselinePayload: null })
})

describe('useDraftByTypeLoader', () => {
  it('恢复缓存签发文书时仍恢复只读锁', async () => {
    useRecordStore.setState({ recordContent: '本机旧缓存', isFinal: false })
    getMock.mockResolvedValue({ ...SERVER_DRAFT, status: 'submitted' })
    renderHook(() => useDraftByTypeLoader('enc-1', 'outpatient'))
    await waitFor(() => expect(useRecordStore.getState().isFinal).toBe(true))
    expect(useRecordStore.getState().recordContent).toBe(SERVER_DRAFT.content)
  })

  it('同类型时间轴选择按文书 ID 拉取，不复用另一份缓存', async () => {
    useRecordStore.setState({ recordType: 'course_record', recordContent: '第一份' })
    useRecordStore.getState().selectRecord('course_record', 'rec-2')
    getMock.mockResolvedValue({ ...SERVER_DRAFT, record_id: 'rec-2', content: '第二份' })
    renderHook(() => useDraftByTypeLoader('enc-1', 'course_record'))
    await waitFor(() => expect(useRecordStore.getState().recordContent).toBe('第二份'))
    expect(getMock.mock.calls[0][0]).toContain('record_id=rec-2')
  })

  it('切A→B→A后旧A响应永久失效，缓存与签发状态各自恢复', async () => {
    let finishOld!: (value: unknown) => void
    getMock.mockImplementationOnce(
      () =>
        new Promise(resolve => {
          finishOld = resolve
        })
    )
    useRecordStore.getState().selectRecord('course_record', 'rec-A')
    renderHook(() => useDraftByTypeLoader('enc-1', 'course_record'))
    getMock.mockResolvedValueOnce({ ...SERVER_DRAFT, record_id: 'rec-B', content: '乙稿' })
    act(() => useRecordStore.getState().selectRecord('course_record', 'rec-B'))
    await waitFor(() => expect(useRecordStore.getState().recordContent).toBe('乙稿'))
    act(() => useRecordStore.getState().setRecordContent('乙未保存编辑'))
    getMock.mockResolvedValueOnce({
      ...SERVER_DRAFT,
      record_id: 'rec-A',
      content: '甲正式稿',
      status: 'submitted',
    })
    act(() => useRecordStore.getState().selectRecord('course_record', 'rec-A'))
    await waitFor(() => expect(useRecordStore.getState().recordContent).toBe('甲正式稿'))
    await act(async () => {
      finishOld({ ...SERVER_DRAFT, record_id: 'rec-A', content: '甲旧响应' })
    })
    expect(useRecordStore.getState().recordContent).toBe('甲正式稿')
    expect(useRecordStore.getState().isFinal).toBe(true)
    getMock.mockResolvedValueOnce({ ...SERVER_DRAFT, record_id: 'rec-B', content: '乙稿' })
    act(() => useRecordStore.getState().selectRecord('course_record', 'rec-B'))
    await waitFor(() => expect(useRecordStore.getState().recordLoading).toBe(false))
    expect(useRecordStore.getState().recordContent).toBe('乙未保存编辑')
    expect(useRecordStore.getState().isFinal).toBe(false)
  })

  it('选中文书加载失败保留门禁，不把缓存当可保存的新稿', async () => {
    getMock.mockRejectedValue(new Error('离线'))
    useRecordStore.getState().selectRecord('course_record', 'rec-A')
    renderHook(() => useDraftByTypeLoader('enc-1', 'course_record'))
    await act(async () => {})
    expect(useRecordStore.getState().recordLoading).toBe(true)
  })

  it('刷新缓存时读取未完成，pagehide和卸载均不得抢救上传未经确认的签发缓存', async () => {
    getMock.mockReturnValue(new Promise(() => {}))
    useRecordStore.setState({ recordContent: '待确认旧缓存' })
    const hook = renderHook(() => {
      const state = useRecordStore()
      // 复现真实编辑器挂载顺序：先自动保存，再发起草稿读取。
      useAutoSaveDraft({
        encounterId: 'enc-1',
        recordType: state.recordType,
        recordContent: state.recordContent,
        isFinal: state.isFinal,
      })
      useDraftByTypeLoader('enc-1', state.recordType)
    })
    act(() => window.dispatchEvent(new Event('pagehide')))
    hook.unmount()
    expect(api.post).not.toHaveBeenCalled()
  })
  it('本地有内容时仍同步服务端基线，且不覆盖医生正在写的字', async () => {
    useRecordStore.setState({ recordContent: '平板上只写了两个字' })
    renderHook(() => useDraftByTypeLoader('enc-1', 'outpatient'))

    await waitFor(() => {
      expect(useRecordAutoSaveTrigger.getState().baselinePayload).not.toBeNull()
    })
    const p = useRecordAutoSaveTrigger.getState().baselinePayload!
    expect(p.updatedAt).toBe(SERVER_DRAFT.updated_at)
    // 只对齐基线，不接管正文状态——本地那份还没上传，不能显示"已保存"
    expect(p.adoptContent).toBe(false)
    expect(useRecordStore.getState().recordContent).toBe('平板上只写了两个字')
  })

  it('本地为空时照旧灌入服务端正文并接管状态', async () => {
    renderHook(() => useDraftByTypeLoader('enc-1', 'outpatient'))
    await waitFor(() => {
      expect(useRecordStore.getState().recordContent).toBe(SERVER_DRAFT.content)
    })
    expect(useRecordAutoSaveTrigger.getState().baselinePayload?.adoptContent).toBe(true)
  })

  it('AI 生成中不拉取（流式分片写入时正文会短暂为空）', async () => {
    useRecordStore.setState({ isGenerating: true })
    renderHook(() => useDraftByTypeLoader('enc-1', 'outpatient'))
    expect(getMock).not.toHaveBeenCalled()
  })

  it('请求在途时换了接诊则整体丢弃', async () => {
    renderHook(() => useDraftByTypeLoader('enc-1', 'outpatient'))
    useActiveEncounterStore.setState({ encounterId: 'enc-2' })
    await new Promise(r => setTimeout(r, 10))
    expect(useRecordStore.getState().recordContent).toBe('')
    expect(useRecordAutoSaveTrigger.getState().baselinePayload).toBeNull()
  })
})
