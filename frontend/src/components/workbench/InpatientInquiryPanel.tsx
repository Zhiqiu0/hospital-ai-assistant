/**
 * 住院问诊面板（components/workbench/InpatientInquiryPanel.tsx）
 * 业务逻辑已提取至 hooks/useInpatientInquiryPanel.ts，此文件仅保留 JSX 渲染。
 * 1.6.2：8 个 profile 字段（既往/过敏/个人/婚育/月经/家族/用药/宗教）已迁到
 * PatientProfileCard，门诊/住院共用同一个卡片，档案数据跟随患者。
 * 当前子组件：SpecialAssessmentSection（专项评估，仅住院本次） / PhysicalExamSection。
 */
import { Form, Input, Button, Divider, Select, Tag } from 'antd'
import { SaveOutlined, CheckOutlined } from '@ant-design/icons'
import VoiceInputCard from './VoiceInputCard'
import PatientProfileCard from './PatientProfileCard'
import SpecialAssessmentSection from './SpecialAssessmentSection'
import PhysicalExamSection from './PhysicalExamSection'
import { useInpatientInquiryPanel } from '@/hooks/useInpatientInquiryPanel'

const { TextArea } = Input

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: '#475569',
  marginBottom: 4,
  display: 'block',
}

const sectionStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: '#2563eb',
  background: '#eff6ff',
  padding: '4px 8px',
  borderRadius: 4,
  marginBottom: 10,
  marginTop: 4,
  letterSpacing: 0.5,
}

const fieldStyle = { marginBottom: 12 }

export default function InpatientInquiryPanel() {
  const {
    form,
    isInputLocked,
    isDirty,
    setIsDirty,
    saving,
    onSave,
    painMarks,
    handleVitalFill,
    handleLabInsert,
    applyVoiceInquiry,
    applyVoiceToRecord,
    hasSavedInquiry,
    profileDirty,
    profileSaving,
    saveAll,
  } = useInpatientInquiryPanel()

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 面板标题 */}
      <div
        style={{
          padding: '14px 16px 12px',
          borderBottom: '1px solid #f1f5f9',
          background: '#fff',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>入院问诊录入</div>
          <Tag color="blue" style={{ fontSize: 10, lineHeight: '18px' }}>
            住院部
          </Tag>
        </div>
        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
          依据浙江省2021版住院病历评分标准
        </div>
      </div>

      {/* 表单主体 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
        <Form
          form={form}
          layout="vertical"
          size="small"
          onFinish={onSave}
          onValuesChange={() => setIsDirty(true)}
          disabled={isInputLocked}
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

          {/* 患者档案卡片：8 字段纵向跟随患者，与门诊共用同一个组件 */}
          <PatientProfileCard />

          {/* 语音录入卡片 */}
          <VoiceInputCard
            visitType="inpatient"
            getFormValues={() => form.getFieldsValue()}
            onApplyInquiry={applyVoiceInquiry}
            onApplyToRecord={isInputLocked ? applyVoiceToRecord : undefined}
          />

          {/* 病史陈述者 */}
          <Form.Item
            style={fieldStyle}
            name="history_informant"
            label={
              <span style={labelStyle}>
                病史陈述者 <span style={{ color: '#ef4444', fontSize: 10 }}>（缺失扣分）</span>
              </span>
            }
          >
            <Select
              placeholder="请选择病史提供者"
              style={{ width: '100%' }}
              size="small"
              allowClear
            >
              <Select.Option value="患者本人，病史可靠">患者本人（病史可靠）</Select.Option>
              <Select.Option value="患者家属（配偶），病史基本可靠">家属—配偶</Select.Option>
              <Select.Option value="患者家属（子女），病史基本可靠">家属—子女</Select.Option>
              <Select.Option value="患者家属（父母），病史基本可靠">家属—父母</Select.Option>
              <Select.Option value="陪护人员，病史可信度一般">陪护人员</Select.Option>
              <Select.Option value="患者意识障碍，由急救人员提供，病史不详">
                急救人员（患者意识障碍）
              </Select.Option>
            </Select>
          </Form.Item>

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* 一、主诉与现病史 */}
          <div style={sectionStyle}>一、主诉与现病史</div>

          <Form.Item
            style={fieldStyle}
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
              placeholder="症状 + 持续时间，能导出第一诊断，原则上不用诊断名称"
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
            />
          </Form.Item>

          <Form.Item
            style={fieldStyle}
            name="history_present_illness"
            label={<span style={labelStyle}>现病史</span>}
          >
            <TextArea
              rows={5}
              placeholder={
                '1.发病时间地点起病缓急及可能原因\n2.主要症状部位、性质、持续时间、程度、演变及伴随症状\n3.入院前诊治经过及效果\n4.一般情况（饮食、精神、睡眠、大小便）\n5.其他需治疗的疾病'
              }
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
            />
          </Form.Item>

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* 二、专项评估（住院本次评估，profile 字段在顶部 PatientProfileCard） */}
          <div style={sectionStyle}>二、专项评估</div>
          <SpecialAssessmentSection painMarks={painMarks} />

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* 三、体格检查与辅助检查 */}
          <div style={sectionStyle}>三、体格检查与辅助检查</div>
          <PhysicalExamSection
            handleVitalFill={handleVitalFill}
            handleLabInsert={handleLabInsert}
          />

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* 四、入院诊断 */}
          <div style={sectionStyle}>四、入院诊断</div>

          <Form.Item
            style={{ marginBottom: 0 }}
            name="admission_diagnosis"
            rules={[{ required: true, message: '请填写入院诊断' }]}
            label={
              <span style={labelStyle}>
                入院诊断 <span style={{ color: '#ef4444' }}>*</span>
              </span>
            }
          >
            <TextArea
              rows={3}
              placeholder={'1. 主要诊断（使用规范中文术语，主要诊断放首位）\n2. 其他诊断...'}
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
            />
          </Form.Item>
        </Form>
      </div>

      {/* 1.6.3 统一保存按钮：合并入院问诊 + 患者档案 */}
      <div
        style={{
          padding: '10px 16px',
          borderTop: '1px solid #f1f5f9',
          background: '#fff',
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
            if (isDirty) parts.push('入院问诊')
            label = `保存${parts.join('+')}`
          } else if (hasSavedInquiry) {
            label = '已保存 ✓'
          } else {
            label = '尚未填写问诊'
          }
          return (
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
                  ? 'linear-gradient(135deg, #0369a1, #0ea5e9)'
                  : hasSavedInquiry
                    ? '#86efac'
                    : '#e5e7eb',
                border: 'none',
                color: anyDirty ? '#fff' : hasSavedInquiry ? '#166534' : '#6b7280',
                transition: 'all 0.3s',
              }}
            >
              {label}
            </Button>
          )
        })()}
      </div>
    </div>
  )
}
