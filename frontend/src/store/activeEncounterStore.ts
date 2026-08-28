/**
 * 当前活动接诊指针（store/activeEncounterStore.ts）
 *
 * 职责（只做一件事）：
 *   记录"医生当前正在处理的接诊"是哪一条 —— 仅持有 patient_id /
 *   encounter_id / visit_type 等指针字段，不存患者档案数据本身。
 *   患者档案存放在 patientCacheStore，本 store 与之解耦。
 *
 * 历史沿革：
 *   旧 workbenchStore 既存"指针"又存"接诊内态"（几十个字段），切换患者
 *   要重置整个 store，无法同时保留多个患者的档案视图。Round 1.5 把指针
 *   单独抽出成本 store，迁移已完成，workbenchStore 已整体删除。
 *
 * 持久化：
 *   挂 persist 中间件，刷新页面后能恢复到上一个接诊。患者档案与病历
 *   内容由调用方（页面 useEffect）重新拉取 snapshot 填回。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Patient, VisitType } from '@/domain/medical'
import { useInquiryStore } from './inquiryStore'
import { useRecordStore } from './recordStore'
import { useQCStore } from './qcStore'
import { useAISuggestionStore } from './aiSuggestionStore'
import { useDiagnosisEntriesStore } from './diagnosisEntriesStore'
import { useAiWrittenFieldsStore } from './aiWrittenFieldsStore'
import { usePatientCacheStore } from './patientCacheStore'

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
   * 本次接诊的就诊时间（2026-08-14 第六轮审计修复）。
   *
   * 病案首页有「就诊时间」一栏。原先前端拿不到它（快照不返回），于是编辑器
   * 打印时把 visit_time 赋成了 finalizedAt（签发时刻）——首页上「患者什么时候
   * 来的」直接写错，而这是病案首页的法定字段。
   */
  visitedAt: string | null

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
    visitedAt?: string | null
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
      visitedAt: string | null
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
      visitedAt: null,

      setActive: input => {
        // Audit Round 4 M1：encounterId 真的变了 → 主动清空 4 个子 store 派生数据，
        // 避免上一个接诊的 inquiry / record / qc / aiSuggestion 残留到新接诊上。
        // 这是 backlog M1 的核心机制：让"切换接诊"成为单一切清空入口，不再
        // 依赖各 consumer 自己手动 reset 一堆字段，加新字段也不会再漏。
        const prev = get().encounterId
        if (prev !== input.encounterId) {
          useInquiryStore.getState().reset()
          useRecordStore.getState().reset()
          useQCStore.getState().reset()
          useAISuggestionStore.getState().reset()
          // 诊断条目按接诊隔离（2026-08-21 阶段1b）——切接诊即清，防跨患者串
          useDiagnosisEntriesStore.getState().reset()
          // AI 写入高亮按接诊隔离 —— 切换接诊清空，避免上一个接诊的
          // 高亮残留误导医生（2026-05-24 治本路线）
          useAiWrittenFieldsStore.getState().clear()
        }
        // 病历正文归属跟着接诊走（2026-08-13 第五轮审计修复）：正文与接诊指针是
        // 两个独立的持久化槽，不绑定归属就会在多标签页/刷新后拼出"甲的病历配乙的患者"
        useRecordStore.getState().bindOwner(input.encounterId)
        // 问诊/质控/AI 建议三个单槽同样绑定归属（2026-08-28 多标签页审计：
        // 此前只有病历正文有守卫，其余三家裸奔可跨标签拼到错误患者名下）
        useInquiryStore.getState().bindOwner(input.encounterId)
        useQCStore.getState().bindOwner(input.encounterId)
        useAISuggestionStore.getState().bindOwner(input.encounterId)

        // 病历类型也跟着接诊走（2026-08-13 第五轮审计修复）：
        // 急诊工作台只是 <WorkbenchPage mode="emergency" />，全程没有任何一处
        // setRecordType('emergency')，recordStore 默认 'outpatient'——于是急诊病历
        // 一路按门诊类型保存、按门诊评分表质控、按门诊类型回写 HIS，全错。
        // 靠"每个页面自己记得设"这种约定必然会漏，改为由接诊类型单点推导。
        // 住院例外：一次住院有入院记录/病程/出院小结等多种文书，具体类型由
        // ComplianceBar 按待办项切换，这里不覆盖医生已选的住院文书类型。
        if (input.visitType !== 'inpatient') {
          useRecordStore.getState().setRecordType(input.visitType)
        }
        set({
          patientId: input.patientId,
          encounterId: input.encounterId,
          visitType: input.visitType,
          isFirstVisit: input.isFirstVisit,
          isPatientReused: input.isPatientReused,
          previousRecordContent: input.previousRecordContent ?? null,
          visitedAt: input.visitedAt ?? null,
        })
      },

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

      clearActive: () => {
        // 关闭接诊：子 store 也一并清空（统一入口，避免遗漏字段）
        useInquiryStore.getState().reset()
        useRecordStore.getState().reset()
        useQCStore.getState().reset()
        useAISuggestionStore.getState().reset()
        useDiagnosisEntriesStore.getState().reset()
        set({
          patientId: null,
          encounterId: null,
          visitType: DEFAULT_VISIT_TYPE,
          isFirstVisit: true,
          isPatientReused: false,
          previousRecordContent: null,
        })
      },

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

/**
 * Audit Round 4 M1 兼容工具：从 Patient 对象直接切换接诊。
 *
 * 替代原 workbenchStore.setCurrentEncounter(patient, encounterId) 的语义：
 *   1. 把 patient 对象 upsert 到 patientCacheStore（保证后续 useCurrentPatient 能拿到）
 *   2. 调 setActive 写入指针字段，自动 reset 4 个子 store
 *
 * 多数调用点只关心切患者，不显式知道 visit/firstVisit 等元信息——
 * options 留空时复用当前 store 已有值，与原 setCurrentEncounter 行为一致。
 */
export function setCurrentEncounterFromPatient(
  patient: Patient,
  encounterId: string,
  options?: {
    visitType?: VisitType
    isFirstVisit?: boolean
    isPatientReused?: boolean
    previousRecordContent?: string | null
    visitedAt?: string | null
  }
): void {
  // 先 upsert 到 cache，让 useCurrentPatient 能查到
  usePatientCacheStore.getState().upsertPatient(patient)
  // 然后切换接诊指针 + 清子 store
  const current = useActiveEncounterStore.getState()
  useActiveEncounterStore.getState().setActive({
    patientId: patient.id,
    encounterId,
    visitType: options?.visitType ?? current.visitType,
    isFirstVisit: options?.isFirstVisit ?? current.isFirstVisit,
    isPatientReused: options?.isPatientReused ?? current.isPatientReused,
    previousRecordContent: options?.previousRecordContent ?? null,
    visitedAt: options?.visitedAt ?? null,
  })
}

/**
 * 一次性清空所有工作台 store（登出 / 强制重置时用）。
 *
 * 替代原 useWorkbenchStore.reset() 的语义。
 */
export function resetAllWorkbench(): void {
  useInquiryStore.getState().reset()
  useRecordStore.getState().reset()
  useQCStore.getState().reset()
  useAISuggestionStore.getState().reset()
  // 诊断条目（2026-08-21 阶段1b）：不清会把上一位患者的诊断带给下一位
  useDiagnosisEntriesStore.getState().reset()
  useActiveEncounterStore.getState().clearActive()
}

/**
 * 便捷 selector hook：拿当前接诊的 Patient 对象（来自 patientCacheStore）。
 *
 * 替代原 workbenchStore.currentPatient 的用法。返回 null 表示无活动接诊
 * 或缓存未命中（首次加载时短暂存在）。
 */
export function useCurrentPatient(): Patient | null {
  const patientId = useActiveEncounterStore(s => s.patientId)
  const cache = usePatientCacheStore(s => s.cache)
  if (!patientId) return null
  return cache[patientId]?.patient ?? null
}
