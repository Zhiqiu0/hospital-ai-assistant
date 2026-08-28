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
import { useRecordStore } from '@/store/recordStore'
import { useAISuggestionStore } from '@/store/aiSuggestionStore'
import { useQCStore } from '@/store/qcStore'
import { useInquiryStore } from '@/store/inquiryStore'
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

    // 病历正文归属校验（2026-08-13 第五轮审计修复）
    // recordStore 与 activeEncounterStore 是两个独立的 localStorage 单槽：医生开两个
    // 标签页分别看甲、乙两位患者时，接诊指针会被后开的那个覆盖成乙，而 recordStore
    // 里可能还留着甲的正文；刷新后两槽各自还原，就拼出「乙患者 + 甲患者的病历」，
    // 再被 auto-save 原样写进乙的接诊——病历写到错误患者身上是医疗事故级问题。
    // 这里在拉快照之前先校验：对不上就丢弃正文（下面的 snapshot 会拉回该接诊的真实
    // 病历，宁可让医生等一次网络往返，也不能张冠李戴）。
    useRecordStore.getState().assertOwner(currentEncounterId)
    // 问诊/质控/AI 建议三家同款归属校验（2026-08-28 多标签页审计）：
    // 对不上即清空重绑——尤其防"后端该接诊 inquiry 为 null 时水合跳过覆盖、
    // 甲患者问诊残留在乙工作台并被保存写库"的高危路径
    useInquiryStore.getState().assertOwner(currentEncounterId)
    useQCStore.getState().assertOwner(currentEncounterId)
    useAISuggestionStore.getState().assertOwner(currentEncounterId)
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
        if (snapshot) {
          applySnapshotResult(snapshot as SnapshotResult)
          // 快照回填的正文属于这条接诊，打上归属标记
          useRecordStore.getState().bindOwner(requestedFor)
        }
      })
      .catch(() => {
        // 失败不报警；下次刷新还会重试
        if (hydratedForRef.current === requestedFor) hydratedForRef.current = null
      })
  }, [currentEncounterId, currentPatientId])
}
