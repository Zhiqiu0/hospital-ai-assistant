/**
 * 门诊/急诊问诊面板（components/workbench/InquiryPanel.tsx）
 * 业务逻辑已提取至 hooks/useInquiryPanel.ts，此文件仅保留 JSX 渲染。
 * 各区块已拆分为独立子组件：TcmSection / DiagnosisSection / TreatmentSection /
 * EmergencySection / EmergencyDispositionBar。
 */
import { Form, Input, Button, Divider, Radio, Tag, DatePicker } from 'antd'
import {
  SaveOutlined,
  CheckOutlined,
  HeartOutlined,
  AlertOutlined,
  ClockCircleOutlined,
  MedicineBoxOutlined,
} from '@ant-design/icons'
import { Modal } from 'antd'
import VoiceInputCard from './VoiceInputCard'
import VitalSignsInput from './VitalSignsInput'
import TcmSection from './TcmSection'
import DiagnosisSection from './DiagnosisSection'
import TreatmentSection from './TreatmentSection'
import EmergencySection from './EmergencySection'
import EmergencyDispositionBar from './EmergencyDispositionBar'
import PatientProfileCard from './PatientProfileCard'
import CollapsibleSection from '@/components/common/CollapsibleSection'
import { useInquiryPanel } from '@/hooks/useInquiryPanel'

const { TextArea } = Input

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-2)',
  marginBottom: 4,
  display: 'block',
}

const fs: React.CSSProperties = { marginBottom: 10 }

export default function InquiryPanel() {
  const {
    form,
    isInputLocked,
    isEmergency,
    isDirty,
    hasSavedInquiry,
    profileDirty,
    profileSaving,
    saveAll,
    setIsDirty,
    saving,
    onSave,
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
  } = useInquiryPanel()

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 面板标题 + 初诊/复诊切换 */}
      <div
        style={{
          padding: '12px 16px 10px',
          borderBottom: '1px solid var(--border-subtle)',
          background: 'var(--surface)',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>问诊录入</div>
            <div style={{ fontSize: 11, color: 'var(--text-4)', marginTop: 1 }}>
              填写后保存，AI自动同步建议
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <Tag color={visitTypeColor} style={{ margin: 0, fontSize: 11 }}>
              {visitTypeLabel}
            </Tag>
            <Radio.Group
              size="small"
              value={isFirstVisit}
              onChange={e => {
                setVisitMeta(e.target.value, currentVisitType)
                setIsDirty(true)
              }}
              optionType="button"
              buttonStyle="solid"
              disabled={isInputLocked || isPatientReused}
            >
              <Radio.Button
                value={true}
                style={{
                  fontSize: 11,
                  padding: '0 8px',
                  height: 24,
                  lineHeight: '22px',
                  borderColor: visitNatureColor,
                  background: isFirstVisit ? visitNatureColor : undefined,
                }}
              >
                初诊
              </Radio.Button>
              <Radio.Button
                value={false}
                style={{ fontSize: 11, padding: '0 8px', height: 24, lineHeight: '22px' }}
              >
                复诊
              </Radio.Button>
            </Radio.Group>
          </div>
        </div>
      </div>

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

          {/* 语音录入卡片：未锁定时填左侧表单，锁定后追记到病历章节 */}
          <VoiceInputCard
            visitType="outpatient"
            getFormValues={() => form.getFieldsValue()}
            onApplyInquiry={applyVoiceInquiry}
            onApplyToRecord={isInputLocked ? applyVoiceToRecord : undefined}
          />

          {/* 时间信息 */}
          <div
            style={{
              background: 'var(--surface-2)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: '8px 10px',
              marginBottom: 10,
              display: 'flex',
              gap: 10,
              alignItems: 'flex-start',
            }}
          >
            <ClockCircleOutlined style={{ color: 'var(--text-3)', marginTop: 6, flexShrink: 0 }} />
            <div style={{ flex: 1, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Form.Item
                style={{ marginBottom: 0, flex: '1 1 140px' }}
                name="visit_time"
                label={
                  <span style={{ ...labelStyle, marginBottom: 2 }}>
                    就诊时间 <span style={{ color: '#ef4444' }}>*</span>
                  </span>
                }
              >
                <DatePicker
                  showTime={{ format: 'HH:mm', use12Hours: false }}
                  format="YYYY-MM-DD HH:mm"
                  placeholder="选择就诊时间"
                  style={{ width: '100%', borderRadius: 6, fontSize: 12 }}
                  size="small"
                  onChange={val =>
                    updateInquiryFields({
                      ...inquiry,
                      visit_time: val ? val.format('YYYY-MM-DD HH:mm') : '',
                    })
                  }
                />
              </Form.Item>
              <Form.Item
                style={{ marginBottom: 0, flex: '1 1 140px' }}
                name="onset_time"
                label={
                  <span style={{ ...labelStyle, marginBottom: 2 }}>
                    病发时间 <span style={{ color: '#ef4444' }}>*</span>
                  </span>
                }
                rules={[{ required: true, message: '请选择病发时间' }]}
              >
                <DatePicker
                  showTime={{ format: 'HH:mm', use12Hours: false }}
                  format="YYYY-MM-DD HH:mm"
                  placeholder="请选择病发时间"
                  style={{ width: '100%', borderRadius: 6, fontSize: 12 }}
                  size="small"
                  onChange={val =>
                    updateInquiryFields({
                      ...inquiry,
                      onset_time: val ? val.format('YYYY-MM-DD HH:mm') : '',
                    })
                  }
                />
              </Form.Item>
            </div>
          </div>

          {/* 基础问诊字段 */}
          <Form.Item
            style={fs}
            name="chief_complaint"
            rules={[{ required: true, message: '请输入主诉' }]}
            label={
              <span style={labelStyle}>
                主诉 <span style={{ color: '#ef4444' }}>*</span>
              </span>
            }
          >
            <TextArea
              rows={2}
              placeholder={
                isFirstVisit
                  ? '症状 + 持续时间，如：发热伴咳嗽3天'
                  : '本次就诊原因，可含诊断名称，如：高血压复诊'
              }
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
            />
          </Form.Item>

          <Form.Item
            style={fs}
            name="history_present_illness"
            label={
              <span style={labelStyle}>
                现病史 <span style={{ color: '#ef4444' }}>*</span>
              </span>
            }
          >
            {!isFirstVisit && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 6,
                  background: '#fffbeb',
                  border: '1px solid #fcd34d',
                  borderRadius: 6,
                  padding: '6px 10px',
                  marginBottom: 6,
                  fontSize: 12,
                  color: '#92400e',
                  lineHeight: 1.5,
                }}
              >
                <span style={{ fontSize: 14, flexShrink: 0 }}>⚠️</span>
                <span>
                  <b>复诊必填：</b>
                  须记录上次治疗后症状改变情况（好转／无变化／加重），否则质控不通过。
                </span>
              </div>
            )}
            <TextArea
              rows={isFirstVisit ? 4 : 5}
              placeholder={
                isFirstVisit
                  ? '起病经过、主要症状体征、诊治经过、一般情况（饮食/睡眠/二便）'
                  : '【必填】上次治疗后症状变化：好转/无变化/加重；本次主要症状；一般情况（饮食/睡眠/二便）'
              }
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
            />
          </Form.Item>

          {/* 既往史/过敏史/个人史/月经史 已迁移至 PatientProfileCard（跟随患者纵向档案） */}

          <Divider style={{ margin: '8px 0 10px', borderColor: 'var(--border-subtle)' }} />

          {/* 体格检查（可折叠） */}
          <CollapsibleSection title="体格检查" icon={<HeartOutlined />} accent="#0284c7" defaultOpen>
            {isEmergency ? (
              <div
                style={{
                  background: '#fef2f2',
                  border: '1px solid #fecaca',
                  borderRadius: 8,
                  padding: '8px 10px',
                  marginBottom: 10,
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    color: '#dc2626',
                    fontWeight: 600,
                    marginBottom: 6,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  <AlertOutlined /> 急诊生命体征（必填）
                </div>
                <VitalSignsInput />
              </div>
            ) : (
              <VitalSignsInput />
            )}

            <Form.Item
              style={fs}
              name="physical_exam"
              label={<span style={labelStyle}>一般体检</span>}
            >
              <TextArea
                rows={3}
                placeholder="各系统体检结果、阳性体征、必要阴性体征"
                style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
              />
            </Form.Item>

            {/* 中医四诊 */}
            <TcmSection />

            <Form.Item
              style={fs}
              name="auxiliary_exam"
              rules={[{ required: true, message: '请填写辅助检查，无检查项目请填写「暂无」' }]}
              label={
                <span style={labelStyle}>
                  辅助检查 <span style={{ color: '#ef4444' }}>*</span>
                </span>
              }
            >
              <TextArea
                rows={3}
                placeholder="已有检查结果原样填入；如无检查请填写「暂无」"
                style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
              />
            </Form.Item>
          </CollapsibleSection>

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

      {/* 1.6.3 统一保存按钮：合并问诊 + 患者档案两份数据的保存动作
           组合状态优先级（任一脏即"待保存"）：
             anyDirty=true                → 蓝色"保存（含未提交：档案/问诊/全部）"
             !anyDirty + hasSavedInquiry  → 绿色"已保存"
             !anyDirty + !hasSavedInquiry → 灰色"尚未填写"（disabled）
           注：profile 单独保存过不算"已保存"，因为问诊是这块面板的主任务 */}
      <div
        style={{
          padding: '10px 16px',
          borderTop: '1px solid var(--border-subtle)',
          background: 'var(--surface)',
          flexShrink: 0,
        }}
      >
        {(() => {
          const anyDirty = isDirty || profileDirty
          const anySaving = saving || profileSaving
          let label: string
          if (anyDirty) {
            const parts: string[] = []
            if (profileDirty) parts.push('档案')
            if (isDirty) parts.push('问诊')
            label = `保存${parts.join('+')}`
          } else if (hasSavedInquiry) {
            label = '已保存'
          } else {
            label = '尚未填写问诊'
          }
          // 转住院按钮的二次确认（门诊/急诊都显示；住院工作台不渲染 InquiryPanel，不会错触发）
          const confirmAdmit = () => {
            Modal.confirm({
              title: '转入住院',
              content: '确认将当前患者转入住院？已填的问诊信息和已签发的病历会作为入院参考带入。',
              okText: '确认转住院',
              cancelText: '取消',
              onOk: () => handleAdmitToInpatient(),
            })
          }
          return (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {/* 转住院按钮：低频但关键，二级样式，左侧放置，避免抢主 CTA */}
              <Button
                size="middle"
                icon={<MedicineBoxOutlined />}
                onClick={confirmAdmit}
                disabled={isInputLocked}
                style={{
                  borderRadius: 8,
                  height: 36,
                  fontWeight: 500,
                  color: '#059669',
                  borderColor: '#bbf7d0',
                  background: 'var(--surface)',
                  flexShrink: 0,
                }}
              >
                转住院
              </Button>
              <Button
                type="primary"
                icon={anyDirty ? <SaveOutlined /> : hasSavedInquiry ? <CheckOutlined /> : undefined}
                block
                disabled={isInputLocked || !anyDirty}
                loading={anySaving}
                onClick={saveAll}
                style={{
                  borderRadius: 8,
                  height: 36,
                  fontWeight: 600,
                  background: anyDirty
                    ? 'linear-gradient(135deg, #2563eb, #3b82f6)'
                    : hasSavedInquiry
                      ? '#86efac'
                      : '#e5e7eb',
                  border: 'none',
                  color: anyDirty ? 'var(--surface)' : hasSavedInquiry ? '#166534' : '#6b7280',
                  transition: 'all 0.3s',
                }}
              >
                {label}
              </Button>
            </div>
          )
        })()}
      </div>
    </div>
  )
}
