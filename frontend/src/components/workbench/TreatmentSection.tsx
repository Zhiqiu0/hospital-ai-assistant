/**
 * 治疗意见区块（TreatmentSection.tsx）
 * 治则治法、处理意见、复诊建议、注意事项四项。
 * 必须渲染在 Ant Design Form 上下文内。
 */
import { Form, Input } from 'antd'
import { MedicineBoxOutlined } from '@ant-design/icons'

const { TextArea } = Input

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: '#475569',
  marginBottom: 4,
  display: 'block',
}

const sectionHeaderStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: '#64748b',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  padding: '6px 0 4px',
}

const fs: React.CSSProperties = { marginBottom: 10 }

export default function TreatmentSection() {
  return (
    <>
      <div style={{ ...sectionHeaderStyle, display: 'flex', alignItems: 'center', gap: 6 }}>
        <MedicineBoxOutlined style={{ color: '#059669' }} />
        <span>治疗意见及措施</span>
      </div>

      <div
        style={{
          background: '#f0fdf4',
          border: '1px solid #bbf7d0',
          borderRadius: 8,
          padding: '10px 10px 4px',
          marginBottom: 10,
        }}
      >
        <Form.Item
          style={fs}
          name="treatment_method"
          label={<span style={{ ...labelStyle, color: '#059669' }}>治则治法</span>}
        >
          <Input
            placeholder="如：平肝潜阳、滋养肝肾；或：清热化痰、止咳平喘"
            style={{ borderRadius: 6, fontSize: 13 }}
          />
        </Form.Item>

        <Form.Item
          style={fs}
          name="treatment_plan"
          label={<span style={labelStyle}>处理意见</span>}
        >
          <TextArea
            rows={3}
            placeholder="检查建议、用药方案、中医治疗措施（针灸、推拿、中药等）"
            style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
          />
        </Form.Item>

        <Form.Item
          style={fs}
          name="followup_advice"
          label={
            <span style={labelStyle}>
              复诊建议 <span style={{ color: '#ef4444' }}>*</span>
            </span>
          }
        >
          <Input
            placeholder="如：2周后复诊，监测血压；如症状加重随时就诊"
            style={{ borderRadius: 6, fontSize: 13 }}
          />
        </Form.Item>

        <Form.Item
          style={{ marginBottom: 4 }}
          name="precautions"
          label={<span style={labelStyle}>注意事项</span>}
        >
          <TextArea
            rows={2}
            placeholder="饮食、生活方式、服药注意等"
            style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
          />
        </Form.Item>
      </div>
    </>
  )
}
