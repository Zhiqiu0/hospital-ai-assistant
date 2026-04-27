/**
 * 患者档案编辑态 Store（store/patientProfileEditStore.ts）
 *
 * 为什么单独建一个 store：
 *   1. 让外部组件（InquiryPanel/InpatientInquiryPanel 的"统一保存"按钮）能
 *      读取 isDirty 与触发 save，而不必从 PatientProfileCard 内部 hook 暴露。
 *   2. 让语音录入处理（useInquiryPanel.applyVoiceInquiry）能把语音 LLM 解析
 *      出来的 profile 字段写入档案表单，避免被丢弃。
 *
 * 与 patientCacheStore 的边界：
 *   patientCacheStore 存"后端权威 profile 数据"（多患者缓存）；
 *   本 store 存"医生当前正在编辑的 profile 草稿"（仅一份，对应 activeEncounter 的患者）。
 *   保存成功后，把后端返回的 profile 写回 patientCacheStore，本 store 清空 dirty。
 *
 * 切换患者时：
 *   loadFromProfile(newPatientId, profile) 会重置 form 与 dirty。
 *   未保存的草稿会被丢弃（这是与 patientCache "切换不丢失" 截然不同的语义；
 *   档案是高敏数据，不该让上一个患者的输入残留到下一个患者）。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { message } from 'antd'
import api from '@/services/api'
import type { PatientProfile } from '@/domain/medical'
import { PROFILE_FIELD_KEYS } from '@/domain/medical'
import { usePatientCacheStore } from './patientCacheStore'

/** 表单本地状态：所有 profile 字段都是 string（空字符串代表清空） */
export type ProfileFormState = Record<(typeof PROFILE_FIELD_KEYS)[number], string>

/** 空表单常量，所有字段都是空字符串 */
export const EMPTY_PROFILE_FORM: ProfileFormState = PROFILE_FIELD_KEYS.reduce((acc, key) => {
  acc[key] = ''
  return acc
}, {} as ProfileFormState)

/** 从 PatientProfile 读出表单初值，缺失字段填空字符串 */
export function profileToForm(profile: PatientProfile | null | undefined): ProfileFormState {
  if (!profile) return { ...EMPTY_PROFILE_FORM }
  const next = { ...EMPTY_PROFILE_FORM }
  for (const key of PROFILE_FIELD_KEYS) {
    next[key] = (profile[key] as string | null | undefined) ?? ''
  }
  return next
}

interface State {
  /** 当前编辑的患者 ID；切换时重置 form */
  loadedPatientId: string | null
  /** 表单本地值 */
  form: ProfileFormState
  /** 是否有未保存改动 */
  isDirty: boolean
  /** 保存请求进行中 */
  saving: boolean

  /**
   * 用于 PatientProfileCard 在患者切换或后端档案变化时刷新本地 form。
   * - 若 patientId 不同 → 重置 form + dirty=false（丢弃旧草稿）
   * - 若 patientId 相同但本地 dirty=true → 不覆盖（保留医生未保存改动）
   * - 若 patientId 相同且本地 dirty=false → 用最新 profile 同步
   */
  loadFromProfile: (patientId: string | null, profile: PatientProfile | null) => void

  /** 单字段更新 */
  setField: (key: keyof ProfileFormState, value: string) => void

  /**
   * 把语音 LLM 解析出的 profile 字段合并到表单，并标 dirty。
   * 仅写入有值（非空字符串）的字段，避免空值清空已填内容。
   * 不直接调 PUT —— 让医生看到卡片已展开后再点"保存"按钮，避免误改。
   */
  mergeVoicePatch: (patch: Record<string, unknown>) => { mergedCount: number }

  /**
   * 保存：调 PUT /patients/:id/profile，成功后写回 patientCacheStore，重置 dirty。
   * 仅发"与缓存里 profile 不同"的字段，减小载荷且避免把空字符串误覆盖。
   * 调用方传 patientId，未传或不匹配 loadedPatientId 时静默失败（防误调）。
   *
   * 返回 true=成功 / false=失败 / 'noop'=没有可保存的变更
   */
  save: (patientId: string) => Promise<true | false | 'noop'>

  /** 重置所有状态（如登出 / 患者切换无 profile） */
  reset: () => void
}

// 持久化说明：
//   form / isDirty / loadedPatientId 均持久化，避免医生填到一半刷新就丢。
//   saving 不持久化（属于瞬时 UI 态，刷新时一定不在保存中）。
//   loadFromProfile 内部已守护"同患者+dirty 不覆盖"，所以恢复后不会被
//   后端 profile 推送覆盖未保存草稿。
export const usePatientProfileEditStore = create<State>()(
  persist(
    (set, get) => ({
      loadedPatientId: null,
      form: { ...EMPTY_PROFILE_FORM },
      isDirty: false,
      saving: false,

      loadFromProfile: (patientId, profile) => {
        const cur = get()
        if (cur.loadedPatientId !== patientId) {
          // 切换患者：丢弃旧草稿，重置为新患者的 profile
          set({
            loadedPatientId: patientId,
            form: profileToForm(profile),
            isDirty: false,
          })
          return
        }
        // 同一患者，且本地无未保存改动 → 用最新数据刷新
        if (!cur.isDirty) {
          set({ form: profileToForm(profile) })
        }
      },

      setField: (key, value) => {
        set(state => ({
          form: { ...state.form, [key]: value },
          isDirty: true,
        }))
      },

      mergeVoicePatch: patch => {
        let mergedCount = 0
        set(state => {
          const next = { ...state.form }
          for (const key of PROFILE_FIELD_KEYS) {
            const val = patch[key]
            // 仅接受非空字符串值；语音识别"未提及"会输出 ""
            if (typeof val !== 'string' || !val.trim()) continue
            next[key] = val
            mergedCount++
          }
          if (mergedCount === 0) return state
          return { form: next, isDirty: true }
        })
        return { mergedCount }
      },

      save: async patientId => {
        const cur = get()
        if (cur.loadedPatientId !== patientId) {
          // 防御：调用方传的 patientId 与当前 loaded 不一致，可能是切换瞬间的竞态
          return false
        }

        // 与缓存里的 profile 比较，只发改动字段
        const cachedProfile = usePatientCacheStore.getState().cache[patientId]?.profile
        const changed: Partial<PatientProfile> = {}
        for (const key of PROFILE_FIELD_KEYS) {
          const before = (cachedProfile?.[key] as string | null | undefined) ?? ''
          const after = cur.form[key] ?? ''
          if (before !== after) changed[key] = after
        }
        if (Object.keys(changed).length === 0) {
          // 无变更，不打扰用户但视为成功
          set({ isDirty: false })
          return 'noop'
        }

        set({ saving: true })
        try {
          const updated: any = await api.put(`/patients/${patientId}/profile`, changed)
          // 后端返回完整 profile，写回 patientCache（含 updated_at）
          usePatientCacheStore.getState().upsertProfile(patientId, {
            past_history: updated.past_history ?? null,
            allergy_history: updated.allergy_history ?? null,
            family_history: updated.family_history ?? null,
            personal_history: updated.personal_history ?? null,
            current_medications: updated.current_medications ?? null,
            marital_history: updated.marital_history ?? null,
            religion_belief: updated.religion_belief ?? null,
            // 月经史已移出档案（地基重构），从 inquiry.menstrual_history 取
            updated_at: updated.updated_at ?? null,
            fields_meta: updated.fields_meta ?? null,
          })
          set({ isDirty: false, saving: false })
          return true
        } catch {
          set({ saving: false })
          message.error('保存档案失败，请稍后重试')
          return false
        }
      },

      reset: () =>
        set({
          loadedPatientId: null,
          form: { ...EMPTY_PROFILE_FORM },
          isDirty: false,
          saving: false,
        }),
    }),
    {
      name: 'medassist-profile-edit',
      partialize: state => ({
        loadedPatientId: state.loadedPatientId,
        form: state.form,
        isDirty: state.isDirty,
      }),
    }
  )
)
