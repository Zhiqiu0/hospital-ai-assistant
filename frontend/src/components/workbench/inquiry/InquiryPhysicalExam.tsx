/**
 * 体格检查折叠区块（components/workbench/inquiry/InquiryPhysicalExam.tsx）
 *
 * 内容：
 *   - 生命体征（急诊场景红色高亮，门诊普通展示）
 *   - 一般体检 textarea
 *   - 中医四诊（TcmSection 子组件）
 *
 * 辅助检查不在此面板：2026-05-03 重构后改为通过右侧 AI 检查建议（写入/已写入）
 * 直接管理病历【辅助检查】章节；inquiry.auxiliary_exam DB 字段保留作为 AI 选中项
 * 的结构化记录。详见 ExamSuggestionTab。
 */
import { Form, Input } from 'antd'
import { HeartOutlined, AlertOutlined } from '@ant-design/icons'
import VitalSignsInput from '../VitalSignsInput'
import TcmSection from '../TcmSection'
import CollapsibleSection from '@/components/common/CollapsibleSection'

// 一般体检仍保留 TextArea 输入；辅助检查 textarea 已删除（数据流改由 ExamSuggestionTab 管）

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
      {/* 辅助检查字段已迁出此面板，由右侧「检查建议」Tab 通过"写入/已写入"按钮
          直接管理病历【辅助检查】章节，避免一字段多源（手输 + AI 建议 + OCR + 影像）冲突 */}
    </CollapsibleSection>
  )
}
