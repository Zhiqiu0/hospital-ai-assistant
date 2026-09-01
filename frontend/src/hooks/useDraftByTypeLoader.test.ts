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
import { renderHook, waitFor } from '@testing-library/react'

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
  getMock.mockResolvedValue(SERVER_DRAFT)
  useActiveEncounterStore.setState({ encounterId: 'enc-1' })
  useRecordStore.setState({ recordContent: '', recordType: 'outpatient', isGenerating: false })
  useRecordAutoSaveTrigger.setState({ baselineSignal: 0, baselinePayload: null })
})

describe('useDraftByTypeLoader', () => {
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
