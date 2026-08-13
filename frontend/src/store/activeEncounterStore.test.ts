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

describe('病历正文归属校验（2026-08-13 第五轮审计修复）', () => {
  it('接诊指针与病历正文对不上时，正文被丢弃而不是套到别的患者头上', async () => {
    const { useRecordStore } = await import('@/store/recordStore')

    // 模拟多标签页刷新后的残留：正文属于甲的接诊 E1
    useRecordStore.setState({ recordContent: '甲患者的主诉与现病史', ownerEncounterId: 'E1' })

    // 而当前接诊指针已经是乙的 E2（被另一个标签页覆盖）
    const ok = useRecordStore.getState().assertOwner('E2')

    expect(ok).toBe(false)
    expect(useRecordStore.getState().recordContent).toBe('')
    expect(useRecordStore.getState().ownerEncounterId).toBe('E2')
  })

  it('归属一致时正文原样保留（不能误伤正常刷新）', async () => {
    const { useRecordStore } = await import('@/store/recordStore')
    useRecordStore.setState({ recordContent: '本接诊的病历', ownerEncounterId: 'E1' })

    expect(useRecordStore.getState().assertOwner('E1')).toBe(true)
    expect(useRecordStore.getState().recordContent).toBe('本接诊的病历')
  })

  it('无归属标记的旧数据一律丢弃（改动之前留下的，无从判断归谁）', async () => {
    const { useRecordStore } = await import('@/store/recordStore')
    useRecordStore.setState({ recordContent: '来历不明的正文', ownerEncounterId: null })

    expect(useRecordStore.getState().assertOwner('E1')).toBe(false)
    expect(useRecordStore.getState().recordContent).toBe('')
  })
})
