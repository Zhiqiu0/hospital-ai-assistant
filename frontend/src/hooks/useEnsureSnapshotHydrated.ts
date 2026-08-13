/**
 * 接诊上下文水合 Hook（hooks/useEnsureSnapshotHydrated.ts）
 *
 * 解决问题：
 *   activeEncounterStore 持久化了 currentEncounterId，
 *   刷新页面后这个"指针"会被还原。但 patientCacheStore 故意不持久化
 *   （档案是后端权威，避免脏数据），导致刷新后 PatientProfileCard 拿不到
 *   patient + profile 数据，渲染成空白。
 *
 *   本 hook 在工作台页面挂载时检测：
 *     - 有 currentEncounterId（说明确实有进行中的接诊）
 *     - 但 patientCache 没有该患者数据（说明是刷新后的"冷启动"）
 *   → 自动调用 GET /encounters/:id/workspace 拿完整 snapshot，
 *     用 applySnapshotResult 把 patient + patient_profile 重新填回 cache。
 *
 * 不重复请求：
 *   ref 标记本次会话是否已 hydrate 过，避免 currentEncounterId 没变但
 *   组件多次重渲染时反复请求。
 *
 * 错误降级：
 *   snapshot 失败时不抛错（用户可能网络抖动），下次刷新仍然会重试。
 */

import { useEffect, useRef } from 'react'
import api from '@/services/api'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { usePatientCacheStore } from '@/store/patientCacheStore'
import { applySnapshotResult, type SnapshotResult } from '@/store/encounterIntake'

export function useEnsureSnapshotHydrated() {
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const currentPatientId = useActiveEncounterStore(s => s.patientId)
  const hydratedForRef = useRef<string | null>(null)

  useEffect(() => {
    // 关键：只看 encounterId 是否存在，不要看 currentPatient 是否非空——
    // 刷新后 patientCacheStore 是空的（故意不持久化），currentPatient 必为 null，
    // 之前用它做守卫会直接 return，永远不会触发回填，导致顶部一直显示"未选择患者"。
    if (!currentEncounterId) return
    // 已 hydrate 过同一个 encounter，跳过
    if (hydratedForRef.current === currentEncounterId) return
    // patientCache 已有该患者数据（同一会话切回来）—— 无需 hydrate
    if (currentPatientId && usePatientCacheStore.getState().cache[currentPatientId]) {
      hydratedForRef.current = currentEncounterId
      return
    }
    // 冷启动：拉 snapshot 回填 patient + profile + inquiry + record + qc + aiSuggestion
    const requestedFor = currentEncounterId
    hydratedForRef.current = currentEncounterId
    api
      .get(`/encounters/${currentEncounterId}/workspace`)
      .then(snapshot => {
        // 迟到响应守卫（2026-08-13 第二轮审计修复）：请求在途时医生可能已经
        // 切到别的接诊（甚至新建了接诊），此时 applySnapshotResult 会把整个
        // 工作台——患者指针 + 问诊 + 病历正文 + 质控 —— 整体覆盖回上一个患者，
        // 当前患者已录入的内容被冲掉且随后被 auto-save 落库（跨患者数据污染）。
        // 只有当前指针仍是发起请求的那条接诊时才应用。
        if (useActiveEncounterStore.getState().encounterId !== requestedFor) return
        // 后端返回的形状已被 SnapshotResult 描述（patient + inquiry + active_record + ai_suggestions 等）
        if (snapshot) applySnapshotResult(snapshot as SnapshotResult)
      })
      .catch(() => {
        // 失败不报警；下次刷新还会重试
        if (hydratedForRef.current === requestedFor) hydratedForRef.current = null
      })
  }, [currentEncounterId, currentPatientId])
}
