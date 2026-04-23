/**
 * 体格检查与辅助检查区块（PhysicalExamSection.tsx）
 * 包含生命体征录入、体格检查文本、辅助检查（含化验单上传和套餐快选）。
 * 必须渲染在 Ant Design Form 上下文内。
 */
import { Form, Input } from 'antd'
import VitalSignsInput from './VitalSignsInput'
import LabOrderPopover from './LabOrderPopover'
import LabReportUploadButton from './LabReportUploadButton'

const { TextArea } = Input

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: '#475569',
  marginBottom: 4,
  display: 'block',
}

const fieldStyle = { marginBottom: 12 }

// 生命体征已独立到 VitalSignsInput，这里的 placeholder 只包含文字体检部分
const PHYSICAL_EXAM_PLACEHOLDER = [
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
].join('\n')

interface Props {
  handleLabInsert: (text: string) => void
}

export default function PhysicalExamSection({ handleLabInsert }: Props) {
  return (
    <>
      <VitalSignsInput />

      <Form.Item
        style={fieldStyle}
        name="physical_exam"
        label={
          <span style={labelStyle}>
            体格检查{' '}
            <span style={{ color: '#ef4444', fontSize: 10 }}>（仅文字描述，生命体征在上方录入）</span>
          </span>
        }
      >
        <TextArea
          rows={10}
          placeholder={PHYSICAL_EXAM_PLACEHOLDER}
          style={{ borderRadius: 6, fontSize: 12, resize: 'vertical', fontFamily: 'monospace' }}
        />
      </Form.Item>

      <Form.Item
        style={fieldStyle}
        name="auxiliary_exam"
        label={
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              width: '100%',
            }}
          >
            <span style={labelStyle}>辅助检查（入院前）</span>
            <div style={{ display: 'flex', gap: 6 }}>
              <LabReportUploadButton onInsert={handleLabInsert} />
              <LabOrderPopover onInsert={handleLabInsert} />
            </div>
          </div>
        }
      >
        <TextArea
          rows={3}
          placeholder="记录入院前与本次疾病相关的主要检查及结果；他院检查须注明机构名称和检查时间"
          style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
        />
      </Form.Item>
    </>
  )
}
