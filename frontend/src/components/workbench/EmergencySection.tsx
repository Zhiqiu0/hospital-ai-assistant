/**
 * 急诊附加项区块（EmergencySection.tsx）
 * 留观记录和患者去向，仅急诊模式下渲染。
 * 必须渲染在 Ant Design Form 上下文内。
 */
import { Divider, Form, Input, Select } from 'antd'
import { AlertOutlined } from '@ant-design/icons'

const { TextArea } = Input

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: '#475569',
  marginBottom: 4,
  display: 'block',
}

const fs: React.CSSProperties = { marginBottom: 10 }

export default function EmergencySection() {
  return (
    <>
      <Divider style={{ margin: '8px 0 10px', borderColor: '#fecaca' }} />
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: '#dc2626',
          textTransform: 'uppercase' as const,
          letterSpacing: '0.05em',
          padding: '6px 0 4px',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <AlertOutlined />
        <span>急诊附加项</span>
      </div>

      <Form.Item
        style={fs}
        name="observation_notes"
        label={<span style={labelStyle}>留观记录</span>}
      >
        <TextArea
          rows={3}
          placeholder="留观期间病情变化、处理措施..."
          style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
        />
      </Form.Item>

      <Form.Item
        style={fs}
        name="patient_disposition"
        label={<span style={labelStyle}>患者去向</span>}
      >
        <Select placeholder="选择患者去向" style={{ borderRadius: 6, fontSize: 13 }}>
          <Select.Option value="回家观察">回家观察</Select.Option>
          <Select.Option value="留院观察">留院观察</Select.Option>
          <Select.Option value="收入住院">收入住院</Select.Option>
          <Select.Option value="转院">转院</Select.Option>
          <Select.Option value="手术室">手术室</Select.Option>
        </Select>
      </Form.Item>
    </>
  )
}
