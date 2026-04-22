/**
 * 专项评估区块（SpecialAssessmentSection.tsx）
 * 仅含住院本次接诊的评估字段：康复需求 / 疼痛评分（NRS）/ VTE风险 / 营养评估 / 心理评估。
 * 1.6.2：当前用药、宗教信仰已迁到 PatientProfileCard（属于患者纵向档案）。
 * 必须渲染在 Ant Design Form 上下文内。
 */
import { Form, Select, Slider } from 'antd'

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: '#475569',
  marginBottom: 4,
  display: 'block',
}

const fieldStyle = { marginBottom: 12 }

interface Props {
  painMarks: Record<number, string>
}

export default function SpecialAssessmentSection({ painMarks }: Props) {
  return (
    <>
      <Form.Item
        style={fieldStyle}
        name="rehabilitation_assessment"
        label={
          <span style={labelStyle}>
            康复需求评估 <span style={{ color: '#ef4444', fontSize: 10 }}>（缺失扣1分）</span>
          </span>
        }
      >
        <Select placeholder="请选择康复需求" style={{ width: '100%' }} size="small" allowClear>
          <Select.Option value="无特殊康复需求">无特殊康复需求</Select.Option>
          <Select.Option value="需肢体功能康复训练">需肢体功能康复训练</Select.Option>
          <Select.Option value="需语言/吞咽功能康复">需语言/吞咽功能康复</Select.Option>
          <Select.Option value="需心肺康复训练">需心肺康复训练</Select.Option>
          <Select.Option value="需综合康复干预">需综合康复干预</Select.Option>
        </Select>
      </Form.Item>

      <Form.Item
        style={fieldStyle}
        name="pain_assessment"
        label={<span style={labelStyle}>疼痛评分（NRS 0-10分）</span>}
        initialValue={0}
      >
        <Slider
          marks={painMarks}
          min={0}
          max={10}
          step={1}
          tooltip={{ formatter: v => `${v}分` }}
        />
      </Form.Item>

      <Form.Item
        style={fieldStyle}
        name="vte_risk"
        label={<span style={labelStyle}>VTE风险评估</span>}
      >
        <Select placeholder="请选择VTE风险等级" style={{ width: '100%' }} size="small" allowClear>
          <Select.Option value="低危">低危 — 基本预防措施</Select.Option>
          <Select.Option value="中危">中危 — 物理预防为主</Select.Option>
          <Select.Option value="高危">高危 — 药物+物理联合预防</Select.Option>
          <Select.Option value="极高危">极高危 — 积极预防治疗</Select.Option>
        </Select>
      </Form.Item>

      <Form.Item
        style={fieldStyle}
        name="nutrition_assessment"
        label={<span style={labelStyle}>营养评估</span>}
      >
        <Select placeholder="请选择营养风险" style={{ width: '100%' }} size="small" allowClear>
          <Select.Option value="营养良好，无营养风险">营养良好，无营养风险</Select.Option>
          <Select.Option value="存在营养风险，需营养支持">存在营养风险，需营养支持</Select.Option>
          <Select.Option value="营养不良，需积极营养干预">营养不良，需积极营养干预</Select.Option>
        </Select>
      </Form.Item>

      <Form.Item
        style={fieldStyle}
        name="psychology_assessment"
        label={<span style={labelStyle}>心理评估</span>}
      >
        <Select placeholder="请选择心理状态" style={{ width: '100%' }} size="small" allowClear>
          <Select.Option value="心理状态良好，无明显焦虑抑郁">心理状态良好</Select.Option>
          <Select.Option value="轻度焦虑，给予心理疏导">轻度焦虑，给予心理疏导</Select.Option>
          <Select.Option value="明显焦虑/抑郁，需心理科会诊">
            明显焦虑/抑郁，需心理科会诊
          </Select.Option>
        </Select>
      </Form.Item>
    </>
  )
}
