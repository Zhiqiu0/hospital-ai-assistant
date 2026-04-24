/**
 * 中医四诊区块（TcmSection.tsx）
 * 望诊、闻诊、舌象、脉象四个输入项，嵌套在 Collapse 内。
 * 必须渲染在 Ant Design Form 上下文内。
 */
import { Collapse, Form, Input } from 'antd'
import { MedicineBoxOutlined } from '@ant-design/icons'

const { Panel } = Collapse

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-2)',
  marginBottom: 4,
  display: 'block',
}

const fs: React.CSSProperties = { marginBottom: 10 }

export default function TcmSection() {
  return (
    <Collapse
      size="small"
      defaultActiveKey={['tcm']}
      style={{
        marginBottom: 10,
        borderRadius: 8,
        border: '1px solid #bae6fd',
        background: '#f0f9ff',
      }}
    >
      <Panel
        key="tcm"
        header={
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <MedicineBoxOutlined style={{ color: '#0284c7' }} />
            <span style={{ fontSize: 12, fontWeight: 700, color: '#0369a1' }}>中医四诊</span>
            <span style={{ fontSize: 10, color: '#7dd3fc' }}>望 · 闻 · 问 · 切</span>
          </div>
        }
      >
        <Form.Item
          style={fs}
          name="tcm_inspection"
          label={<span style={labelStyle}>望诊（神色形态）</span>}
        >
          <Input
            placeholder="如：神清气爽，面色略红，体形中等"
            style={{ borderRadius: 6, fontSize: 13 }}
          />
        </Form.Item>

        <Form.Item
          style={fs}
          name="tcm_auscultation"
          label={<span style={labelStyle}>闻诊（声音气味）</span>}
        >
          <Input placeholder="如：语声清晰，无异常气味" style={{ borderRadius: 6, fontSize: 13 }} />
        </Form.Item>

        <Form.Item
          style={fs}
          name="tongue_coating"
          label={
            <span style={{ ...labelStyle, color: '#0369a1' }}>
              舌象 <span style={{ color: '#ef4444' }}>*</span>
            </span>
          }
        >
          <Input
            placeholder="如：舌淡红，苔薄白；或：舌红苔黄腻"
            style={{ borderRadius: 6, fontSize: 13 }}
          />
        </Form.Item>

        <Form.Item
          style={{ marginBottom: 0 }}
          name="pulse_condition"
          label={
            <span style={{ ...labelStyle, color: '#0369a1' }}>
              脉象 <span style={{ color: '#ef4444' }}>*</span>
            </span>
          }
        >
          <Input placeholder="如：脉弦细；或：脉滑数" style={{ borderRadius: 6, fontSize: 13 }} />
        </Form.Item>
      </Panel>
    </Collapse>
  )
}
