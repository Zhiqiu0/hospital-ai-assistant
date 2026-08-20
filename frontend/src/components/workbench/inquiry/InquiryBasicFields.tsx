/**
 * 问诊基础字段（components/workbench/inquiry/InquiryBasicFields.tsx）
 *
 * 内容：主诉 + 现病史。复诊时现病史顶部加黄色 banner 提示必填症状变化。
 * 现病史下方有常用句式标签（2026-08-19）：一键追加"否认发热接触/一般情况"等
 * 模板句——医生点击即确认，AI 不代写；追加走 form.setFieldsValue，
 * 保存/生成读取的是表单值所以能带上，脏标记由 onAppendPhrase 回调补打。
 */
import { Form, Input, Tag } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import {
  INQUIRY_PHRASES,
  REVISIT_HPI_PHRASES,
  appendPhrase,
} from '../patientProfile/profilePhrases'

const { TextArea } = Input

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-2)',
  marginBottom: 4,
  display: 'block',
}

const fs: React.CSSProperties = { marginBottom: 10 }

interface InquiryBasicFieldsProps {
  isFirstVisit: boolean
  /** 输入锁定（病历已生成）：锁定时隐藏句式标签——Tag 不是表单控件，
   *  Form disabled 级联管不到它，不隐藏会出现"只读框旁的标签还能改值" */
  locked?: boolean
  /** 患者性别：女性才显示月经史输入（法定"育龄女性无月经史扣5分"，2026-08-20） */
  patientGender?: string | null
  /** 句式追加后回调（父组件用来打 isDirty——setFieldsValue 不触发 onValuesChange） */
  onAppendPhrase?: () => void
}

export default function InquiryBasicFields({
  isFirstVisit,
  patientGender,
  locked,
  onAppendPhrase,
}: InquiryBasicFieldsProps) {
  const form = Form.useFormInstance()
  const isFemale = (patientGender || '').trim() === '女' || patientGender === 'female'
  // 已插入的句式不再显示标签（与患者档案卡行为一致），用 useWatch 感知当前值
  const hpiValue = (Form.useWatch('history_present_illness', form) as string) || ''
  // 复诊追加"病史同前/较前好转"等专用句式（医院真实复诊的高频写法），初诊不显示
  const hpiPhrases = [
    ...(isFirstVisit ? [] : REVISIT_HPI_PHRASES),
    ...(INQUIRY_PHRASES.history_present_illness ?? []),
  ].filter(p => !hpiValue.includes(p.text))
  const appendHpiPhrase = (text: string) => {
    const cur = (form.getFieldValue('history_present_illness') as string) || ''
    if (cur.includes(text)) return
    form.setFieldsValue({ history_present_illness: appendPhrase(cur, text) })
    onAppendPhrase?.()
  }
  return (
    <>
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

      {/* 复诊警示必须放在 Form.Item 外面：
          Form.Item 带 name 时只允许一个子节点（antd 会把 value/onChange 注入这个子节点），
          多子节点会触发 "[antd: Form.Item] must have a single child element" 警告。 */}
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
      <Form.Item
        style={fs}
        name="history_present_illness"
        label={
          <span style={labelStyle}>
            现病史 <span style={{ color: '#ef4444' }}>*</span>
          </span>
        }
      >
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
      {/* 现病史常用句式：点标签追加（不覆盖已有内容）；锁定时隐藏 */}
      {!locked && hpiPhrases.length > 0 && (
        <div style={{ marginTop: -6, marginBottom: 10, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {hpiPhrases.map(p => (
            <Tag
              key={p.label}
              icon={<PlusOutlined />}
              onClick={() => appendHpiPhrase(p.text)}
              title={p.text}
              style={{ cursor: 'pointer', fontSize: 11, margin: 0, userSelect: 'none' }}
            >
              {p.label}
            </Tag>
          ))}
        </div>
      )}
      {/* 月经史：仅女性显示（法定评分"育龄女性无月经史扣5分"，2026-08-20） */}
      {isFemale && (
        <Form.Item
          style={fs}
          name="menstrual_history"
          label={<span style={labelStyle}>月经史</span>}
        >
          <TextArea
            rows={1}
            placeholder="初潮年龄、周期、经量、末次月经；绝经填「XX岁绝经」"
            style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
          />
        </Form.Item>
      )}
    </>
  )
}
