/** 冷启动全局快照不能覆盖时间轴选定的旧文书。 */
import { beforeEach, expect, it } from 'vitest'
import { useRecordStore } from './recordStore'
import { useActiveEncounterStore } from './activeEncounterStore'
import { applySnapshotResult } from './encounterIntake'

beforeEach(() => {
  useRecordStore.getState().reset()
  useActiveEncounterStore.setState({ encounterId: 'enc', patientId: 'p' })
})

it('active_record不同于当前所选ID时保留正文、签发锁及首页', () => {
  useRecordStore.getState().selectRecord('course_record', 'A')
  useRecordStore.setState({
    recordContent: '甲签发稿',
    isFinal: true,
    patientSnapshot: { name: '冻结姓名' },
  })
  applySnapshotResult({
    encounter_id: 'enc',
    visit_type: 'inpatient',
    patient: { id: 'p', name: '患者' },
    active_record: {
      record_id: 'B',
      record_type: 'admission_note',
      content: '乙稿',
      status: 'editing',
    },
  })
  expect(useRecordStore.getState()).toMatchObject({
    selectedRecordId: 'A',
    recordType: 'course_record',
    recordContent: '甲签发稿',
    isFinal: true,
    patientSnapshot: { name: '冻结姓名' },
  })
})
