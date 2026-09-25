/** 页面视图切换不得修改现有接诊的业务类型或已签发导出首页。 */
import { fireEvent, render } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import {
  useActiveEncounterStore,
  setCurrentEncounterFromPatient,
} from '@/store/activeEncounterStore'
import { useRecordStore } from '@/store/recordStore'
import { exportWordDoc } from '@/utils/recordExport'
import WorkbenchPage from './WorkbenchPage'
vi.mock('@/hooks/useEnsureSnapshotHydrated', () => ({ useEnsureSnapshotHydrated: vi.fn() }))
vi.mock('@/hooks/useWorkbenchBase', () => ({ useWorkbenchBase: () => ({}) }))
vi.mock('@/components/workbench/InquiryPanel', () => ({ default: () => null }))
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
vi.mock('@/components/workbench/NewEncounterModal', () => ({
  default: ({
    isEmergency,
    onSuccess,
  }: {
    isEmergency: boolean
    onSuccess: (
      res: {
        encounter_id: string
        patient: { id: string; name: string; gender: string }
        visit_type: string
      },
      visitType: string
    ) => void
  }) => (
    <button
      onClick={() =>
        onSuccess(
          {
            encounter_id: 'new-emergency',
            patient: { id: 'new-p', name: '急诊测试患者', gender: 'unknown' },
            visit_type: 'emergency',
          },
          'emergency'
        )
      }
    >
      {isEmergency ? '新建急诊' : '新建门诊'}
    </button>
  ),
}))

it('门诊签发后切急诊页面，仍以门诊首页导出且允许新建急诊', async () => {
  setCurrentEncounterFromPatient(
    { id: 'audit-p', name: '测试患者', gender: 'unknown' },
    'audit-e',
    { visitType: 'outpatient' }
  )
  useRecordStore.getState().setRecordContent('已签发门诊正文')
  useRecordStore.getState().setFinal(true, '2026-09-26T01:00:00')
  const page = (mode: 'outpatient' | 'emergency') => (
    <MemoryRouter>
      <WorkbenchPage mode={mode} />
    </MemoryRouter>
  )
  const { rerender, getByText } = render(page('outpatient'))
  rerender(page('emergency'))
  expect(getByText('新建急诊')).toBeInTheDocument()
  let blob!: Blob
  vi.stubGlobal('URL', {
    createObjectURL: vi.fn((b: Blob) => {
      blob = b
      return 'blob:audit'
    }),
    revokeObjectURL: vi.fn(),
  })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  const record = useRecordStore.getState()
  exportWordDoc(
    record.recordContent,
    { name: '测试患者' },
    record.recordType,
    record.finalizedAt,
    record.patientSnapshot,
    { visit_type: useActiveEncounterStore.getState().visitType }
  )
  const html = await new Promise<string>(resolve => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.readAsText(blob)
  })
  expect(html).not.toContain('急诊')
  expect(useActiveEncounterStore.getState().visitType).toBe('outpatient')
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('急诊页面新建成功仍由真实接诊更新文书类型', () => {
  useActiveEncounterStore.getState().clearActive()
  const { getByRole } = render(
    <MemoryRouter>
      <WorkbenchPage mode="emergency" />
    </MemoryRouter>
  )
  fireEvent.click(getByRole('button', { name: '新建急诊' }))
  expect(useActiveEncounterStore.getState().encounterId).toBe('new-emergency')
  expect(useActiveEncounterStore.getState().visitType).toBe('emergency')
  expect(useRecordStore.getState().recordType).toBe('emergency')
})
