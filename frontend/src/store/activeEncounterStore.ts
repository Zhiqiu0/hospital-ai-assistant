/**
 * 当前活动接诊指针（store/activeEncounterStore.ts）
 *
 * 职责（只做一件事）：
 *   记录"医生当前正在处理的接诊"是哪一条 —— 仅持有 patient_id /
 *   encounter_id / visit_type 等指针字段，不存患者档案数据本身。
 *   患者档案存放在 patientCacheStore，本 store 与之解耦。
 *
 * 为什么不直接复用 workbenchStore：
 *   workbenchStore 既存了"指针"（currentPatient/currentEncounterId）又
 *   存了"接诊内态"（inquiry/recordContent/QC 结果等几十个字段），导致
 *   切换患者时为了清理内态要重置整个 store，无法在内存里同时保留多个
 *   患者的档案视图。Round 1.5 把指针单独抽出来，1.6 起新组件直接读
 *   activeEncounterStore + patientCacheStore，老组件继续用 workbenchStore，
 *   等迁移完了再把 workbenchStore 里冗余的指针字段删掉。
 *
 * 持久化：
 *   挂 persist 中间件，刷新页面后能恢复到上一个接诊。患者档案与病历
 *   内容由调用方（页面 useEffect）重新拉取 snapshot 填回。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { VisitType } from '@/domain/medical'

interface ActiveEncounterState {
  /** 当前接诊的患者 ID；null 表示尚未开始任何接诊 */
  patientId: string | null
  /** 当前接诊 ID；null 表示尚未开始任何接诊 */
  encounterId: string | null
  /** 接诊场景：门诊 / 急诊 / 住院 */
  visitType: VisitType
  /** 是否初诊（系统自动判断，非用户切换） */
  isFirstVisit: boolean
  /** 该患者是否被复用（true=复诊，初诊/复诊 toggle 不可手动切换） */
  isPatientReused: boolean
  /** 复诊时上一次的病历全文，供 AI 生成参考（null=初诊或暂无） */
  previousRecordContent: string | null

  /**
   * 一次性设置当前接诊（quick-start 成功 / snapshot 恢复时调用）
   * 把所有指针字段一起写入，避免组件分多次 set 导致中间态被订阅
   */
  setActive: (input: {
    patientId: string
    encounterId: string
    visitType: VisitType
    isFirstVisit: boolean
    isPatientReused: boolean
    previousRecordContent?: string | null
  }) => void

  /**
   * 仅更新接诊状态字段（不切换患者）。
   * 用于：医生中途修改 visit_type / 系统判定 patient_reused 状态变更等。
   */
  patchActive: (
    patch: Partial<{
      visitType: VisitType
      isFirstVisit: boolean
      isPatientReused: boolean
      previousRecordContent: string | null
    }>
  ) => void

  /** 关闭 / 取消接诊，清空指针；不影响 patientCacheStore 中的档案数据 */
  clearActive: () => void

  /** 是否处于接诊中（patientId & encounterId 同时存在） */
  hasActive: () => boolean
}

const DEFAULT_VISIT_TYPE: VisitType = 'outpatient'

export const useActiveEncounterStore = create<ActiveEncounterState>()(
  persist(
    (set, get) => ({
      patientId: null,
      encounterId: null,
      visitType: DEFAULT_VISIT_TYPE,
      isFirstVisit: true,
      isPatientReused: false,
      previousRecordContent: null,

      setActive: input =>
        set({
          patientId: input.patientId,
          encounterId: input.encounterId,
          visitType: input.visitType,
          isFirstVisit: input.isFirstVisit,
          isPatientReused: input.isPatientReused,
          previousRecordContent: input.previousRecordContent ?? null,
        }),

      patchActive: patch =>
        set(state => ({
          visitType: patch.visitType ?? state.visitType,
          isFirstVisit: patch.isFirstVisit !== undefined ? patch.isFirstVisit : state.isFirstVisit,
          isPatientReused:
            patch.isPatientReused !== undefined ? patch.isPatientReused : state.isPatientReused,
          previousRecordContent:
            patch.previousRecordContent !== undefined
              ? patch.previousRecordContent
              : state.previousRecordContent,
        })),

      clearActive: () =>
        set({
          patientId: null,
          encounterId: null,
          visitType: DEFAULT_VISIT_TYPE,
          isFirstVisit: true,
          isPatientReused: false,
          previousRecordContent: null,
        }),

      hasActive: () => {
        const s = get()
        return Boolean(s.patientId && s.encounterId)
      },
    }),
    {
      name: 'medassist-active-encounter',
      // 全部字段都持久化（指针类，量小，刷新即生效）
      partialize: state => ({
        patientId: state.patientId,
        encounterId: state.encounterId,
        visitType: state.visitType,
        isFirstVisit: state.isFirstVisit,
        isPatientReused: state.isPatientReused,
        previousRecordContent: state.previousRecordContent,
      }),
    }
  )
)
