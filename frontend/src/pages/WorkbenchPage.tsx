/**
 * 门诊/急诊工作台页面（pages/WorkbenchPage.tsx）
 *
 * 门诊和急诊接诊的核心工作台，通过 mode prop 区分：
 *   mode="outpatient"（默认）→ 门诊  mode="emergency" → 急诊
 *
 * 布局：三栏响应式布局
 *   左栏：InquiryPanel（问诊表单）+ VoiceInputCard（语音录入）
 *   中栏：RecordEditor（病历编辑区）+ FinalRecordModal（签发弹窗）
 *   右栏：Tab 切换 QCIssuePanel / AISuggestionPanel / LabReportTab
 *
 * 顶栏功能：
 *   - 登记新患者（PatientSearch + 接诊登记）
 *   - 历史病历查看（HistoryDrawer）
 *   - 续接诊（ResumeDrawer）
 *   - 登出（useWorkbenchBase.handleLogout）
 *
 * 工作台重置：
 *   每次登记新患者时调用 workbenchStore.reset()，
 *   清空所有问诊、病历、质控状态，开始新接诊。
 */
import { useState, useEffect } from 'react'
import { Layout, Button, Typography, Space, Tag, message, Avatar, Divider, Empty, Tabs } from 'antd'
import {
  LogoutOutlined,
  PlusOutlined,
  MedicineBoxOutlined,
  CameraOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { useWorkbenchStore } from '@/store/workbenchStore'
import { applyQuickStartResult } from '@/store/encounterIntake'
import { useWorkbenchBase } from '@/hooks/useWorkbenchBase'
import { useEnsureSnapshotHydrated } from '@/hooks/useEnsureSnapshotHydrated'
import InquiryPanel from '@/components/workbench/InquiryPanel'
import RecordEditor from '@/components/workbench/RecordEditor'
import AISuggestionPanel from '@/components/workbench/AISuggestionPanel'
import ImagingUploadModal from '@/components/workbench/ImagingUploadModal'
import HistoryDrawer from '@/components/workbench/HistoryDrawer'
import RecordViewModal from '@/components/workbench/RecordViewModal'
import LabReportTab from '@/components/workbench/LabReportTab'
import NewEncounterModal from '@/components/workbench/NewEncounterModal'

const { Header, Content } = Layout
const { Text } = Typography

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
  const {
    currentPatient,
    currentEncounterId,
    setCurrentEncounter,
    setVisitMeta,
    setPatientReused,
    setPreviousRecordContent,
    reset,
  } = useWorkbenchStore()

  // 无接诊时清空残留数据（仅在页面初次挂载时执行，避免新建接诊时的竞态问题）
  useEffect(() => {
    if (!currentEncounterId) reset()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 刷新页面后从后端 snapshot 回填 patientCache（patient + patient_profile）
  // 否则 PatientProfileCard 会因 cache 为空而显示空白
  useEnsureSnapshotHydrated()

  // 切换门诊/急诊页面时同步 visitType 到 store
  useEffect(() => {
    const defaultType = isEmergency ? 'emergency' : 'outpatient'
    const { currentVisitType, isFirstVisit } = useWorkbenchStore.getState()
    if (currentVisitType !== defaultType) {
      setVisitMeta(isFirstVisit, defaultType)
    }
  }, [isEmergency])

  const {
    historyOpen,
    setHistoryOpen,
    historyRecords,
    historyLoading,
    openHistory,
    viewRecord,
    setViewRecord,
    handleLogout,
  } = useWorkbenchBase({
    resumeSuccessMsg: name => `已恢复「${name}」的接诊工作台`,
  })

  const [modalOpen, setModalOpen] = useState<'new' | 'returning' | null>(null)
  const [imagingOpen, setImagingOpen] = useState(false)

  // 新建接诊成功回调：更新 store 并处理住院跳转
  // resumed=true 表示后端检测到已有进行中接诊，直接续接而非新建
  const handleEncounterCreated = (res: any, visitType: string) => {
    reset()
    // 1.6 数据接入：把 patient + patient_profile 写入 patientCacheStore，
    // 并设置 activeEncounterStore；老的 workbenchStore 指针字段暂时并存。
    applyQuickStartResult(res)
    setCurrentEncounter(
      {
        id: res.patient.id,
        name: res.patient.name,
        gender: res.patient.gender,
        age: res.patient.age,
      },
      res.encounter_id
    )
    setVisitMeta(!res.patient_reused, res.visit_type || visitType)
    setPatientReused(!!res.patient_reused)
    setPreviousRecordContent(res.previous_record_content || null)
    if (res.resumed) {
      message.info(`「${res.patient.name}」有未完成的接诊，已自动恢复`)
    } else {
      message.success(`已为「${res.patient.name}」开始接诊`)
    }
    if ((res.visit_type || visitType) === 'inpatient') navigate('/inpatient')
  }

  return (
    <Layout style={{ height: '100vh', background: 'var(--bg)' }}>
      {/* Header */}
      <Header
        style={{
          height: 58,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: '#fff',
          borderBottom: '1px solid var(--border)',
          padding: '0 20px',
          boxShadow: '0 1px 8px rgba(0,0,0,0.06)',
          zIndex: 100,
          flexShrink: 0,
          position: 'relative',
        }}
      >
        {/* Top accent stripe */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: 3,
            background: `linear-gradient(90deg, ${accentColor}, ${accentLight}, ${accentLighter})`,
            borderRadius: '0 0 2px 2px',
          }}
        />

        {/* Logo */}
        <Space size={10}>
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 9,
              background: `linear-gradient(135deg, ${accentColor}, ${accentLight})`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: `0 2px 8px ${isEmergency ? 'rgba(220,38,38,0.35)' : 'rgba(37,99,235,0.35)'}`,
            }}
          >
            <MedicineBoxOutlined style={{ color: '#fff', fontSize: 16 }} />
          </div>
          <Text strong style={{ fontSize: 16, color: 'var(--text-1)', letterSpacing: '-0.4px' }}>
            MediScribe
          </Text>
          <Tag color={isEmergency ? 'red' : 'blue'} style={{ margin: 0, borderRadius: 20 }}>
            {isEmergency ? '急诊部' : '门诊部'}
          </Tag>
        </Space>

        {/* Patient info (center) */}
        <div
          style={{
            position: 'absolute',
            left: '50%',
            transform: 'translateX(-50%)',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          {currentPatient ? (
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
                border: '1px solid #bbf7d0',
                borderRadius: 8,
                padding: '4px 12px',
                boxShadow: '0 1px 4px rgba(5,150,105,0.1)',
                lineHeight: 1,
              }}
            >
              <div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: '#22c55e',
                  boxShadow: '0 0 0 2px rgba(34,197,94,0.25)',
                  flexShrink: 0,
                }}
              />
              <Text style={{ fontSize: 13, fontWeight: 700, color: '#065f46' }}>
                {currentPatient.name}
              </Text>
              {currentPatient.gender && currentPatient.gender !== 'unknown' && (
                <Text style={{ fontSize: 12, color: '#059669' }}>
                  {currentPatient.gender === 'male' ? '男' : '女'}
                </Text>
              )}
              {currentPatient.age != null && currentPatient.age > 0 && (
                <Text style={{ fontSize: 12, color: '#059669' }}>{currentPatient.age}岁</Text>
              )}
              <Text
                style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace', marginLeft: 4 }}
              >
                #{currentEncounterId?.slice(-6).toUpperCase()}
              </Text>
            </div>
          ) : (
            <Text style={{ fontSize: 13, color: 'var(--text-4)' }}>未选择患者</Text>
          )}
          <Button
            icon={<PlusOutlined />}
            size="small"
            type="primary"
            onClick={() => setModalOpen('new')}
            style={{ borderRadius: 20, fontSize: 12, height: 30, paddingInline: 14 }}
          >
            初诊
          </Button>
          <Button
            size="small"
            onClick={() => setModalOpen('returning')}
            style={{ borderRadius: 20, fontSize: 12, height: 30, paddingInline: 14 }}
          >
            复诊
          </Button>
        </div>

        {/* Right: user actions */}
        <Space size={4} style={{ flexShrink: 0 }}>
          <Button
            size="small"
            type="text"
            onClick={openHistory}
            style={{ color: 'var(--text-3)', fontSize: 12, borderRadius: 8 }}
          >
            历史病历
          </Button>
          <Button
            icon={<CameraOutlined />}
            size="small"
            type="text"
            onClick={() => setImagingOpen(true)}
            style={{ color: '#7c3aed', fontSize: 12, borderRadius: 8 }}
          >
            影像分析
          </Button>
          <Button
            size="small"
            type="text"
            onClick={() => navigate(isEmergency ? '/workbench' : '/emergency')}
            style={{
              color: isEmergency ? '#2563eb' : '#dc2626',
              fontSize: 12,
              borderRadius: 8,
              fontWeight: 500,
            }}
          >
            切换至{isEmergency ? '门诊' : '急诊'}
          </Button>
          <Divider type="vertical" style={{ margin: '0 4px', borderColor: 'var(--border)' }} />
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '4px 10px',
              borderRadius: 8,
              background: 'var(--surface-2)',
            }}
          >
            <Avatar
              size={26}
              style={{
                background: `linear-gradient(135deg, ${accentColor}, ${accentLighter})`,
                fontSize: 11,
                flexShrink: 0,
              }}
            >
              {user?.real_name?.[0]}
            </Avatar>
            <div style={{ lineHeight: 1.3 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-2)' }}>
                {user?.real_name}
              </div>
              {user?.department_name && (
                <div style={{ fontSize: 11, color: 'var(--text-4)' }}>{user.department_name}</div>
              )}
            </div>
          </div>
          <Button
            icon={<LogoutOutlined />}
            size="small"
            type="text"
            onClick={handleLogout}
            style={{ color: 'var(--text-3)', borderRadius: 8 }}
          />
        </Space>
      </Header>

      {/* Content */}
      <Content
        style={{ display: 'flex', overflow: 'hidden', gap: 10, padding: 10, position: 'relative' }}
      >
        {/* Left: Inquiry + Lab Reports */}
        <div
          style={{
            width: 320,
            background: '#fff',
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
                  <div style={{ height: 'calc(100vh - 116px)' }}>
                    <InquiryPanel />
                  </div>
                ),
              },
              {
                key: 'lab',
                label: '检验报告',
                children: (
                  <div style={{ height: 'calc(100vh - 116px)' }}>
                    <LabReportTab />
                  </div>
                ),
              },
            ]}
          />
        </div>

        {/* Center: Record editor */}
        <div style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
          <RecordEditor />
        </div>

        {/* Right: AI suggestions */}
        <div
          style={{
            width: 320,
            background: '#fff',
            borderRadius: 12,
            border: '1px solid var(--border)',
            overflow: 'hidden',
            flexShrink: 0,
            boxShadow: 'var(--shadow-sm)',
          }}
        >
          <AISuggestionPanel />
        </div>

        {/* No-patient overlay */}
        {!currentPatient && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              background: 'rgba(248,250,252,0.90)',
              backdropFilter: 'blur(3px)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 16,
              zIndex: 50,
              borderRadius: 8,
            }}
          >
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <span style={{ fontSize: 14, color: '#64748b' }}>
                  暂无接诊，请选择「初诊」或「复诊」开始
                </span>
              }
            />
            <Space>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setModalOpen('new')}
                size="large"
                style={{ borderRadius: 20 }}
              >
                初诊
              </Button>
              <Button
                onClick={() => setModalOpen('returning')}
                size="large"
                style={{ borderRadius: 20 }}
              >
                复诊
              </Button>
            </Space>
          </div>
        )}
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

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        records={historyRecords}
        loading={historyLoading}
        onView={setViewRecord}
        accentColor={accentColor}
        tagColor={isEmergency ? 'red' : 'blue'}
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
    </Layout>
  )
}
