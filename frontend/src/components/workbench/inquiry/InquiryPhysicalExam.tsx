/**
 * 体格检查折叠区块（components/workbench/inquiry/InquiryPhysicalExam.tsx）
 *
 * 内容：
 *   - 生命体征（急诊场景红色高亮，门诊普通展示）
 *   - 一般体检 textarea
 *   - 中医四诊（TcmSection 子组件）
 *   - 辅助检查 textarea（必填）
 */
import { Form, Input } from 'antd'
import { HeartOutlined, AlertOutlined } from '@ant-design/icons'
import VitalSignsInput from '../VitalSignsInput'
import TcmSection from '../TcmSection'
import CollapsibleSection from '@/components/common/CollapsibleSection'

const { TextArea } = Input

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-2)',
  marginBottom: 4,
  display: 'block',
}

const fs: React.CSSProperties = { marginBottom: 10 }

interface InquiryPhysicalExamProps {
  isEmergency: boolean
}

export default function InquiryPhysicalExam({ isEmergency }: InquiryPhysicalExamProps) {
  return (
    <CollapsibleSection title="体格检查" icon={<HeartOutlined />} accent="#0284c7" defaultOpen>
      {isEmergency ? (
        <div
          style={{
            background: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: 8,
            padding: '8px 10px',
            marginBottom: 10,
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: '#dc2626',
              fontWeight: 600,
              marginBottom: 6,
              display: 'flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            <AlertOutlined /> 急诊生命体征（必填）
          </div>
          <VitalSignsInput />
        </div>
      ) : (
        <VitalSignsInput />
      )}

      <Form.Item style={fs} name="physical_exam" label={<span style={labelStyle}>一般体检</span>}>
        <TextArea
          rows={3}
          placeholder="各系统体检结果、阳性体征、必要阴性体征"
          style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
        />
      </Form.Item>

      {/* 中医四诊 */}
      <TcmSection />

      <Form.Item
        style={fs}
        name="auxiliary_exam"
        rules={[{ required: true, message: '请填写辅助检查，无检查项目请填写「暂无」' }]}
        label={
          <span style={labelStyle}>
            辅助检查 <span style={{ color: '#ef4444' }}>*</span>
          </span>
        }
      >
        <TextArea
          rows={3}
          placeholder="已有检查结果原样填入；如无检查请填写「暂无」"
          style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
        />
      </Form.Item>
    </CollapsibleSection>
  )
}
