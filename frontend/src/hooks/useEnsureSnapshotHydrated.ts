/**
 * 接诊上下文水合 Hook（hooks/useEnsureSnapshotHydrated.ts）
 *
 * 解决问题：
 *   workbenchStore + activeEncounterStore 都持久化了 currentEncounterId，
 *   刷新页面后这些"指针"会被还原。但 patientCacheStore 故意不持久化
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
import { useWorkbenchStore } from '@/store/workbenchStore'
import { usePatientCacheStore } from '@/store/patientCacheStore'
import { applySnapshotResult } from '@/store/encounterIntake'

export function useEnsureSnapshotHydrated() {
  const currentEncounterId = useWorkbenchStore(s => s.currentEncounterId)
  const currentPatient = useWorkbenchStore(s => s.currentPatient)
  const hydratedForRef = useRef<string | null>(null)

  useEffect(() => {
    if (!currentEncounterId || !currentPatient) return
    // 已 hydrate 过同一个 encounter，跳过
    if (hydratedForRef.current === currentEncounterId) return
    // patientCache 已有该患者数据，无需 hydrate
    const cached = usePatientCacheStore.getState().cache[currentPatient.id]
    if (cached) {
      hydratedForRef.current = currentEncounterId
      return
    }
    // 冷启动：拉 snapshot 回填
    hydratedForRef.current = currentEncounterId
    api
      .get(`/encounters/${currentEncounterId}/workspace`)
      .then((snapshot: any) => {
        if (snapshot) applySnapshotResult(snapshot)
      })
      .catch(() => {
        // 失败不报警；下次刷新还会重试
        hydratedForRef.current = null
      })
  }, [currentEncounterId, currentPatient])
}
