/** 签发后保留接诊指针供转住院，同时向医生显示已完成。 */
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import WorkbenchStatusBar from './WorkbenchStatusBar'
import {
  setCurrentEncounterFromPatient,
  useActiveEncounterStore,
} from '@/store/activeEncounterStore'
import { useRecordStore } from '@/store/recordStore'

it('门診签发后显示接诊已完成且保留转住院上下文', () => {
  setCurrentEncounterFromPatient({ id: 'test-p', name: '测试患者', gender: 'unknown' }, 'test-e', {
    visitType: 'outpatient',
  })
  useRecordStore.getState().setFinal(true, '2026-09-26T01:00:00')
  render(<WorkbenchStatusBar />)
  expect(screen.getByText('测试患者 · 接诊已完成')).toBeInTheDocument()
  expect(useActiveEncounterStore.getState().encounterId).toBe('test-e')
})

it('住院单份文书签发不能把住院接诊误标为完成', () => {
  setCurrentEncounterFromPatient(
    { id: 'test-p', name: '测试患者', gender: 'unknown' },
    'test-inpatient',
    { visitType: 'inpatient' }
  )
  useRecordStore.getState().setFinal(true, '2026-09-26T01:00:00')
  render(<WorkbenchStatusBar />)
  expect(screen.getByText('测试患者 · 接诊中')).toBeInTheDocument()
})
