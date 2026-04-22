/**
 * 住院工作台页面（pages/InpatientWorkbenchPage.tsx）
 *
 * 住院接诊专用工作台，相比门诊有以下差异：
 *   - 问诊面板：InpatientInquiryPanel（含入院诊断、体征等住院专属字段）
 *   - 病历类型默认：inpatient
 *   - 续接诊列表：visitTypeFilter='inpatient'，只加载住院类接诊
 *   - 布局增加「病程记录」标签页（Progress Notes）
 *
 * 与 WorkbenchPage 的关系：
 *   住院工作台独立实现（非 mode prop 复用），
 *   因字段结构差异较大（主页布局、问诊面板均不同）。
 */
import { useState, useEffect } from 'react'
import { Layout, Button, Typography, Space, Tag, message, Avatar, Divider, Empty, Tabs } from 'antd'
import {
  LogoutOutlined,
  PlusOutlined,
  MedicineBoxOutlined,
  CameraOutlined,
  UnorderedListOutlined,
  HeartOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '@/store/authStore'
import { useWorkbenchStore } from '@/store/workbenchStore'
import { useWorkbenchBase } from '@/hooks/useWorkbenchBase'
import { useEnsureSnapshotHydrated } from '@/hooks/useEnsureSnapshotHydrated'
import InpatientInquiryPanel from '@/components/workbench/InpatientInquiryPanel'
import RecordEditor from '@/components/workbench/RecordEditor'
import AISuggestionPanel from '@/components/workbench/AISuggestionPanel'
import ImagingUploadModal from '@/components/workbench/ImagingUploadModal'
import HistoryDrawer from '@/components/workbench/HistoryDrawer'
import RecordViewModal from '@/components/workbench/RecordViewModal'
import WardView from '@/components/workbench/WardView'
import NewInpatientEncounterModal from '@/components/workbench/NewInpatientEncounterModal'
import ComplianceBar from '@/components/workbench/ComplianceBar'
import VitalsPanel from '@/components/workbench/VitalsPanel'
import ProblemListPanel from '@/components/workbench/ProblemListPanel'

const { Header, Content } = Layout
const { Text } = Typography

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
  const { user } = useAuthStore()
  const { currentPatient, currentEncounterId, setCurrentEncounter, setRecordType, reset } =
    useWorkbenchStore()

  useEffect(() => {
    setRecordType('admission_note')
  }, [])

  // 刷新页面后从后端 snapshot 回填 patientCache（patient + patient_profile）
  // 否则 PatientProfileCard 会因 cache 为空而显示空白
  useEnsureSnapshotHydrated()

  const {
    historyOpen,
    setHistoryOpen,
    historyRecords,
    historyLoading,
    openHistory,
    viewRecord,
    setViewRecord,
    handleResume,
    handleLogout,
  } = useWorkbenchBase({
    visitTypeFilter: 'inpatient',
    defaultRecordType: 'admission_note',
    resumeSuccessMsg: name => `已恢复「${name}」的住院接诊工作台`,
    resumeErrorMsg: '恢复住院接诊失败，请重试',
  })

  const [modalOpen, setModalOpen] = useState(false)
  const [imagingOpen, setImagingOpen] = useState(false)

  // 从病区列表选择患者，复用 handleResume 加载工作台快照
  const handleSelectWardPatient = async (p: any) => {
    await handleResume({ encounter_id: p.encounter_id, patient_name: p.patient_name })
  }

  // 新建住院接诊成功回调
  const handleEncounterCreated = (res: any) => {
    reset()
    setRecordType('admission_note')
    setCurrentEncounter(
      {
        id: res.patient.id,
        name: res.patient.name,
        gender: res.patient.gender,
        age: res.patient.age,
      },
      res.encounter_id
    )
    message.success(`已为「${res.patient.name}」开始住院接诊`)
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
        {/* Top accent stripe — green for inpatient */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: 3,
            background: 'linear-gradient(90deg, #065f46, #059669, #34d399)',
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
              background: 'linear-gradient(135deg, #065f46, #059669)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 2px 8px rgba(5,150,105,0.35)',
            }}
          >
            <MedicineBoxOutlined style={{ color: '#fff', fontSize: 16 }} />
          </div>
          <Text strong style={{ fontSize: 16, color: 'var(--text-1)', letterSpacing: '-0.4px' }}>
            MediScribe
          </Text>
          <Tag color="green" style={{ margin: 0, borderRadius: 20 }}>
            住院部
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
                住院 #{currentEncounterId?.slice(-6).toUpperCase()}
              </Text>
            </div>
          ) : (
            <Text style={{ fontSize: 13, color: 'var(--text-4)' }}>从左侧病区选择患者</Text>
          )}
        </div>

        {/* Right: user actions */}
        <Space size={4}>
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
                background: 'linear-gradient(135deg, #065f46, #34d399)',
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
        style={{ display: 'flex', overflow: 'hidden', gap: 0, padding: 10, position: 'relative' }}
      >
        {/* 最左：病区视图侧栏 */}
        <div
          style={{
            width: 210,
            background: '#fff',
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
              marginTop: currentEncounterId ? 0 : 0,
            }}
          >
            {/* 问诊面板 */}
            <div
              style={{
                width: 300,
                background: '#fff',
                borderRadius: 12,
                border: '1px solid var(--border)',
                overflow: 'auto',
                flexShrink: 0,
                boxShadow: 'var(--shadow-sm)',
              }}
            >
              <InpatientInquiryPanel />
            </div>

            {/* 病历编辑器 */}
            <div style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
              <RecordEditor />
            </div>

            {/* 右侧：AI建议 + 问题列表 + 生命体征 */}
            <div
              style={{
                width: 340,
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
                defaultActiveKey="ai"
                size="small"
                style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
                tabBarStyle={{ padding: '0 12px', marginBottom: 0, flexShrink: 0 }}
                items={[
                  {
                    key: 'ai',
                    label: 'AI 建议',
                    children: (
                      <div style={{ overflow: 'auto', height: '100%' }}>
                        <AISuggestionPanel />
                      </div>
                    ),
                  },
                  {
                    key: 'problems',
                    label: (
                      <span>
                        <UnorderedListOutlined /> 问题列表
                      </span>
                    ),
                    children: (
                      <div style={{ overflow: 'auto', height: '100%' }}>
                        <ProblemListPanel />
                      </div>
                    ),
                  },
                  {
                    key: 'vitals',
                    label: (
                      <span>
                        <HeartOutlined /> 体征
                      </span>
                    ),
                    children: (
                      <div style={{ overflow: 'auto', height: '100%' }}>
                        <VitalsPanel />
                      </div>
                    ),
                  },
                ]}
              />
            </div>
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
                <span style={{ fontSize: 14, color: '#64748b' }}>
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

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        records={historyRecords}
        loading={historyLoading}
        onView={setViewRecord}
        accentColor={ACCENT}
        tagColor="green"
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
    </Layout>
  )
}
