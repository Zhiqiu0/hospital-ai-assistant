/**
 * 住院工作台页面（pages/InpatientWorkbenchPage.tsx）
 *
 * 住院接诊专用工作台。与门诊差异：
 *   - 问诊面板：InpatientInquiryPanel（含入院诊断、体征等住院字段）
 *   - 默认病历类型：admission_note（入院记录）
 *   - 续接诊列表：visitTypeFilter='inpatient'
 *   - 时间轴：病程记录 tab（InpatientTimeline + ProgressNotePanel）
 *
 * 中间编辑区行为：
 *   - 未选中时间轴条目 或 选中入院记录 → RecordEditor（主编辑器）
 *   - 选中病程记录 → ProgressNotePanel（独立编辑/签发）
 *
 * 2026-06-11 Round 5.5 拆分：新建接诊成功后的副作用编排（写缓存/预填/警示/恢复
 * snapshot）移至 ./inpatientWorkbench/encounterCreated.tsx，本页只保留布局编排。
 */
import { useState, useEffect } from 'react'
import { App, Layout, Button, Empty } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useAuthStore } from '@/store/authStore'
import { useRecordStore } from '@/store/recordStore'
import {
  useActiveEncounterStore,
  useCurrentPatient,
  resetAllWorkbench,
} from '@/store/activeEncounterStore'
import {
  handleInpatientEncounterCreated,
  type InpatientEncounterCreatedRes,
} from './inpatientWorkbench/encounterCreated'
import { useWorkbenchBase } from '@/hooks/useWorkbenchBase'
import { useEnsureSnapshotHydrated } from '@/hooks/useEnsureSnapshotHydrated'
import InpatientInquiryPanel from '@/components/workbench/InpatientInquiryPanel'
import RecordEditor from '@/components/workbench/RecordEditor'
import ImagingUploadModal from '@/components/workbench/ImagingUploadModal'
import PatientHistoryDrawer from '@/components/workbench/PatientHistoryDrawer'
import RecordViewModal from '@/components/workbench/RecordViewModal'
import WardView from '@/components/workbench/WardView'
import NewInpatientEncounterModal from '@/components/workbench/NewInpatientEncounterModal'
import ComplianceBar from '@/components/workbench/ComplianceBar'
import InpatientHeader from '@/components/workbench/InpatientHeader'
import InpatientRightPanel from '@/components/workbench/InpatientRightPanel'
import ProgressNotePanel from '@/components/workbench/ProgressNotePanel'
import WorkbenchStatusBar from '@/components/workbench/WorkbenchStatusBar'
import CancelEncounterModal from '@/components/workbench/CancelEncounterModal'
import { TimelineItem } from '@/domain/inpatient'

const { Content } = Layout

const ACCENT = '#059669'

const RECORD_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊病历',
  admission_note: '入院记录',
  first_course_record: '首次病程',
  course_record: '日常病程',
  senior_round: '上级查房',
  discharge_record: '出院记录',
}

export default function InpatientWorkbenchPage() {
  // App.useApp() 的 modal 实例能 consume 主题 context；不要用 Modal.info 静态方法
  const { modal } = App.useApp()
  const { user } = useAuthStore()
  const currentPatient = useCurrentPatient()
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const setRecordType = useRecordStore(s => s.setRecordType)

  useEffect(() => {
    setRecordType('admission_note')
    // setRecordType 来自 zustand store，引用稳定；只需挂载时设置一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 刷新页面后从后端 snapshot 回填 patientCache（patient + patient_profile）
  // 否则 PatientProfileCard 会因 cache 为空而显示空白
  useEnsureSnapshotHydrated()

  const {
    historyOpen,
    setHistoryOpen,
    openHistory,
    viewRecord,
    setViewRecord,
    handleResume,
    handleLogout,
    cancelOpen,
    openCancel,
    closeCancel,
    handleCancelEncounter,
  } = useWorkbenchBase({
    visitTypeFilter: 'inpatient',
    defaultRecordType: 'admission_note',
    resumeSuccessMsg: name => `已恢复「${name}」的住院接诊工作台`,
    resumeErrorMsg: '恢复住院接诊失败，请重试',
  })

  const [modalOpen, setModalOpen] = useState(false)
  const [imagingOpen, setImagingOpen] = useState(false)
  // 时间轴选中项（null = 默认显示 RecordEditor；progress_note = 切到 ProgressNotePanel）
  const [selectedNote, setSelectedNote] = useState<TimelineItem | null>(null)
  // 外部触发时间轴刷新（签发/保存后 +1）
  const [timelineRefresh, setTimelineRefresh] = useState(0)
  // 外部触发病区列表刷新（出院 / 新建接诊后 +1）
  const [wardRefresh, setWardRefresh] = useState(0)

  // 出院成功回调：清空当前接诊，触发病区列表重新拉取
  const handleDischarged = () => {
    resetAllWorkbench()
    setWardRefresh(n => n + 1)
  }

  // 切换患者时清空时间轴选中，避免跨患者串数据
  useEffect(() => {
    setSelectedNote(null)
  }, [currentEncounterId])

  /** 病区列表点选某患者后传过来的最小载荷（仅取 encounter_id / patient_name 传 handleResume） */
  interface WardPatientItem {
    encounter_id: string
    patient_name?: string
  }
  // 从病区列表选择患者，复用 handleResume 加载工作台快照
  const handleSelectWardPatient = async (p: WardPatientItem) => {
    await handleResume({ encounter_id: p.encounter_id, patient_name: p.patient_name })
  }

  // 新建住院接诊成功回调（与门诊端对齐）——副作用编排在 encounterCreated.tsx，
  // 这里只透传 modal 实例（App.useApp 的 modal 能 consume 主题 context）
  const handleEncounterCreated = (res: InpatientEncounterCreatedRes) =>
    handleInpatientEncounterCreated(res, modal)

  // 中间编辑区：选中病程记录时切换到 ProgressNotePanel，否则保持 RecordEditor
  const renderCenterEditor = () => {
    if (selectedNote && selectedNote.type === 'progress_note') {
      return (
        <div
          style={{
            height: '100%',
            background: 'var(--surface)',
            borderRadius: 12,
            border: '1px solid var(--border)',
            overflow: 'hidden',
            boxShadow: 'var(--shadow-sm)',
          }}
        >
          <ProgressNotePanel item={selectedNote} onSaved={() => setTimelineRefresh(n => n + 1)} />
        </div>
      )
    }
    return <RecordEditor />
  }

  return (
    <Layout style={{ height: '100vh', background: 'var(--bg)' }}>
      <InpatientHeader
        currentPatient={currentPatient}
        currentEncounterId={currentEncounterId}
        user={user}
        onOpenHistory={openHistory}
        onOpenImaging={() => setImagingOpen(true)}
        onLogout={handleLogout}
        onDischarged={handleDischarged}
        onOpenCancel={openCancel}
      />

      <Content
        style={{ display: 'flex', overflow: 'hidden', gap: 0, padding: 10, position: 'relative' }}
      >
        {/* 最左：病区视图侧栏 */}
        <div
          style={{
            width: 210,
            background: 'var(--surface)',
            borderRadius: 12,
            border: '1px solid var(--border)',
            overflow: 'hidden',
            flexShrink: 0,
            boxShadow: 'var(--shadow-sm)',
            marginRight: 10,
          }}
        >
          <WardView
            onNewEncounter={() => setModalOpen(true)}
            onSelectPatient={handleSelectWardPatient}
            refreshSignal={wardRefresh}
            selectedEncounterId={currentEncounterId}
          />
        </div>

        {/* 右侧主工作区（竖向：时效栏 + 三栏面板） */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            minWidth: 0,
          }}
        >
          {/* 时效合规提醒栏 */}
          <ComplianceBar encounterId={currentEncounterId} />

          {/* 三栏面板 */}
          <div
            style={{
              flex: 1,
              display: 'flex',
              gap: 10,
              overflow: 'hidden',
            }}
          >
            {/* 问诊面板 */}
            <div
              style={{
                width: 300,
                background: 'var(--surface)',
                borderRadius: 12,
                border: '1px solid var(--border)',
                overflow: 'auto',
                flexShrink: 0,
                boxShadow: 'var(--shadow-sm)',
              }}
            >
              <InpatientInquiryPanel />
            </div>

            {/* 中间编辑区（入院记录 or 病程记录） */}
            <div style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>{renderCenterEditor()}</div>

            {/* 右侧：AI建议 + 病程记录 + 问题列表 + 体征 */}
            <InpatientRightPanel
              selectedNote={selectedNote}
              setSelectedNote={setSelectedNote}
              timelineRefresh={timelineRefresh}
              setTimelineRefresh={setTimelineRefresh}
            />
          </div>
        </div>

        {/* 未选患者蒙层：提示从左侧选患者 */}
        {!currentPatient && (
          <div
            style={{
              position: 'absolute',
              // 不覆盖病区侧栏（left = 210 + 10gap + 10padding = 230px）
              left: 220,
              top: 0,
              right: 0,
              bottom: 0,
              background: 'rgba(248,250,252,0.92)',
              backdropFilter: 'blur(3px)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 16,
              zIndex: 50,
              borderRadius: '0 12px 12px 0',
            }}
          >
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <span style={{ fontSize: 14, color: 'var(--text-3)' }}>
                  从左侧病区选择患者，或新建住院接诊
                </span>
              }
            />
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setModalOpen(true)}
              size="large"
              style={{ borderRadius: 20, background: ACCENT, borderColor: ACCENT }}
            >
              新建住院接诊
            </Button>
          </div>
        )}
      </Content>

      <NewInpatientEncounterModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSuccess={handleEncounterCreated}
      />

      {/* 住院端历史病历抽屉：
          - 选中病区患者时 → 按患者聚焦，直接显示该患者全部签发病历
          - 未选中患者（如刚办理出院后）→ 自动切到搜索模式，能搜到已出院患者
            避免出现"出院后无法查看其签发病历"的死循环 */}
      <PatientHistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        patientId={currentPatient?.id || null}
        patientName={currentPatient?.name}
        patientGender={currentPatient?.gender ?? undefined}
        patientAge={currentPatient?.age ?? undefined}
        searchable={!currentPatient?.id}
        // 住院端选中病区患者时一定在院（出院后 currentPatient 已被清空走搜索路径）
        patientHasActiveInpatient={currentPatient?.id ? true : undefined}
        onView={setViewRecord}
        recordTypeLabel={t => RECORD_TYPE_LABEL[t] || t}
      />

      <RecordViewModal
        record={viewRecord}
        onClose={() => setViewRecord(null)}
        accentColor={ACCENT}
        tagColor="green"
        recordTypeLabel={t => RECORD_TYPE_LABEL[t] || t}
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
