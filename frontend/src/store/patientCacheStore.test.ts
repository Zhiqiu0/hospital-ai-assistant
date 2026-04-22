/**
 * patientCacheStore 单元测试
 *
 * 覆盖要点：
 *  - upsertPatient 不会清空已有 profile（顺序写入幂等）
 *  - upsertProfile 在患者尚未缓存时被忽略（防悬空）
 *  - getCached / getProfile / getPatient 命中后刷新 lastAccessedAt
 *  - 超过 MAX_CACHED_PATIENTS 时淘汰最久未访问的条目（LRU）
 *  - evict / clear 行为正确
 */

import { describe, it, expect, beforeEach } from 'vitest'
import {
  usePatientCacheStore,
  pruneIfOverflow,
  MAX_CACHED_PATIENTS,
  type CachedPatient,
} from './patientCacheStore'
import type { Patient, PatientProfile } from '@/domain/medical'

const makePatient = (id: string, name = `患者${id}`): Patient => ({
  id,
  name,
  gender: 'unknown',
  age: 30,
})

const makeProfile = (allergy = '青霉素过敏'): PatientProfile => ({
  allergy_history: allergy,
  past_history: '高血压',
})

describe('patientCacheStore', () => {
  beforeEach(() => {
    usePatientCacheStore.getState().clear()
  })

  it('upsertPatient 写入新患者后能读出', () => {
    const { upsertPatient, getPatient } = usePatientCacheStore.getState()
    upsertPatient(makePatient('p1', '张三'))
    expect(getPatient('p1')?.name).toBe('张三')
  })

  it('upsertPatient 不会清空已有 profile（顺序写入幂等）', () => {
    const store = usePatientCacheStore.getState()
    store.upsertPatient(makePatient('p1'))
    store.upsertProfile('p1', makeProfile('海鲜过敏'))
    // 再次 upsertPatient，profile 应保留
    store.upsertPatient(makePatient('p1', '张三-改名'))
    const cached = usePatientCacheStore.getState().getCached('p1')
    expect(cached?.patient.name).toBe('张三-改名')
    expect(cached?.profile?.allergy_history).toBe('海鲜过敏')
  })

  it('upsertProfile 在患者未缓存时被忽略（防悬空 profile）', () => {
    const { upsertProfile } = usePatientCacheStore.getState()
    upsertProfile('ghost', makeProfile())
    expect(usePatientCacheStore.getState().cache['ghost']).toBeUndefined()
  })

  it('getProfile 命中后刷新 lastAccessedAt', async () => {
    const store = usePatientCacheStore.getState()
    store.upsertPatient(makePatient('p1'))
    store.upsertProfile('p1', makeProfile())
    const t1 = usePatientCacheStore.getState().cache['p1'].lastAccessedAt
    // 等 2ms 让时间戳确实拉开
    await new Promise(r => setTimeout(r, 2))
    usePatientCacheStore.getState().getProfile('p1')
    const t2 = usePatientCacheStore.getState().cache['p1'].lastAccessedAt
    expect(t2).toBeGreaterThan(t1)
  })

  it('evict 移除指定患者，不影响其他', () => {
    const store = usePatientCacheStore.getState()
    store.upsertPatient(makePatient('p1'))
    store.upsertPatient(makePatient('p2'))
    store.evict('p1')
    expect(usePatientCacheStore.getState().cache['p1']).toBeUndefined()
    expect(usePatientCacheStore.getState().cache['p2']).toBeDefined()
  })

  it('clear 清空所有患者', () => {
    const store = usePatientCacheStore.getState()
    store.upsertPatient(makePatient('p1'))
    store.upsertPatient(makePatient('p2'))
    store.clear()
    expect(Object.keys(usePatientCacheStore.getState().cache)).toHaveLength(0)
  })
})

describe('pruneIfOverflow (LRU)', () => {
  it('未超过上限时不变更', () => {
    const cache: Record<string, CachedPatient> = {
      a: { patient: makePatient('a'), profile: null, lastAccessedAt: 1 },
      b: { patient: makePatient('b'), profile: null, lastAccessedAt: 2 },
    }
    const next = pruneIfOverflow(cache, 5)
    expect(Object.keys(next)).toEqual(['a', 'b'])
  })

  it('超过上限时淘汰最久未访问的条目', () => {
    const cache: Record<string, CachedPatient> = {
      old: { patient: makePatient('old'), profile: null, lastAccessedAt: 100 },
      mid: { patient: makePatient('mid'), profile: null, lastAccessedAt: 200 },
      new: { patient: makePatient('new'), profile: null, lastAccessedAt: 300 },
    }
    const next = pruneIfOverflow(cache, 2)
    expect(Object.keys(next).sort()).toEqual(['mid', 'new'])
    expect(next['old']).toBeUndefined()
  })

  it('与 store 集成：写超过 MAX_CACHED_PATIENTS 后自动淘汰最早访问的', async () => {
    const store = usePatientCacheStore.getState()
    // 写 MAX+3 个患者，每次写入间隔 1ms 让 lastAccessedAt 拉开
    for (let i = 0; i < MAX_CACHED_PATIENTS + 3; i++) {
      store.upsertPatient(makePatient(`p${i}`))
      await new Promise(r => setTimeout(r, 1))
    }
    const ids = Object.keys(usePatientCacheStore.getState().cache)
    expect(ids.length).toBe(MAX_CACHED_PATIENTS)
    // 最早写入的 p0/p1/p2 应该被淘汰
    expect(ids).not.toContain('p0')
    expect(ids).not.toContain('p1')
    expect(ids).not.toContain('p2')
    // 最后一批应该都还在
    expect(ids).toContain(`p${MAX_CACHED_PATIENTS + 2}`)
  })
})
