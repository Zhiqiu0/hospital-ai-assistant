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

describe('切换病历类型不丢内容（2026-08-14 第七轮审计修复）', () => {
  it('切走再切回，原类型的内容还在', async () => {
    const { useRecordStore } = await import('@/store/recordStore')
    const st = useRecordStore.getState()

    st.reset()
    useRecordStore.setState({ recordType: 'admission_note' })
    useRecordStore.getState().setRecordContent('入院记录：患者因腰痛入院……')

    // 切到病程
    useRecordStore.getState().setRecordType('course_record')
    expect(useRecordStore.getState().recordContent).toBe('')

    useRecordStore.getState().setRecordContent('病程：今日查房……')

    // 切回入院记录 —— 原内容必须还在
    useRecordStore.getState().setRecordType('admission_note')
    expect(useRecordStore.getState().recordContent).toBe('入院记录：患者因腰痛入院……')

    // 再切回病程 —— 病程内容也还在
    useRecordStore.getState().setRecordType('course_record')
    expect(useRecordStore.getState().recordContent).toBe('病程：今日查房……')
  })

  it('换患者时按类型暂存的草稿被清空（不能跨患者残留）', async () => {
    const { useRecordStore } = await import('@/store/recordStore')

    useRecordStore.getState().reset()
    useRecordStore.setState({ recordType: 'admission_note' })
    useRecordStore.getState().setRecordContent('甲患者的入院记录')
    useRecordStore.getState().setRecordType('course_record')

    // 此时 draftsByType 里存着甲的内容
    expect(Object.keys(useRecordStore.getState().draftsByType).length).toBeGreaterThan(0)

    useRecordStore.getState().reset()
    expect(useRecordStore.getState().draftsByType).toEqual({})
  })
})

// ─── 住院接诊必须给住院文书类型作默认（2026-09-01 住院支线实测发现）────────
//
// 原实现对住院直接跳过 setRecordType，理由是「具体类型由 ComplianceBar 切换」。
// 但「不覆盖医生选择」不等于「不给默认」：新建住院接诊后 recordType 保持
// recordStore 的默认值 outpatient，医生直接填问诊点生成，落库的就是一份
// record_type='outpatient' 的病历挂在住院接诊下——章节按门诊模板渲染（缺婚育史/
// 月经史/诊疗计划，还多出【辨证分析】）、质控按门诊评分表判、HIS 回写也是门诊。
// 这正是 2026-08-13 修过的那个急诊 bug，只是当时把住院排除在外了。
describe('住院接诊的默认病历类型', () => {
  it('新建住院接诊时，门诊类型要被换成入院记录', async () => {
    const { useRecordStore } = await import('./recordStore')
    useRecordStore.getState().setRecordType('outpatient')
    useActiveEncounterStore.getState().setActive({
      patientId: 'p-ip',
      encounterId: 'e-ip',
      visitType: 'inpatient',
      isFirstVisit: true,
      isPatientReused: false,
    })
    expect(useRecordStore.getState().recordType).toBe('admission_note')
  })

  it('同一接诊内医生已切到病程记录时不覆盖他的选择', async () => {
    // 注意前提：encounterId 不变才谈得上「不覆盖」——换接诊时 setActive 会先
    // reset 四个子 store（防跨患者串味），那是更优先的不变量，此时给默认才对。
    const { useRecordStore } = await import('./recordStore')
    const same = {
      patientId: 'p-ip2',
      encounterId: 'e-ip2',
      visitType: 'inpatient' as const,
      isFirstVisit: false,
      isPatientReused: false,
    }
    useActiveEncounterStore.getState().setActive(same)
    useRecordStore.getState().setRecordType('course_record')
    useActiveEncounterStore.getState().setActive(same) // 同一接诊再次进入
    expect(useRecordStore.getState().recordType).toBe('course_record')
  })

  it('门诊/急诊仍按接诊类型直接设置', async () => {
    const { useRecordStore } = await import('./recordStore')
    useActiveEncounterStore.getState().setActive({
      patientId: 'p-er',
      encounterId: 'e-er',
      visitType: 'emergency',
      isFirstVisit: true,
      isPatientReused: false,
    })
    expect(useRecordStore.getState().recordType).toBe('emergency')
  })
})
