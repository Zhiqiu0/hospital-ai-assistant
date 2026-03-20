import { useEffect, useState } from 'react'
import { Form, Input, Button, message, Divider, Select, Slider, Tag } from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import api from '@/services/api'
import VoiceInputCard from './VoiceInputCard'

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
  const [form] = Form.useForm()
  const { inquiry, currentPatient, setInquiry, currentEncounterId } = useWorkbenchStore()
  const [patientGender, setPatientGender] = useState<string>('unknown')

  useEffect(() => {
    form.setFieldsValue({
      chief_complaint: inquiry.chief_complaint,
      history_present_illness: inquiry.history_present_illness,
      past_history: inquiry.past_history,
      allergy_history: inquiry.allergy_history,
      personal_history: inquiry.personal_history,
      physical_exam: inquiry.physical_exam,
      history_informant: inquiry.history_informant,
      marital_history: inquiry.marital_history,
      menstrual_history: inquiry.menstrual_history,
      family_history: inquiry.family_history,
      current_medications: inquiry.current_medications,
      rehabilitation_assessment: inquiry.rehabilitation_assessment,
      religion_belief: inquiry.religion_belief,
      pain_assessment: inquiry.pain_assessment ? Number(inquiry.pain_assessment) : 0,
      vte_risk: inquiry.vte_risk,
      nutrition_assessment: inquiry.nutrition_assessment,
      psychology_assessment: inquiry.psychology_assessment,
      auxiliary_exam: inquiry.auxiliary_exam,
      admission_diagnosis: inquiry.admission_diagnosis || inquiry.initial_impression,
    })
    setPatientGender(currentPatient?.gender || 'unknown')
  }, [form, inquiry, currentEncounterId, currentPatient?.gender])

  const onSave = async (values: any) => {
    const painScore = values.pain_assessment ?? 0

    const inquiryData = {
      chief_complaint: values.chief_complaint || '',
      history_present_illness: values.history_present_illness || '',
      past_history: values.past_history || '',
      allergy_history: values.allergy_history || '',
      personal_history: values.personal_history || '',
      physical_exam: values.physical_exam || '',
      initial_impression: values.admission_diagnosis || '',
      history_informant: values.history_informant || '',
      marital_history: values.marital_history || '',
      menstrual_history: values.menstrual_history || '',
      family_history: values.family_history || '',
      current_medications: values.current_medications || '',
      rehabilitation_assessment: values.rehabilitation_assessment || '',
      religion_belief: values.religion_belief || '',
      pain_assessment: String(painScore),
      vte_risk: values.vte_risk || '',
      nutrition_assessment: values.nutrition_assessment || '',
      psychology_assessment: values.psychology_assessment || '',
      auxiliary_exam: values.auxiliary_exam || '',
      admission_diagnosis: values.admission_diagnosis || '',
    }
    setInquiry(inquiryData)
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, inquiryData).catch(() => {})
    }
    message.success({ content: '入院问诊信息已保存', duration: 1.5 })
  }

  const painMarks = { 0: '0', 2: '2', 4: '4', 6: '轻中', 8: '重', 10: '10' }

  const applyVoiceInquiry = (patch: any) => {
    const nextValues = { ...form.getFieldsValue(), ...patch }
    form.setFieldsValue({
      ...nextValues,
      pain_assessment: nextValues.pain_assessment ? Number(nextValues.pain_assessment) : 0,
      admission_diagnosis: nextValues.admission_diagnosis || nextValues.initial_impression,
    })

    const painScore = nextValues.pain_assessment ?? 0

    const data = {
      chief_complaint: nextValues.chief_complaint || '',
      history_present_illness: nextValues.history_present_illness || '',
      past_history: nextValues.past_history || '',
      allergy_history: nextValues.allergy_history || '',
      personal_history: nextValues.personal_history || '',
      physical_exam: nextValues.physical_exam || '',
      initial_impression: nextValues.admission_diagnosis || '',
      history_informant: nextValues.history_informant || '',
      marital_history: nextValues.marital_history || '',
      menstrual_history: nextValues.menstrual_history || '',
      family_history: nextValues.family_history || '',
      current_medications: nextValues.current_medications || '',
      rehabilitation_assessment: nextValues.rehabilitation_assessment || '',
      religion_belief: nextValues.religion_belief || '',
      pain_assessment: String(painScore),
      vte_risk: nextValues.vte_risk || '',
      nutrition_assessment: nextValues.nutrition_assessment || '',
      psychology_assessment: nextValues.psychology_assessment || '',
      auxiliary_exam: nextValues.auxiliary_exam || '',
      admission_diagnosis: nextValues.admission_diagnosis || '',
    }
    setInquiry(data)
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, data).catch(() => {})
    }
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div style={{
        padding: '14px 16px 12px',
        borderBottom: '1px solid #f1f5f9',
        background: '#fff',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>入院问诊录入</div>
          <Tag color="blue" style={{ fontSize: 10, lineHeight: '18px' }}>住院部</Tag>
        </div>
        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>依据浙江省2021版住院病历评分标准</div>
      </div>

      {/* Form */}
      <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
        <Form form={form} layout="vertical" size="small" onFinish={onSave}>
          <VoiceInputCard
            visitType="inpatient"
            getFormValues={() => form.getFieldsValue()}
            onApplyInquiry={applyVoiceInquiry}
          />

          {/* ── 病史陈述者 ── */}
          <Form.Item style={fieldStyle} name="history_informant"
            label={<span style={labelStyle}>病史陈述者 <span style={{ color: '#ef4444', fontSize: 10 }}>（缺失扣分）</span></span>}>
            <Select placeholder="请选择病史提供者" style={{ width: '100%' }} size="small" allowClear>
              <Select.Option value="患者本人，病史可靠">患者本人（病史可靠）</Select.Option>
              <Select.Option value="患者家属（配偶），病史基本可靠">家属—配偶</Select.Option>
              <Select.Option value="患者家属（子女），病史基本可靠">家属—子女</Select.Option>
              <Select.Option value="患者家属（父母），病史基本可靠">家属—父母</Select.Option>
              <Select.Option value="陪护人员，病史可信度一般">陪护人员</Select.Option>
              <Select.Option value="患者意识障碍，由急救人员提供，病史不详">急救人员（患者意识障碍）</Select.Option>
            </Select>
          </Form.Item>

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* ── 一、主诉与现病史 ── */}
          <div style={sectionStyle}>一、主诉与现病史</div>

          <Form.Item style={fieldStyle} name="chief_complaint"
            rules={[{ required: true, message: '请输入主诉' }]}
            label={<span style={labelStyle}>主诉 <span style={{ color: '#ef4444' }}>*</span></span>}>
            <TextArea rows={2} placeholder="症状 + 持续时间，能导出第一诊断，原则上不用诊断名称"
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Form.Item style={fieldStyle} name="history_present_illness"
            label={<span style={labelStyle}>现病史</span>}>
            <TextArea rows={5} placeholder="1.发病时间地点起病缓急及可能原因&#10;2.主要症状部位、性质、持续时间、程度、演变及伴随症状&#10;3.入院前诊治经过及效果&#10;4.一般情况（饮食、精神、睡眠、大小便）&#10;5.其他需治疗的疾病"
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* ── 二、既往史 ── */}
          <div style={sectionStyle}>二、既往史</div>

          <Form.Item style={fieldStyle} name="past_history"
            label={<span style={labelStyle}>既往史</span>}>
            <TextArea rows={3} placeholder="心脑血管、肺、肝、肾、内分泌系统疾病史；手术史、外伤史、传染病史、输血史、预防接种史、用药史"
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Form.Item style={fieldStyle} name="allergy_history"
            rules={[{ required: true, message: '过敏史为必填项（可填"否认过敏史"）' }]}
            label={<span style={labelStyle}>食物/药物过敏史 <span style={{ color: '#ef4444' }}>*</span></span>}>
            <Input placeholder="如：青霉素过敏 / 否认食物、药物过敏史" style={{ borderRadius: 6, fontSize: 13 }} />
          </Form.Item>

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* ── 三、个人史/婚育史/家族史 ── */}
          <div style={sectionStyle}>三、个人史 · 婚育史 · 家族史</div>

          <Form.Item style={fieldStyle} name="personal_history"
            label={<span style={labelStyle}>个人史</span>}>
            <TextArea rows={2} placeholder="出生地及长期居留地、生活习惯及嗜好、职业与工作条件、毒物/粉尘/放射性物质接触史、冶游史"
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Form.Item style={fieldStyle} name="marital_history"
            label={<span style={labelStyle}>婚育史</span>}>
            <TextArea rows={2} placeholder="婚姻状况、结婚年龄、配偶及子女健康状况"
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Form.Item style={{ ...fieldStyle }}
            label={<span style={labelStyle}>患者性别（用于判断是否需月经史）</span>}>
            <Select value={patientGender} onChange={setPatientGender} style={{ width: '100%' }} size="small">
              <Select.Option value="female">女性</Select.Option>
              <Select.Option value="male">男性</Select.Option>
              <Select.Option value="unknown">未知</Select.Option>
            </Select>
          </Form.Item>

          {patientGender === 'female' && (
            <Form.Item style={fieldStyle} name="menstrual_history"
              label={<span style={labelStyle}>月经史 <span style={{ color: '#ef4444' }}>*</span></span>}>
              <TextArea rows={2} placeholder="初潮年龄、行经期天数、间隔天数、末次月经时间（或闭经年龄）、月经量、痛经及生育情况"
                style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
            </Form.Item>
          )}

          <Form.Item style={fieldStyle} name="family_history"
            label={<span style={labelStyle}>家族史</span>}>
            <TextArea rows={2} placeholder="父母、兄弟、姐妹健康状况，有无遗传倾向疾病"
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* ── 四、专项评估 ── */}
          <div style={sectionStyle}>四、专项评估</div>

          <Form.Item style={fieldStyle} name="current_medications"
            label={<span style={labelStyle}>当前用药 <span style={{ color: '#ef4444', fontSize: 10 }}>（缺失扣1分）</span></span>}>
            <TextArea rows={2} placeholder="入院前正在使用的药物（药名、剂量、用法），无则填写：无"
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Form.Item style={fieldStyle} name="rehabilitation_assessment"
            label={<span style={labelStyle}>康复需求评估 <span style={{ color: '#ef4444', fontSize: 10 }}>（缺失扣1分）</span></span>}>
            <Select placeholder="请选择康复需求" style={{ width: '100%' }} size="small" allowClear>
              <Select.Option value="无特殊康复需求">无特殊康复需求</Select.Option>
              <Select.Option value="需肢体功能康复训练">需肢体功能康复训练</Select.Option>
              <Select.Option value="需语言/吞咽功能康复">需语言/吞咽功能康复</Select.Option>
              <Select.Option value="需心肺康复训练">需心肺康复训练</Select.Option>
              <Select.Option value="需综合康复干预">需综合康复干预</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item style={fieldStyle} name="religion_belief"
            label={<span style={labelStyle}>宗教信仰 <span style={{ color: '#ef4444', fontSize: 10 }}>（影响饮食/用药，缺失扣1分）</span></span>}>
            <Select placeholder="请选择" style={{ width: '100%' }} size="small" allowClear>
              <Select.Option value="无特殊宗教信仰，饮食无特殊要求">无特殊宗教信仰</Select.Option>
              <Select.Option value="回族，禁食猪肉及相关制品">回族（禁食猪肉）</Select.Option>
              <Select.Option value="佛教，素食为主">佛教（素食）</Select.Option>
              <Select.Option value="其他宗教信仰，需与患者进一步沟通">其他宗教信仰</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item style={fieldStyle} name="pain_assessment"
            label={<span style={labelStyle}>疼痛评分（NRS 0-10分）</span>}
            initialValue={0}>
            <Slider marks={painMarks} min={0} max={10} step={1}
              tooltip={{ formatter: (v) => `${v}分` }} />
          </Form.Item>

          <Form.Item style={fieldStyle} name="vte_risk"
            label={<span style={labelStyle}>VTE风险评估</span>}>
            <Select placeholder="请选择VTE风险等级" style={{ width: '100%' }} size="small" allowClear>
              <Select.Option value="低危">低危 — 基本预防措施</Select.Option>
              <Select.Option value="中危">中危 — 物理预防为主</Select.Option>
              <Select.Option value="高危">高危 — 药物+物理联合预防</Select.Option>
              <Select.Option value="极高危">极高危 — 积极预防治疗</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item style={fieldStyle} name="nutrition_assessment"
            label={<span style={labelStyle}>营养评估</span>}>
            <Select placeholder="请选择营养风险" style={{ width: '100%' }} size="small" allowClear>
              <Select.Option value="营养良好，无营养风险">营养良好，无营养风险</Select.Option>
              <Select.Option value="存在营养风险，需营养支持">存在营养风险，需营养支持</Select.Option>
              <Select.Option value="营养不良，需积极营养干预">营养不良，需积极营养干预</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item style={fieldStyle} name="psychology_assessment"
            label={<span style={labelStyle}>心理评估</span>}>
            <Select placeholder="请选择心理状态" style={{ width: '100%' }} size="small" allowClear>
              <Select.Option value="心理状态良好，无明显焦虑抑郁">心理状态良好</Select.Option>
              <Select.Option value="轻度焦虑，给予心理疏导">轻度焦虑，给予心理疏导</Select.Option>
              <Select.Option value="明显焦虑/抑郁，需心理科会诊">明显焦虑/抑郁，需心理科会诊</Select.Option>
            </Select>
          </Form.Item>

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* ── 五、体格检查与辅助检查 ── */}
          <div style={sectionStyle}>五、体格检查与辅助检查</div>

          <Form.Item style={fieldStyle} name="physical_exam"
            label={<span style={labelStyle}>体格检查 <span style={{ color: '#ef4444', fontSize: 10 }}>（需含各系统，缺项扣分）</span></span>}>
            <TextArea rows={10} placeholder={[
              'T:__ ℃  P:__ 次/分  R:__ 次/分  BP:__/__mmHg  SpO2:__%',
              '一般情况：发育正常，营养良好，神志清楚，自主体位，查体合作',
              '皮肤黏膜：无黄染，无皮疹，无出血点，无水肿',
              '全身浅表淋巴结：颈部、腋窝、腹股沟浅表淋巴结未触及肿大',
              '头颈部：头颅无畸形，眼鼻耳口腔未见异常，颈软，气管居中，甲状腺未肿大，颈静脉无怒张',
              '胸部（肺）：胸廓对称，叩诊清音，双肺呼吸音清，未闻及干湿啰音',
              '胸部（心脏）：心率__次/分，心律齐，心音正常，各瓣膜区未闻及病理性杂音',
              '腹部：腹平软，全腹无压痛及反跳痛，肝脾肋下未触及，肠鸣音4次/分',
              '脊柱四肢：脊柱无畸形及压痛，四肢关节活动正常，双下肢无水肿',
              '神经系统：生理反射正常，病理反射未引出',
              '专科检查：',
            ].join('\n')}
              style={{ borderRadius: 6, fontSize: 12, resize: 'vertical', fontFamily: 'monospace' }} />
          </Form.Item>

          <Form.Item style={fieldStyle} name="auxiliary_exam"
            label={<span style={labelStyle}>辅助检查（入院前）</span>}>
            <TextArea rows={3} placeholder="记录入院前与本次疾病相关的主要检查及结果；他院检查须注明机构名称和检查时间"
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>

          <Divider style={{ margin: '8px 0 10px', borderColor: '#f1f5f9' }} />

          {/* ── 六、入院诊断 ── */}
          <div style={sectionStyle}>六、入院诊断</div>

          <Form.Item style={{ marginBottom: 0 }} name="admission_diagnosis"
            rules={[{ required: true, message: '请填写入院诊断' }]}
            label={<span style={labelStyle}>入院诊断 <span style={{ color: '#ef4444' }}>*</span></span>}>
            <TextArea rows={3} placeholder="1. 主要诊断（使用规范中文术语，主要诊断放首位）&#10;2. 其他诊断..."
              style={{ borderRadius: 6, fontSize: 13, resize: 'none' }} />
          </Form.Item>
        </Form>
      </div>

      {/* Save button */}
      <div style={{
        padding: '10px 16px',
        borderTop: '1px solid #f1f5f9',
        background: '#fff',
        flexShrink: 0,
      }}>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          block
          onClick={() => form.submit()}
          style={{
            borderRadius: 8, height: 36, fontWeight: 600,
            background: 'linear-gradient(135deg, #0369a1, #0ea5e9)',
            border: 'none',
          }}
        >
          保存入院问诊信息
        </Button>
      </div>
    </div>
  )
}
