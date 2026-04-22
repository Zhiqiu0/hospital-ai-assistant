/**
 * 患者档案多患者缓存（store/patientCacheStore.ts）
 *
 * 设计目标：
 *   - 一处缓存，多组件复用：医生在多患者间快速切换时，避免重复请求
 *     `GET /patients/:id/profile`，并且接诊面板、患者条、问诊抽屉读到的
 *     是同一份数据（修改即刻反映）。
 *   - 与"当前接诊"解耦：本 store 只关心"哪个患者的档案是什么"，不存
 *     "现在医生正在接哪个患者"，后者由 activeEncounterStore 维护，避免
 *     单例耦合，便于 1.6/1.7 改 InquiryPanel 时按 patient_id 选择数据。
 *
 * LRU 控制：
 *   缓存条目按"最后访问时间"排序，超过 MAX_CACHED_PATIENTS 时淘汰最久未
 *   访问的患者，防止门诊一天接 50+ 患者后内存膨胀。
 *
 * 与后端字段对齐：
 *   Patient / PatientProfile 的形状直接复用 domain/medical/types.ts，对应
 *   后端 schemas/patient.py 的 PatientResponse 与 PatientProfile。后端
 *   `/encounters/quick-start` 与 `/encounters/{id}/snapshot` 已在响应里
 *   附 `patient` + `patient_profile` 两段数据，调用方拿到响应后调
 *   `upsertPatient` + `upsertProfile` 即可填充缓存。
 *
 * 持久化：
 *   故意不持久化（不挂 persist 中间件）。患者档案是后端权威数据，刷新
 *   页面后由 activeEncounterStore 触发的 snapshot 请求会重新填回；
 *   localStorage 里残留多个患者的旧档案反而容易导致脏数据。
 */

import { create } from 'zustand'
import type { Patient, PatientProfile } from '@/domain/medical'

/** 单个患者在缓存里的完整记录 */
export interface CachedPatient {
  /** 患者人口学信息（必有，先于 profile 写入） */
  patient: Patient
  /** 患者纵向档案；首次写入前可能为 null（接口未返回时） */
  profile: PatientProfile | null
  /** 最后一次被读/写的时间戳，用于 LRU 淘汰 */
  lastAccessedAt: number
}

/** 缓存上限：超出后淘汰 lastAccessedAt 最早的条目 */
export const MAX_CACHED_PATIENTS = 20

interface PatientCacheState {
  /** 以 patient.id 为键的缓存表 */
  cache: Record<string, CachedPatient>

  /** 写入或覆盖患者人口学信息；不会清空已有 profile */
  upsertPatient: (patient: Patient) => void
  /** 写入或覆盖患者档案；要求该患者已经在缓存里（否则忽略，避免悬空 profile） */
  upsertProfile: (patientId: string, profile: PatientProfile) => void
  /** 读取患者完整缓存条目；命中时刷新 lastAccessedAt */
  getCached: (patientId: string) => CachedPatient | undefined
  /** 仅读 profile 的便捷方法；命中时刷新 lastAccessedAt */
  getProfile: (patientId: string) => PatientProfile | null | undefined
  /** 仅读 patient 人口学信息的便捷方法；命中时刷新 lastAccessedAt */
  getPatient: (patientId: string) => Patient | undefined
  /** 主动淘汰一个患者（如：接诊取消、患者档案被删） */
  evict: (patientId: string) => void
  /** 清空所有缓存（如：用户登出） */
  clear: () => void
}

/**
 * 内部工具：在写入后若超过容量，淘汰最久未访问的若干条
 * 单独抽出来便于测试，导出仅用于单元测试，业务代码不要直接调用
 */
export function pruneIfOverflow(
  cache: Record<string, CachedPatient>,
  limit: number
): Record<string, CachedPatient> {
  const ids = Object.keys(cache)
  if (ids.length <= limit) return cache
  const sorted = ids.sort((a, b) => cache[a].lastAccessedAt - cache[b].lastAccessedAt)
  const toDrop = sorted.slice(0, ids.length - limit)
  const next = { ...cache }
  for (const id of toDrop) delete next[id]
  return next
}

export const usePatientCacheStore = create<PatientCacheState>()((set, get) => ({
  cache: {},

  upsertPatient: patient => {
    set(state => {
      const existing = state.cache[patient.id]
      const merged: CachedPatient = {
        patient,
        // 已有档案保留（避免 quick-start 之后再次 upsertPatient 把档案抹掉）
        profile: existing?.profile ?? null,
        lastAccessedAt: Date.now(),
      }
      const nextCache = { ...state.cache, [patient.id]: merged }
      return { cache: pruneIfOverflow(nextCache, MAX_CACHED_PATIENTS) }
    })
  },

  upsertProfile: (patientId, profile) => {
    set(state => {
      const existing = state.cache[patientId]
      // 若患者尚未在缓存里，忽略 profile 写入：profile 不应脱离 patient 单独存在
      // （调用方应先 upsertPatient，再 upsertProfile）
      if (!existing) return state
      return {
        cache: {
          ...state.cache,
          [patientId]: {
            ...existing,
            profile,
            lastAccessedAt: Date.now(),
          },
        },
      }
    })
  },

  getCached: patientId => {
    const entry = get().cache[patientId]
    if (!entry) return undefined
    // 读操作也刷新访问时间（命中即"近期使用"）
    set(state => ({
      cache: {
        ...state.cache,
        [patientId]: { ...entry, lastAccessedAt: Date.now() },
      },
    }))
    return entry
  },

  getProfile: patientId => {
    const entry = get().getCached(patientId)
    return entry ? entry.profile : undefined
  },

  getPatient: patientId => {
    const entry = get().getCached(patientId)
    return entry ? entry.patient : undefined
  },

  evict: patientId => {
    set(state => {
      if (!(patientId in state.cache)) return state
      const next = { ...state.cache }
      delete next[patientId]
      return { cache: next }
    })
  },

  clear: () => set({ cache: {} }),
}))
