/** 真实转住院hook与门急诊页面联测：住院路由延迟加载也不能丢失接诊和转诊参考。 */
import { Suspense, lazy } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import WorkbenchPage from './WorkbenchPage'
import { useEmergencyFlow } from '@/hooks/inquiryPanel/useEmergencyFlow'
import {
  useActiveEncounterStore,
  useCurrentPatient,
  setCurrentEncounterFromPatient,
} from '@/store/activeEncounterStore'
import { useRecordStore } from '@/store/recordStore'
import api from '@/services/api'

vi.mock('@/services/api', () => ({ default: { post: vi.fn() } }))
vi.mock('@/services/messageBridge', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))
vi.mock('@/hooks/useEnsureSnapshotHydrated', () => ({ useEnsureSnapshotHydrated: vi.fn() }))
vi.mock('@/hooks/useWorkbenchBase', () => ({ useWorkbenchBase: () => ({}) }))
vi.mock('@/components/workbench/RecordEditor', () => ({ default: () => null }))
vi.mock('@/components/workbench/AISuggestionPanel', () => ({ default: () => null }))
vi.mock('@/components/workbench/ImagingUploadModal', () => ({ default: () => null }))
vi.mock('@/components/workbench/PatientHistoryDrawer', () => ({ default: () => null }))
vi.mock('@/components/workbench/RecordViewModal', () => ({ default: () => null }))
vi.mock('@/components/workbench/LabReportTab', () => ({ default: () => null }))
vi.mock('@/components/workbench/WorkbenchHeader', () => ({ default: () => null }))
vi.mock('@/components/workbench/ReturnedRecordsNotice', () => ({ default: () => null }))
vi.mock('@/components/workbench/NoPatientOverlay', () => ({ default: () => null }))
vi.mock('@/components/workbench/CancelEncounterModal', () => ({ default: () => null }))
vi.mock('@/components/workbench/HisQueueDock', () => ({ default: () => null }))
vi.mock('@/components/workbench/WorkbenchStatusBar', () => ({ default: () => null }))
vi.mock('@/components/workbench/NewEncounterModal', () => ({ default: () => null }))
vi.mock('@/components/workbench/InquiryPanel', () => ({ default: TransferAction }))

/** 只替换表单布局，点击调用真实转住院流程及真实接诊store。 */
function TransferAction() {
  const currentPatient = useCurrentPatient()
  const { recordContent, setRecordContent } = useRecordStore()
  const { handleAdmitToInpatient } = useEmergencyFlow({
    currentPatient,
    recordContent,
    setRecordContent,
  })
  return <button onClick={handleAdmitToInpatient}>转住院</button>
}

function InpatientDestination() {
  const encounterId = useActiveEncounterStore(s => s.encounterId)
  return <div>住院接诊：{encounterId || '未选择患者'}</div>
}

beforeEach(() => {
  vi.clearAllMocks()
  setCurrentEncounterFromPatient(
    { id: 'transfer-p', name: '转住院测试患者', gender: 'unknown' },
    'outpatient-e',
    { visitType: 'outpatient' }
  )
  useRecordStore.getState().setRecordContent('已经签发的门诊参考正文')
  useRecordStore.getState().setFinal(true, '2026-09-26T01:00:00')
})

it('住院路由仍在加载时，转住院不得被旧页面guard清空', async () => {
  let finishLoad!: (value: { default: typeof InpatientDestination }) => void
  const DelayedInpatient = lazy(
    () =>
      new Promise<{ default: typeof InpatientDestination }>(resolve => {
        finishLoad = resolve
      })
  )
  vi.mocked(api.post).mockResolvedValue({
    encounter_id: 'inpatient-e',
    visit_type: 'inpatient',
    patient: { id: 'transfer-p', name: '转住院测试患者', gender: 'unknown' },
  })
  render(
    <MemoryRouter initialEntries={['/workbench']}>
      <Suspense fallback={<span>加载住院工作台</span>}>
        <Routes>
          <Route path="/workbench" element={<WorkbenchPage />} />
          <Route path="/inpatient" element={<DelayedInpatient />} />
        </Routes>
      </Suspense>
    </MemoryRouter>
  )
  fireEvent.click(screen.getByRole('button', { name: '转住院' }))
  await waitFor(() => expect(api.post).toHaveBeenCalled())
  // 路由懒加载尚未完成，给旧页面的effect和零延迟定时器实际执行机会。
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 20))
  })
  expect(useActiveEncounterStore.getState().encounterId).toBe('inpatient-e')
  expect(useActiveEncounterStore.getState().previousRecordContent).toBe('已经签发的门诊参考正文')
  await act(async () => {
    finishLoad({ default: InpatientDestination })
  })
  expect(screen.getByText('住院接诊：inpatient-e')).toBeInTheDocument()
  expect(useRecordStore.getState().recordType).toBe('admission_note')
})

it('手动在门诊路由恢复住院接诊时仍隔离场景，并保留接诊送回住院页', async () => {
  setCurrentEncounterFromPatient(
    { id: 'transfer-p', name: '转住院测试患者', gender: 'unknown' },
    'restored-inpatient',
    { visitType: 'inpatient', previousRecordContent: '原转诊参考' }
  )
  render(
    <MemoryRouter initialEntries={['/workbench']}>
      <Routes>
        <Route path="/workbench" element={<WorkbenchPage />} />
        <Route path="/inpatient" element={<InpatientDestination />} />
      </Routes>
    </MemoryRouter>
  )
  await waitFor(() => expect(screen.getByText('住院接诊：restored-inpatient')).toBeInTheDocument())
  expect(screen.queryByRole('button', { name: '转住院' })).toBeNull()
  expect(useActiveEncounterStore.getState().previousRecordContent).toBe('原转诊参考')
})
