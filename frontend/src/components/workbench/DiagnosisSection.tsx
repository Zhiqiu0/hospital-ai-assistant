/**
 * 诊断区块（DiagnosisSection.tsx）
 * 中医疾病诊断、中医证候诊断（各至多一条，文本输入）+ 西医诊断条目编辑器
 * （2026-08-21 阶段1b 结构化：可多条、主诊断显式勾选）+ 初步印象。
 * 必须渲染在 Ant Design Form 上下文内。
 */
import { Form, Input } from 'antd'
import { BulbOutlined } from '@ant-design/icons'
import WesternDiagnosisEditor from './inquiry/WesternDiagnosisEditor'
import { FormDiagnosisNameInput } from './inquiry/DiagnosisCodeInput'

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-2)',
  marginBottom: 4,
  display: 'block',
}

const sectionHeaderStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: 'var(--text-3)',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  padding: '6px 0 4px',
}

const fs: React.CSSProperties = { marginBottom: 10 }

export default function DiagnosisSection({ locked = false }: { locked?: boolean }) {
  return (
    <>
      <div style={{ ...sectionHeaderStyle, display: 'flex', alignItems: 'center', gap: 6 }}>
        <BulbOutlined style={{ color: '#7c3aed' }} />
        <span>诊断</span>
      </div>

      <div
        style={{
          background: '#faf5ff',
          border: '1px solid #e9d5ff',
          borderRadius: 8,
          padding: '10px 10px 4px',
          marginBottom: 10,
        }}
      >
        <Form.Item
          style={fs}
          name="tcm_disease_diagnosis"
          label={<span style={{ ...labelStyle, color: '#7c3aed' }}>中医疾病诊断</span>}
        >
          <FormDiagnosisNameInput
            codeType="TCD_DIS"
            placeholder="如：眩晕病、胸痹、感冒（可输拼音首字母联想）"
            style={{ borderRadius: 6, fontSize: 13 }}
          />
        </Form.Item>

        <Form.Item
          style={fs}
          name="tcm_syndrome_diagnosis"
          label={<span style={{ ...labelStyle, color: '#7c3aed' }}>中医证候诊断</span>}
        >
          <FormDiagnosisNameInput
            codeType="TCD_SYN"
            placeholder="如：肝阳上亢证、痰热壅肺证（可输拼音首字母联想）"
            style={{ borderRadius: 6, fontSize: 13 }}
          />
        </Form.Item>

        {/* 西医诊断：条目编辑器（结构化权威，2026-08-21 阶段1b）。
            旧 western_diagnosis 文本字段仍在 store/表单值里（投影），但不再
            直接编辑——保存时由条目合成投影回填 */}
        <div style={{ marginBottom: 4 }}>
          <span style={labelStyle}>西医诊断</span>
          <WesternDiagnosisEditor disabled={locked} />
        </div>
      </div>

      <Form.Item
        style={fs}
        name="initial_impression"
        label={<span style={labelStyle}>初步印象（补充）</span>}
      >
        <Input
          placeholder="暂时无法明确时的印象或鉴别方向"
          style={{ borderRadius: 6, fontSize: 13 }}
        />
      </Form.Item>
    </>
  )
}
