/**
 * 门诊/急诊工作台页面（pages/WorkbenchPage.tsx）
 *
 * 门诊和急诊接诊的核心工作台，通过 mode prop 区分：
 *   mode="outpatient"（默认）→ 门诊  mode="emergency" → 急诊
 *
 * 布局：三栏响应式布局
 *   左栏：InquiryPanel（问诊表单）+ LabReportTab（检验报告 Tab 切换）
 *   中栏：RecordEditor（病历编辑区）+ FinalRecordModal（签发弹窗）
 *   右栏：AISuggestionPanel（AI 检查/追问/诊断建议）
 *
 * 子组件：
 *   WorkbenchHeader   → 顶部 Logo + 患者徽章 + 用户操作
 *   NoPatientOverlay  → 无接诊遮罩
 *   WorkbenchStatusBar→ 底部状态栏
 */
import { useState, useEffect } from 'react'
import { Layout, message, Tabs, Modal } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { useInquiryStore } from '@/store/inquiryStore'
import {
  useActiveEncounterStore,
  useCurrentPatient,
  resetAllWorkbench,
  setCurrentEncounterFromPatient,
} from '@/store/activeEncounterStore'
import type { VisitType } from '@/domain/medical'
import { applyQuickStartResult, applySnapshotResult } from '@/store/encounterIntake'
import api from '@/services/api'
import { useWorkbenchBase } from '@/hooks/useWorkbenchBase'
import { useEnsureSnapshotHydrated } from '@/hooks/useEnsureSnapshotHydrated'
import InquiryPanel from '@/components/workbench/InquiryPanel'
import RecordEditor from '@/components/workbench/RecordEditor'
import AISuggestionPanel from '@/components/workbench/AISuggestionPanel'
import ImagingUploadModal from '@/components/workbench/ImagingUploadModal'
import PatientHistoryDrawer from '@/components/workbench/PatientHistoryDrawer'
import RecordViewModal from '@/components/workbench/RecordViewModal'
import LabReportTab from '@/components/workbench/LabReportTab'
import NewEncounterModal from '@/components/workbench/NewEncounterModal'
import WorkbenchStatusBar from '@/components/workbench/WorkbenchStatusBar'
import WorkbenchHeader from '@/components/workbench/WorkbenchHeader'
import NoPatientOverlay from '@/components/workbench/NoPatientOverlay'
import CancelEncounterModal from '@/components/workbench/CancelEncounterModal'

const { Header, Content } = Layout

const RECORD_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊病历',
  admission_note: '入院记录',
  first_course_record: '首次病程记录',
  course_record: '日常病程记录',
  senior_round: '上级查房记录',
  discharge_record: '出院记录',
}

interface WorkbenchPageProps {
  mode?: 'outpatient' | 'emergency'
}

export default function WorkbenchPage({ mode = 'outpatient' }: WorkbenchPageProps) {
  const isEmergency = mode === 'emergency'
  const accentColor = isEmergency ? '#dc2626' : '#0891B2'
  const accentLight = isEmergency ? '#ef4444' : '#06b6d4'
  const accentLighter = isEmergency ? '#fca5a5' : '#67e8f9'
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const currentPatient = useCurrentPatient()
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const patchActive = useActiveEncounterStore(s => s.patchActive)
  const updateInquiryFields = useInquiryStore(s => s.updateInquiryFields)
  // 兼容封装，保留原 setVisitMeta 形状（页面里用了 4 处）
  const setVisitMeta = (firstVisit: boolean, vt: string) =>
    patchActive({ isFirstVisit: firstVisit, visitType: vt as VisitType })

  // 无接诊时清空残留数据（仅在页面初次挂载时执行，避免新建接诊时的竞态问题）
  useEffect(() => {
    if (!currentEncounterId) resetAllWorkbench()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 刷新页面后从后端 snapshot 回填 patientCache（patient + patient_profile）
  // 否则 PatientProfileCard 会因 cache 为空而显示空白
  useEnsureSnapshotHydrated()

  // 切换门诊/急诊页面时同步 visitType 到 store
  useEffect(() => {
    const defaultType = isEmergency ? 'emergency' : 'outpatient'
    const { visitType, isFirstVisit } = useActiveEncounterStore.getState()
    if (visitType !== defaultType) {
      setVisitMeta(isFirstVisit, defaultType)
    }
  }, [isEmergency])

  const {
    historyOpen,
    setHistoryOpen,
    openHistory,
    viewRecord,
    setViewRecord,
    handleLogout,
    cancelOpen,
    openCancel,
    closeCancel,
    handleCancelEncounter,
  } = useWorkbenchBase({
    resumeSuccessMsg: name => `已恢复「${name}」的接诊工作台`,
  })

  const [modalOpen, setModalOpen] = useState<'new' | 'returning' | null>(null)
  const [imagingOpen, setImagingOpen] = useState(false)

  // 新建接诊成功回调：更新 store 并处理住院跳转
  // resumed=true 表示后端检测到已有进行中接诊，直接续接而非新建
  const handleEncounterCreated = (res: any, visitType: string) => {
    resetAllWorkbench()
    // 1.6 数据接入：把 patient + patient_profile 写入 patientCacheStore，
    // 并通过 setCurrentEncounterFromPatient 设置 activeEncounterStore（一次性传完元信息）
    applyQuickStartResult(res)
    setCurrentEncounterFromPatient(res.patient, res.encounter_id, {
      visitType: (res.visit_type || visitType) as VisitType,
      // 2026-05-03 改：用后端权威 is_first_visit，旧逻辑 !patient_reused 在续接未签发
      // 接诊时会把"上次初诊未签发"误显示成"复诊"。后端用接诊状态机（completed=复诊
      // 起点）判断更准。fallback 保留旧推算兼容（万一后端没返回该字段也能跑）。
      isFirstVisit:
        typeof res.is_first_visit === 'boolean' ? res.is_first_visit : !res.patient_reused,
      isPatientReused: !!res.patient_reused,
      previousRecordContent: res.previous_record_content || null,
    })
    // 跨医生未完成接诊警示（非阻断）：让医生看到该患者还有别的医生留下的进行中接诊
    if (Array.isArray(res.pending_encounters) && res.pending_encounters.length > 0) {
      Modal.info({
        title: '该患者尚有未完成接诊',
        width: 480,
        content: (
          <div style={{ marginTop: 8 }}>
            <div style={{ marginBottom: 10, color: 'var(--text-3)', fontSize: 13 }}>
              建议联系下列医生处理后再继续，避免重复就诊：
            </div>
            <ul style={{ paddingLeft: 18, margin: 0, fontSize: 13, lineHeight: 2 }}>
              {res.pending_encounters.map(
                (
                  e: { doctor_name: string; visit_type: string; visited_at?: string },
                  i: number
                ) => (
                  <li key={i}>
                    医生 <b>{e.doctor_name}</b>（
                    {e.visit_type === 'emergency'
                      ? '急诊'
                      : e.visit_type === 'inpatient'
                        ? '住院'
                        : '门诊'}
                    {e.visited_at ? `，${new Date(e.visited_at).toLocaleString('zh-CN')}` : ''}）
                  </li>
                )
              )}
            </ul>
          </div>
        ),
        okText: '我已知悉，继续接诊',
      })
    }
    // 复诊且非续接：把上次稳定字段（既往史/过敏史/个人史等）预填入问诊表单
    if (res.patient_reused && !res.resumed && res.previous_inquiry) {
      const current = useInquiryStore.getState().inquiry
      updateInquiryFields({ ...current, ...res.previous_inquiry })
    }
    if (res.resumed) {
      message.info(`「${res.patient.name}」有未完成的接诊，已自动恢复`)
      // ★ 治本：自动恢复时拉 snapshot 灌回 inquiry/record/qc/aiSuggestion 4 个 store——
      // quick-start 接口本身只返回 patient + encounter_id，不含 AI 产物，
      // 所以 logout 重登后中间编辑器 / 质控提示 / 追问建议会全空（用户报告 bug）。
      // 失败不阻断，useEnsureSnapshotHydrated 在 currentEncounterId 变化时也会兜底重试。
      void api
        .get(`/encounters/${res.encounter_id}/workspace`)
        .then((snapshot: any) => {
          if (snapshot) applySnapshotResult(snapshot)
        })
        .catch(() => {
          /* 静默失败 */
        })
    } else {
      message.success(`已为「${res.patient.name}」开始接诊`)
    }
    if ((res.visit_type || visitType) === 'inpatient') navigate('/inpatient')
  }

  return (
    <Layout style={{ height: '100vh', background: 'var(--bg)' }}>
      <Header
        style={{
          height: 58,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--surface)',
          borderBottom: '1px solid var(--border)',
          padding: '0 20px',
          boxShadow: '0 1px 8px rgba(0,0,0,0.06)',
          zIndex: 100,
          flexShrink: 0,
          position: 'relative',
        }}
      >
        <WorkbenchHeader
          isEmergency={isEmergency}
          accentColor={accentColor}
          accentLight={accentLight}
          accentLighter={accentLighter}
          user={user}
          currentPatient={currentPatient}
          currentEncounterId={currentEncounterId}
          setModalOpen={setModalOpen}
          openHistory={openHistory}
          setImagingOpen={setImagingOpen}
          onSwitchMode={() => navigate(isEmergency ? '/workbench' : '/emergency')}
          handleLogout={handleLogout}
          onOpenCancel={openCancel}
        />
      </Header>

      <Content
        style={{ display: 'flex', overflow: 'hidden', gap: 10, padding: 10, position: 'relative' }}
      >
        {/* 左栏：问诊 + 检验报告 Tab */}
        <div
          style={{
            width: 320,
            background: 'var(--surface)',
            borderRadius: 12,
            border: '1px solid var(--border)',
            overflow: 'hidden',
            flexShrink: 0,
            boxShadow: 'var(--shadow-sm)',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <Tabs
            defaultActiveKey="inquiry"
            size="small"
            style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
            tabBarStyle={{ padding: '0 12px', marginBottom: 0, flexShrink: 0 }}
            items={[
              {
                key: 'inquiry',
                label: '问诊信息',
                children: (
                  <div style={{ height: '100%', overflow: 'hidden' }}>
                    <InquiryPanel />
                  </div>
                ),
              },
              {
                key: 'lab',
                label: '检验报告',
                children: (
                  <div style={{ height: '100%', overflow: 'hidden' }}>
                    <LabReportTab />
                  </div>
                ),
              },
            ]}
          />
        </div>

        {/* 中栏：病历编辑器 */}
        <div style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
          <RecordEditor />
        </div>

        {/* 右栏：AI 建议 */}
        <div
          style={{
            width: 320,
            background: 'var(--surface)',
            borderRadius: 12,
            border: '1px solid var(--border)',
            overflow: 'hidden',
            flexShrink: 0,
            boxShadow: 'var(--shadow-sm)',
          }}
        >
          <AISuggestionPanel />
        </div>

        {/* 无接诊遮罩 */}
        {!currentPatient && <NoPatientOverlay setModalOpen={setModalOpen} />}
      </Content>

      <NewEncounterModal
        open={modalOpen !== null}
        mode={modalOpen ?? 'new'}
        onClose={() => setModalOpen(null)}
        isEmergency={isEmergency}
        accentColor={accentColor}
        accentLight={accentLight}
        onSuccess={handleEncounterCreated}
      />

      {/* 历史病历抽屉：默认显示患者列表（按最近就诊倒序）+ 搜索过滤 +
          点患者看其全部签发病历。门诊/住院共用同一组件，命名统一为"历史病历"。 */}
      <PatientHistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        patientId={null}
        searchable
        onView={setViewRecord}
        recordTypeLabel={t => RECORD_TYPE_LABEL[t] || t}
      />

      <RecordViewModal
        record={viewRecord}
        onClose={() => setViewRecord(null)}
        accentColor={accentColor}
        tagColor={isEmergency ? 'red' : 'blue'}
        recordTypeLabel={t => RECORD_TYPE_LABEL[t] || t}
        showPrint
      />

      <ImagingUploadModal open={imagingOpen} onClose={() => setImagingOpen(false)} />

      <CancelEncounterModal
        open={cancelOpen}
        onClose={closeCancel}
        onConfirm={handleCancelEncounter}
      />

      {/* 底部状态栏：接诊状态 + 保存时间 */}
      <div
        style={{
          minHeight: 32,
          padding: '6px 16px',
          background: 'var(--surface-2)',
          borderTop: '1px solid var(--border)',
          fontSize: 12,
          lineHeight: 1.4,
          display: 'flex',
          alignItems: 'center',
          flexShrink: 0,
        }}
      >
        <WorkbenchStatusBar />
      </div>
    </Layout>
  )
}
