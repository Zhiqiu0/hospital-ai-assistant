/** 恢复接诊时由真实就诊类型选择空文书，不能被页面默认类型覆盖。 */
import { act, renderHook } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { useWorkbenchBase } from './useWorkbenchBase'
import { useActiveEncounterStore, resetAllWorkbench } from '@/store/activeEncounterStore'
import { useRecordStore } from '@/store/recordStore'
import api from '@/services/api'

vi.mock('@/services/api', () => ({ default: { get: vi.fn() } }))
vi.mock('@/services/messageBridge', () => ({ message: { success: vi.fn(), error: vi.fn() } }))

beforeEach(() => {
  vi.resetAllMocks()
  resetAllWorkbench()
})

it.each(['outpatient', 'emergency'])(
  '恢复无文书的%s接诊必须使用其真实文书类型',
  async visitType => {
    vi.mocked(api.get).mockResolvedValue({
      encounter_id: 'resume-e',
      patient: { id: 'resume-p', name: '恢复测试', gender: 'unknown' },
      visit_type: visitType,
      active_record: null,
    })
    // 与门急诊工作台相同，不依靠页面模式给默认文书类型。
    const { result } = renderHook(() => useWorkbenchBase(), {
      wrapper: ({ children }) => <MemoryRouter>{children}</MemoryRouter>,
    })
    await act(async () => {
      await result.current.handleResume({ encounter_id: 'resume-e' })
    })
    expect(useActiveEncounterStore.getState().visitType).toBe(visitType)
    expect(useRecordStore.getState().recordType).toBe(visitType)
  }
)

it('住院空文书继续使用工作台指定的入院记录默认值', async () => {
  vi.mocked(api.get).mockResolvedValue({
    encounter_id: 'resume-i',
    patient: { id: 'resume-pi', name: '住院测试', gender: 'unknown' },
    visit_type: 'inpatient',
    active_record: null,
  })
  const { result } = renderHook(() => useWorkbenchBase({ defaultRecordType: 'admission_note' }), {
    wrapper: ({ children }) => <MemoryRouter>{children}</MemoryRouter>,
  })
  await act(async () => {
    await result.current.handleResume({ encounter_id: 'resume-i' })
  })
  expect(useRecordStore.getState().recordType).toBe('admission_note')
})
