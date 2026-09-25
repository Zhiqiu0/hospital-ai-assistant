/** 真实动作 hook 与 store：住院同接诊切文书后，迟到 AI 响应不得污染新文书。 */
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useRecordEditorShared } from './useRecordEditorShared'
import { useRecordGenerate } from './useRecordGenerate'
import { useRecordPolish } from './useRecordPolish'
import { useRecordQC } from './useRecordQC'
import { useRecordSupplement } from './useRecordSupplement'
import { useRecordStore } from '@/store/recordStore'
import { useInquiryStore } from '@/store/inquiryStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useQCStore } from '@/store/qcStore'
import { useRecordAutoSaveTrigger } from '@/store/recordAutoSaveTrigger'
import { streamSSE } from '@/services/streamSSE'

vi.mock('@/services/streamSSE', () => ({ streamSSE: vi.fn() }))
vi.mock('@/services/messageBridge', () => ({
  message: { warning: vi.fn(), error: vi.fn(), success: vi.fn(), info: vi.fn() },
}))
vi.mock('@/sentry', () => ({ reportCaught: vi.fn() }))

function deferred() {
  let resolve!: () => void
  let reject!: (e: Error) => void
  const promise = new Promise<void>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
let handlers: Parameters<typeof streamSSE>[3]
let gate: ReturnType<typeof deferred>
beforeEach(() => {
  vi.clearAllMocks()
  useRecordStore.getState().reset()
  useQCStore.getState().reset()
  useInquiryStore.getState().reset()
  useInquiryStore
    .getState()
    .updateInquiryFields({ ...useInquiryStore.getState().inquiry, chief_complaint: '原问诊' })
  useActiveEncounterStore.setState({ encounterId: 'same-inpatient', patientId: null })
  useRecordStore.setState({ recordType: 'admission_note', recordContent: '入院原文' })
  gate = deferred()
  vi.mocked(streamSSE).mockImplementation(async (_u, _b, _t, h) => {
    handlers = h
    await gate.promise
  })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
function switchDocument() {
  useRecordStore.getState().setRecordType('daily_progress')
  useRecordStore.getState().setRecordContent('【主诉】\n新文书内容')
}

it.each(['chunk', 'error', 'complete', 'return'] as const)(
  '生成迟到 %s 不写新文书或问诊基线',
  async mode => {
    const { result } = renderHook(() => useRecordGenerate(useRecordEditorShared()))
    await act(async () => {
      void result.current.handleGenerate()
    })
    const baseline = useRecordAutoSaveTrigger.getState().baselineSignal
    await act(async () => {
      switchDocument()
      if (mode === 'return') useRecordStore.getState().setRecordType('admission_note')
      useRecordStore.getState().setRecordContent('【主诉】\n新文书内容')
      useRecordStore.getState().setGenerating(true)
      if (mode === 'chunk' || mode === 'return') handlers.onChunk?.('旧流内容')
      if (mode === 'error') gate.reject(new Error('旧请求失败'))
      else {
        handlers.onEvent?.({ type: 'done', saved_updated_at: '2026-09-26T00:00:00Z' })
        gate.resolve()
      }
    })
    expect(useRecordStore.getState().recordContent).toBe('【主诉】\n新文书内容')
    expect(useInquiryStore.getState().inquiry.chief_complaint).toBe('原问诊')
    expect(useRecordAutoSaveTrigger.getState().baselineSignal).toBe(baseline)
    expect(useRecordStore.getState().isGenerating).toBe(true)
  }
)

it('旧润色失败不回滚新文书，也不清除新文书生成态', async () => {
  const { result } = renderHook(() => useRecordPolish(useRecordEditorShared()))
  let work!: Promise<void>
  await act(async () => {
    work = result.current.handlePolish()
  })
  await act(async () => {
    switchDocument()
    useRecordStore.getState().setPolishing(true)
    gate.reject(new Error('旧润色失败'))
    await work
  })
  expect(useRecordStore.getState().recordContent).toBe('【主诉】\n新文书内容')
  expect(useRecordStore.getState().isPolishing).toBe(true)
})

it('旧质控事件与 finally 不覆盖新文书正在进行的质控', async () => {
  const { result } = renderHook(() => useRecordQC(useRecordEditorShared()))
  let work!: Promise<void>
  await act(async () => {
    work = result.current.handleQC()
  })
  await act(async () => {
    switchDocument()
    useQCStore.setState({ qcSummary: '新文书质控', isQCing: true, qcLlmLoading: true })
    handlers.onEvent?.({ type: 'done', summary: '旧质控', pass: true })
    gate.resolve()
    await work
  })
  expect(useQCStore.getState()).toMatchObject({
    qcSummary: '新文书质控',
    isQCing: true,
    qcLlmLoading: true,
  })
})

it('补全迟到 JSON 不改新文书，也不触发新文书质控', async () => {
  useQCStore.setState({
    qcIssues: [
      {
        field_name: '主诉',
        issue_type: 'missing',
        source: 'rule',
        risk_level: 'high',
        issue_description: '缺主诉',
        suggestion: '补充主诉',
      },
    ],
  })
  const qc = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      await gate.promise
      return { ok: true, json: async () => ({ items: [{ field_name: '主诉', value: '旧补全' }] }) }
    })
  )
  const { result } = renderHook(() => useRecordSupplement(useRecordEditorShared(), qc))
  let work!: Promise<void>
  await act(async () => {
    work = result.current.handleSupplement()
  })
  await act(async () => {
    switchDocument()
    gate.resolve()
    await work
  })
  expect(useRecordStore.getState().recordContent).toBe('【主诉】\n新文书内容')
  expect(qc).not.toHaveBeenCalled()
})
