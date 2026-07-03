/**
 * 门诊/急诊问诊面板（components/workbench/InquiryPanel.tsx）
 *
 * 业务逻辑由 hooks/useInquiryPanel 提供；本文件只做 layout shell，
 * 把面板分块渲染：
 *   InquiryPanelHeader  → 标题 + 初诊/复诊切换
 *   PatientProfileCard  → 患者纵向档案（既往/过敏等 8 字段）
 *   ImagingReportsCard  → 既往影像报告（≥1 条才渲染）
 *   VoiceInputCard      → 语音录入
 *   InquiryTimeFields   → 就诊时间 + 病发时间
 *   InquiryBasicFields  → 主诉 + 现病史
 *   InquiryPhysicalExam → 生命体征 + 体检 + 中医四诊 + 辅助检查
 *   DiagnosisSection / TreatmentSection / EmergencySection
 *   EmergencyDispositionBar → 急诊流转（仅急诊）
 *   InquirySaveBar      → 保存 + 转住院
 */
import { Form, Divider, ConfigProvider, Button } from 'antd'
import { useState } from 'react'
import { HistoryOutlined } from '@ant-design/icons'
import { message } from '@/services/messageBridge'
import api from '@/services/api'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { buildInquiryData } from '@/utils/inquirySync'
import type { InquiryData } from '@/store/types'
import VoiceInputCard from './VoiceInputCard'
import DiagnosisSection from './DiagnosisSection'
import TreatmentSection from './TreatmentSection'
import EmergencySection from './EmergencySection'
import EmergencyDispositionBar from './EmergencyDispositionBar'
import PatientProfileCard from './PatientProfileCard'
import ImagingReportsCard from './ImagingReportsCard'
import CollapsibleSection from '@/components/common/CollapsibleSection'
import InquiryPanelHeader from './inquiry/InquiryPanelHeader'
import InquiryTimeFields from './inquiry/InquiryTimeFields'
import InquiryBasicFields from './inquiry/InquiryBasicFields'
import InquiryPhysicalExam from './inquiry/InquiryPhysicalExam'
import InquirySaveBar from './inquiry/InquirySaveBar'
import { useInquiryPanel } from '@/hooks/useInquiryPanel'

export default function InquiryPanel() {
  const {
    form,
    isInputLocked,
    isPolishing,
    isEmergency,
    isDirty,
    hasSavedInquiry,
    profileDirty,
    profileSaving,
    saveAll,
    setIsDirty,
    saving,
    onSave,
    currentPatient,
    applyVoiceInquiry,
    applyVoiceToRecord,
    visitNatureColor,
    visitTypeLabel,
    visitTypeColor,
    isFirstVisit,
    isPatientReused,
    currentVisitType,
    setVisitMeta,
    inquiry,
    updateInquiryFields,
    savedDisposition,
    handleAdmitToInpatient,
    handleAddObservationNote,
    hasUnsignedRecord,
  } = useInquiryPanel()

  const encounterId = useActiveEncounterStore(s => s.encounterId)
  const [syncing, setSyncing] = useState(false)

  // 一键同步上次病历：拉该患者上次接诊的文字病历（体征不带回，需本次重新测量）
  const handleSyncPrevious = async () => {
    if (!encounterId) return
    setSyncing(true)
    try {
      const res = (await api.get(`/encounters/${encounterId}/previous-record`)) as {
        source_visit_time: string | null
        fields: Partial<InquiryData>
      }
      if (!res.fields || Object.keys(res.fields).length === 0) {
        message.info('该患者暂无历史病历可同步')
        return
      }
      const nextValues = { ...form.getFieldsValue(), ...res.fields }
      form.setFieldsValue(nextValues)
      updateInquiryFields(buildInquiryData(nextValues) as unknown as InquiryData)
      setIsDirty(true)
      message.success('已同步上次病历，请核对并重新测量体征后保存')
    } catch {
      message.error('同步失败，请重试')
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <InquiryPanelHeader
        isInputLocked={isInputLocked}
        isPatientReused={isPatientReused}
        isFirstVisit={isFirstVisit}
        visitTypeLabel={visitTypeLabel}
        visitTypeColor={visitTypeColor}
        visitNatureColor={visitNatureColor}
        currentVisitType={currentVisitType}
        setVisitMeta={setVisitMeta}
        setIsDirty={setIsDirty}
      />

      {/* 一键同步上次病历（复诊参考：拉上次文字病历，体征不带回、需本次重测） */}
      {encounterId && !isInputLocked && (
        <div style={{ padding: '6px 16px 0', display: 'flex', justifyContent: 'flex-end' }}>
          <Button
            size="small"
            icon={<HistoryOutlined />}
            loading={syncing}
            onClick={handleSyncPrevious}
          >
            同步上次病历
          </Button>
        </div>
      )}

      {/* 表单主体 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '10px 16px' }}>
        <Form
          form={form}
          layout="vertical"
          size="small"
          onFinish={onSave}
          onValuesChange={() => setIsDirty(true)}
          disabled={isInputLocked}
          scrollToFirstError={{ behavior: 'smooth', block: 'center' }}
        >
          {isInputLocked && (
            <div
              style={{
                background: '#fef9c3',
                border: '1px solid #fde047',
                borderRadius: 6,
                padding: '6px 10px',
                marginBottom: 10,
                fontSize: 12,
                color: '#854d0e',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <span>🔒</span>
              <span>
                病历已生成，问诊信息仅供查看，请直接编辑右侧病历。语音录入将直接追记到病历章节。
              </span>
            </div>
          )}

          {/* 患者档案卡片（既往/过敏/个人/家族/月经/婚育/用药/宗教 8 字段，纵向跟随患者） */}
          <PatientProfileCard />

          {/* R1 sprint F-1：既往影像报告卡片，0 条时不渲染 */}
          <ImagingReportsCard patientId={currentPatient?.id} />

          {/* 语音录入卡片：未锁定时填左侧表单，锁定后追记到病历章节
              用 ConfigProvider componentDisabled={false} 重置 antd 的 disabled 上下文：
              外层 <Form disabled={isInputLocked}> 会通过 ConfigProvider 把 disabled
              透传给所有 antd 子组件（含 VoiceInputCard 里的 Button），导致锁定后
              「继续录音」/「清空重录」/「重新分析」全部点不动 —— 这与"锁定后语音
              仍可继续补录"的设计相悖。在此显式 reset，让语音卡片永远可交互。 */}
          <ConfigProvider componentDisabled={false}>
            <VoiceInputCard
              visitType="outpatient"
              getFormValues={() => form.getFieldsValue()}
              onApplyInquiry={applyVoiceInquiry}
              onApplyToRecord={isInputLocked ? applyVoiceToRecord : undefined}
            />
          </ConfigProvider>

          <InquiryTimeFields inquiry={inquiry} updateInquiryFields={updateInquiryFields} />

          <InquiryBasicFields isFirstVisit={isFirstVisit} />

          {/* 既往史/过敏史/个人史/月经史 已迁移至 PatientProfileCard（跟随患者纵向档案） */}

          <Divider style={{ margin: '8px 0 10px', borderColor: 'var(--border-subtle)' }} />

          <InquiryPhysicalExam isEmergency={isEmergency} />

          {/* 诊断区块（可折叠） */}
          <CollapsibleSection title="诊断" defaultOpen>
            <DiagnosisSection />
          </CollapsibleSection>

          {/* 治疗意见区块（可折叠） */}
          <CollapsibleSection title="治疗意见" defaultOpen>
            <TreatmentSection />
            {isEmergency && <EmergencySection />}
          </CollapsibleSection>
        </Form>
      </div>

      {/* 急诊流转提示栏 */}
      {isEmergency && (
        <EmergencyDispositionBar
          savedDisposition={savedDisposition}
          onAdmitToInpatient={handleAdmitToInpatient}
          onAddObservationNote={handleAddObservationNote}
        />
      )}

      <InquirySaveBar
        isInputLocked={isInputLocked}
        isPolishing={isPolishing}
        isDirty={isDirty}
        hasSavedInquiry={hasSavedInquiry}
        profileDirty={profileDirty}
        profileSaving={profileSaving}
        saving={saving}
        saveAll={saveAll}
        handleAdmitToInpatient={handleAdmitToInpatient}
        hasUnsignedRecord={hasUnsignedRecord}
      />
    </div>
  )
}
