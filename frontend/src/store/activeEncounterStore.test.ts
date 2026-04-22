/**
 * activeEncounterStore 单元测试
 *
 * 覆盖要点：
 *  - 初始状态：无活动接诊
 *  - setActive 一次性写入所有指针字段
 *  - patchActive 只更新指定字段，其他保留
 *  - clearActive 重置回初始
 *  - hasActive 判定逻辑
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { useActiveEncounterStore } from './activeEncounterStore'

describe('activeEncounterStore', () => {
  beforeEach(() => {
    useActiveEncounterStore.getState().clearActive()
  })

  it('初始状态无活动接诊', () => {
    const s = useActiveEncounterStore.getState()
    expect(s.patientId).toBeNull()
    expect(s.encounterId).toBeNull()
    expect(s.hasActive()).toBe(false)
  })

  it('setActive 一次性写入所有指针字段', () => {
    useActiveEncounterStore.getState().setActive({
      patientId: 'p1',
      encounterId: 'e1',
      visitType: 'emergency',
      isFirstVisit: false,
      isPatientReused: true,
      previousRecordContent: '上次主诉：发热',
    })
    const s = useActiveEncounterStore.getState()
    expect(s.patientId).toBe('p1')
    expect(s.encounterId).toBe('e1')
    expect(s.visitType).toBe('emergency')
    expect(s.isFirstVisit).toBe(false)
    expect(s.isPatientReused).toBe(true)
    expect(s.previousRecordContent).toBe('上次主诉：发热')
    expect(s.hasActive()).toBe(true)
  })

  it('setActive 不传 previousRecordContent 时默认 null', () => {
    useActiveEncounterStore.getState().setActive({
      patientId: 'p1',
      encounterId: 'e1',
      visitType: 'outpatient',
      isFirstVisit: true,
      isPatientReused: false,
    })
    expect(useActiveEncounterStore.getState().previousRecordContent).toBeNull()
  })

  it('patchActive 只更新指定字段，其他保留', () => {
    useActiveEncounterStore.getState().setActive({
      patientId: 'p1',
      encounterId: 'e1',
      visitType: 'outpatient',
      isFirstVisit: true,
      isPatientReused: false,
      previousRecordContent: 'X',
    })
    useActiveEncounterStore.getState().patchActive({ visitType: 'emergency' })
    const s = useActiveEncounterStore.getState()
    expect(s.visitType).toBe('emergency')
    // 其他字段保持
    expect(s.patientId).toBe('p1')
    expect(s.isFirstVisit).toBe(true)
    expect(s.previousRecordContent).toBe('X')
  })

  it('patchActive 显式传 false / null 也能正确写入', () => {
    useActiveEncounterStore.getState().setActive({
      patientId: 'p1',
      encounterId: 'e1',
      visitType: 'outpatient',
      isFirstVisit: true,
      isPatientReused: true,
      previousRecordContent: 'X',
    })
    useActiveEncounterStore
      .getState()
      .patchActive({ isPatientReused: false, previousRecordContent: null })
    const s = useActiveEncounterStore.getState()
    expect(s.isPatientReused).toBe(false)
    expect(s.previousRecordContent).toBeNull()
  })

  it('clearActive 重置所有指针', () => {
    useActiveEncounterStore.getState().setActive({
      patientId: 'p1',
      encounterId: 'e1',
      visitType: 'inpatient',
      isFirstVisit: false,
      isPatientReused: true,
      previousRecordContent: 'X',
    })
    useActiveEncounterStore.getState().clearActive()
    const s = useActiveEncounterStore.getState()
    expect(s.patientId).toBeNull()
    expect(s.encounterId).toBeNull()
    expect(s.visitType).toBe('outpatient')
    expect(s.isFirstVisit).toBe(true)
    expect(s.isPatientReused).toBe(false)
    expect(s.previousRecordContent).toBeNull()
    expect(s.hasActive()).toBe(false)
  })

  it('hasActive 仅在 patientId 与 encounterId 同时存在时为 true', () => {
    const s = useActiveEncounterStore.getState()
    expect(s.hasActive()).toBe(false)
    s.setActive({
      patientId: 'p1',
      encounterId: 'e1',
      visitType: 'outpatient',
      isFirstVisit: true,
      isPatientReused: false,
    })
    expect(useActiveEncounterStore.getState().hasActive()).toBe(true)
  })
})
