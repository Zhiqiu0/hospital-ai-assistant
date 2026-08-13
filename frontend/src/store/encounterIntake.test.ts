/**
 * encounterIntake 单元测试
 *
 * 重点覆盖：
 *  - applyQuickStartResult 同时写入两个 store
 *  - patient_profile 缺失时不抛错
 *  - patient.gender 异常值（null / unknown 字符串）被收敛为 'unknown'
 *  - patient_reused=true 对应 isFirstVisit=false
 *  - applySnapshotResult 默认按复诊态处理
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { applyQuickStartResult, applySnapshotResult, type SnapshotResult } from './encounterIntake'
import { usePatientCacheStore } from './patientCacheStore'
import { useActiveEncounterStore } from './activeEncounterStore'

beforeEach(() => {
  usePatientCacheStore.getState().clear()
  useActiveEncounterStore.getState().clearActive()
})

describe('applyQuickStartResult', () => {
  it('同时写入 patientCache 与 activeEncounter', () => {
    applyQuickStartResult({
      encounter_id: 'e1',
      patient: { id: 'p1', name: '张三', gender: 'male', age: 40 },
      patient_profile: { allergy_history: '青霉素过敏', past_history: '高血压' },
      visit_type: 'outpatient',
      patient_reused: false,
      previous_record_content: null,
    })

    const cached = usePatientCacheStore.getState().getCached('p1')
    expect(cached?.patient.name).toBe('张三')
    expect(cached?.profile?.allergy_history).toBe('青霉素过敏')

    const active = useActiveEncounterStore.getState()
    expect(active.patientId).toBe('p1')
    expect(active.encounterId).toBe('e1')
    expect(active.visitType).toBe('outpatient')
    expect(active.isFirstVisit).toBe(true)
    expect(active.isPatientReused).toBe(false)
  })

  it('patient_profile 缺失时仅写 patient，不抛错', () => {
    // QuickStartResult.encounter_id + patient 必填，其它字段都 optional；无需 cast
    expect(() =>
      applyQuickStartResult({
        encounter_id: 'e1',
        patient: { id: 'p1', name: '张三' },
      })
    ).not.toThrow()
    expect(usePatientCacheStore.getState().getCached('p1')?.profile).toBeNull()
  })

  it('未知 gender 收敛为 unknown，未知 visit_type 收敛为 outpatient', () => {
    // gender 字段后端类型签名是 string | null，运行时可能传非法值；用 satisfies 验证
    // 整体形状仍是 QuickStartResult，避免破坏类型检查
    applyQuickStartResult({
      encounter_id: 'e1',
      patient: { id: 'p1', name: 'X', gender: 'weird-value' },
      visit_type: 'weird-type',
    })
    expect(usePatientCacheStore.getState().getPatient('p1')?.gender).toBe('unknown')
    expect(useActiveEncounterStore.getState().visitType).toBe('outpatient')
  })

  it('patient_reused=true → isFirstVisit=false 且 isPatientReused=true', () => {
    applyQuickStartResult({
      encounter_id: 'e1',
      patient: { id: 'p1', name: '李四' },
      patient_reused: true,
      previous_record_content: '上次病历...',
    })
    const active = useActiveEncounterStore.getState()
    expect(active.isFirstVisit).toBe(false)
    expect(active.isPatientReused).toBe(true)
    expect(active.previousRecordContent).toBe('上次病历...')
  })
})

describe('applySnapshotResult', () => {
  it('恢复接诊时默认按复诊态处理', () => {
    applySnapshotResult({
      encounter_id: 'e2',
      patient: { id: 'p2', name: '王五' },
      patient_profile: { past_history: '糖尿病' },
      visit_type: 'inpatient',
    })
    const active = useActiveEncounterStore.getState()
    expect(active.encounterId).toBe('e2')
    expect(active.visitType).toBe('inpatient')
    expect(active.isFirstVisit).toBe(false)
    expect(active.isPatientReused).toBe(true)
    expect(usePatientCacheStore.getState().getProfile('p2')?.past_history).toBe('糖尿病')
  })

  it('encounter_id 缺失时不写 active，但仍可写 patientCache', () => {
    // SnapshotResult.encounter_id 是 optional，直接传入合法
    applySnapshotResult({
      patient: { id: 'p3', name: '赵六' },
      patient_profile: { allergy_history: '海鲜' },
    } satisfies SnapshotResult)
    expect(usePatientCacheStore.getState().getProfile('p3')?.allergy_history).toBe('海鲜')
    expect(useActiveEncounterStore.getState().encounterId).toBeNull()
  })
})

describe('水合不得静默回滚未保存的病历（2026-08-13 第五轮审计修复）', () => {
  it('本地有未落库的编辑时，快照不覆盖医生正在写的内容', async () => {
    const { useRecordStore } = await import('@/store/recordStore')
    const { applySnapshotResult } = await import('@/store/encounterIntake')

    // 上次保存到"主诉：头痛。"，医生之后又打了一段还没触发 auto-save（5秒防抖）
    useRecordStore.setState({
      recordContent: '主诉：头痛。现病史：三天前受凉后起病……',
      lastSavedContent: '主诉：头痛。',
    })

    applySnapshotResult({
      active_record: {
        content: '主诉：头痛。',
        status: 'draft',
        updated_at: '2026-08-13T10:00:00',
      },
    } as never)

    expect(useRecordStore.getState().recordContent).toBe('主诉：头痛。现病史：三天前受凉后起病……')
  })

  it('本地无未保存编辑时，快照正常回填（不能因为怕覆盖就永远不同步）', async () => {
    const { useRecordStore } = await import('@/store/recordStore')
    const { applySnapshotResult } = await import('@/store/encounterIntake')

    useRecordStore.setState({ recordContent: '旧内容', lastSavedContent: '旧内容' })

    applySnapshotResult({
      active_record: {
        content: '服务端的新内容',
        status: 'draft',
        updated_at: '2026-08-13T10:00:00',
      },
    } as never)

    expect(useRecordStore.getState().recordContent).toBe('服务端的新内容')
  })
})
