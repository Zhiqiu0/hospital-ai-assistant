/**
 * 患者档案卡片业务逻辑（hooks/usePatientProfileCard.ts）
 *
 * 1.6.3 重构：表单状态从 hook 内部 useState 迁到 patientProfileEditStore，
 * 让 InquiryPanel/InpatientInquiryPanel 的统一保存按钮也能读 dirty / 触发 save，
 * 同时让 useInquiryPanel.applyVoiceInquiry 能把语音解析的 profile 字段
 * 通过 mergeVoicePatch 注入到表单。
 *
 * 职责：
 *   - 监听 activeEncounter.patientId 与 patientCache.profile 变化，
 *     同步到 patientProfileEditStore
 *   - 暴露读视图（form/isDirty/saving/isFemale/updatedAt）与编辑动作（setField）
 *   - 不再暴露 onSave —— 保存改由统一按钮触发，避免双入口
 */

import { useEffect } from 'react'
import { usePatientCacheStore } from '@/store/patientCacheStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { usePatientProfileEditStore, type ProfileFormState } from '@/store/patientProfileEditStore'
import { PROFILE_FIELD_KEYS } from '@/domain/medical'

export function usePatientProfileCard() {
  const patientId = useActiveEncounterStore(s => s.patientId)
  const cache = usePatientCacheStore(s => (patientId ? s.cache[patientId] : undefined))
  const loadFromProfile = usePatientProfileEditStore(s => s.loadFromProfile)
  const form = usePatientProfileEditStore(s => s.form)
  const isDirty = usePatientProfileEditStore(s => s.isDirty)
  const saving = usePatientProfileEditStore(s => s.saving)
  const setField = usePatientProfileEditStore(s => s.setField)

  const profile = cache?.profile ?? null
  const isFemale = cache?.patient.gender === 'female'

  // 切换患者或后端档案变化时同步到编辑 store
  // 同一患者且本地 dirty 时不会被 store 内部覆盖（保留医生未保存改动）
  useEffect(() => {
    loadFromProfile(patientId, profile)
  }, [patientId, profile?.updated_at, loadFromProfile])
  // 注意：profile?.updated_at 作为 dep —— 后端写入后 cache.profile 引用变，
  // 但 updated_at 也会变；如果 cache 因为 LRU 命中（lastAccessedAt 刷新）
  // 重建 cache 引用，updated_at 不变，loadFromProfile 内部会因 isDirty 守护
  // 不覆盖。所以这里依赖只看 patientId + updated_at 是安全的。

  // 后端 profile 是否已有任何字段被填写（用于折叠态判断、按钮态判断）
  const hasAnyProfileContent = profile
    ? PROFILE_FIELD_KEYS.some(k => {
        const v = profile[k]
        return v != null && String(v).trim() !== ''
      })
    : false

  return {
    /** 当前活动患者 ID；为 null 时组件应渲染空态 */
    patientId,
    /** 当前活动患者的 gender（驱动月经史字段是否显示） */
    isFemale,
    /** 表单本地值（来自 store） */
    form,
    /** 单字段更新（写入 store） */
    setField: setField as (key: keyof ProfileFormState, value: string) => void,
    /** 是否有未保存改动 */
    isDirty,
    /** 保存请求进行中 */
    saving,
    /** 后端最近一次写入档案的时间，用于"上次更新于"提示 */
    updatedAt: profile?.updated_at ?? null,
    /** 后端 profile 是否已有内容（驱动卡片初始折叠态） */
    hasAnyProfileContent,
  }
}
