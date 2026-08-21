/**
 * 诊断条目 store（store/diagnosisEntriesStore.ts，2026-08-21 阶段1b）
 *
 * 诊断条目是病历/病案首页的结构化权威源（后端 diagnoses 表），本 store 是
 * 前端工作副本：
 *   - 西医条目（可多条、恰一条主诊断、住院场景逐条入院病情标志）由
 *     WesternDiagnosisEditor 直接编辑本 store
 *   - 中医疾病/证候仍走 antd Form 文本字段（各至多一条），保存时由
 *     useInquirySave 合成完整条目列表 PUT /encounters/{id}/diagnoses
 *   - workspace 快照恢复时整组覆盖（applySnapshotResult / handleResume）
 *
 * persist 单槽（与 inquiryStore 同模式）：刷新不丢编辑中的条目；
 * resetAllWorkbench 时清空，防跨患者串数据。
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** 单条诊断条目（与后端 DiagnosisItemOut 对齐；新建条目时 id 为空串） */
export interface DiagnosisEntry {
  id?: string
  category: 'western' | 'tcm_disease' | 'tcm_syndrome'
  name: string
  code?: string | null
  code_type?: string | null
  is_primary: boolean
  /** 入院病情（住院逐条必填）：有 / 临床未确定 / 情况不明 / 无 */
  admission_condition?: string | null
  sort_order: number
}

interface DiagnosisEntriesState {
  /** 全部条目（含中医；编辑器只渲染西医区，中医由保存链路合成） */
  entries: DiagnosisEntry[]
  /** 整组覆盖（workspace 恢复 / PUT 响应回填） */
  setEntries: (entries: DiagnosisEntry[]) => void
  /** 只替换西医条目（编辑器写入口），保持中医条目不动 */
  setWesternEntries: (western: DiagnosisEntry[]) => void
  reset: () => void
}

export const useDiagnosisEntriesStore = create<DiagnosisEntriesState>()(
  persist(
    set => ({
      entries: [],
      setEntries: entries => set({ entries }),
      setWesternEntries: western =>
        set(state => ({
          entries: [...western, ...state.entries.filter(e => e.category !== 'western')],
        })),
      reset: () => set({ entries: [] }),
    }),
    { name: 'medassist-diagnoses' }
  )
)

/** 便捷 selector：西医条目（主诊断在前、组内按 sort_order） */
export function selectWestern(entries: DiagnosisEntry[]): DiagnosisEntry[] {
  return entries
    .filter(e => e.category === 'western')
    .sort((a, b) => Number(b.is_primary) - Number(a.is_primary) || a.sort_order - b.sort_order)
}
