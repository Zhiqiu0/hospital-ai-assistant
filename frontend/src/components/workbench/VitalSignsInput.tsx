/**
 * 生命体征快速录入组件（components/workbench/VitalSignsInput.tsx）
 *
 * 设计：
 *   - 受控于 antd Form：所有字段（temperature/pulse/respiration/bp_systolic/bp_diastolic/spo2/height/weight）
 *     通过 Form.Item 的 name 绑定到问诊表单，点"保存"时一起提交到后端。
 *   - 生命体征数据与 physical_exam 文字描述完全分离：体征数值只存在这里，
 *     AI 生成病历时后端会自动把体征合并到体检段前缀。
 *
 * 交互：
 *   用户可以手动录入数值，也可以由语音 AI 分析自动回填（语音返回 vital_signs
 *   结构体后，调用方 setFieldsValue({temperature: "36.5", pulse: "72", ...})）。
 */
import { Form, Input, Tooltip } from 'antd'

const inputStyle: React.CSSProperties = {
  borderRadius: 5,
  fontSize: 12,
  textAlign: 'center',
  padding: '2px 4px',
}

const fieldStyle: React.CSSProperties = { marginBottom: 0 }

export default function VitalSignsInput() {
  return (
    <div
      style={{
        background: '#f0f9ff',
        border: '1px solid #bae6fd',
        borderRadius: 8,
        padding: '10px 12px',
        marginBottom: 10,
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 700, color: '#0369a1', marginBottom: 8 }}>
        生命体征快速录入
      </div>

      {/* Row 1: T P R BP SpO2 */}
      <div
        style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}
      >
        <Tooltip title="体温 ℃">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: 'var(--text-2)', whiteSpace: 'nowrap' }}>T</span>
            <Form.Item style={fieldStyle} name="temperature">
              <Input placeholder="36.5" style={{ ...inputStyle, width: 52 }} />
            </Form.Item>
            <span style={{ fontSize: 11, color: 'var(--text-4)' }}>℃</span>
          </div>
        </Tooltip>

        <Tooltip title="脉搏 次/分">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: 'var(--text-2)' }}>P</span>
            <Form.Item style={fieldStyle} name="pulse">
              <Input placeholder="72" style={{ ...inputStyle, width: 46 }} />
            </Form.Item>
            <span style={{ fontSize: 11, color: 'var(--text-4)' }}>次/分</span>
          </div>
        </Tooltip>

        <Tooltip title="呼吸 次/分">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: 'var(--text-2)' }}>R</span>
            <Form.Item style={fieldStyle} name="respiration">
              <Input placeholder="18" style={{ ...inputStyle, width: 40 }} />
            </Form.Item>
            <span style={{ fontSize: 11, color: 'var(--text-4)' }}>次/分</span>
          </div>
        </Tooltip>

        <Tooltip title="血压 mmHg">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: 'var(--text-2)' }}>BP</span>
            <Form.Item style={fieldStyle} name="bp_systolic">
              <Input placeholder="120" style={{ ...inputStyle, width: 44 }} />
            </Form.Item>
            <span style={{ fontSize: 11, color: 'var(--text-4)' }}>/</span>
            <Form.Item style={fieldStyle} name="bp_diastolic">
              <Input placeholder="80" style={{ ...inputStyle, width: 40 }} />
            </Form.Item>
            <span style={{ fontSize: 11, color: 'var(--text-4)' }}>mmHg</span>
          </div>
        </Tooltip>

        <Tooltip title="血氧饱和度 %">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: 'var(--text-2)' }}>SpO₂</span>
            <Form.Item style={fieldStyle} name="spo2">
              <Input placeholder="98" style={{ ...inputStyle, width: 40 }} />
            </Form.Item>
            <span style={{ fontSize: 11, color: 'var(--text-4)' }}>%</span>
          </div>
        </Tooltip>
      </div>

      {/* Row 2: H W */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <Tooltip title="身高 cm">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: 'var(--text-2)' }}>身高</span>
            <Form.Item style={fieldStyle} name="height">
              <Input placeholder="170" style={{ ...inputStyle, width: 46 }} />
            </Form.Item>
            <span style={{ fontSize: 11, color: 'var(--text-4)' }}>cm</span>
          </div>
        </Tooltip>

        <Tooltip title="体重 kg">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: 'var(--text-2)' }}>体重</span>
            <Form.Item style={fieldStyle} name="weight">
              <Input placeholder="65" style={{ ...inputStyle, width: 46 }} />
            </Form.Item>
            <span style={{ fontSize: 11, color: 'var(--text-4)' }}>kg</span>
          </div>
        </Tooltip>
      </div>
    </div>
  )
}
