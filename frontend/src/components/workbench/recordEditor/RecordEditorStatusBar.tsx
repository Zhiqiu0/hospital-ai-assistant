/**
 * 病历编辑器状态条（components/workbench/recordEditor/RecordEditorStatusBar.tsx）
 *
 * 三态视觉切换（互斥）：
 *   - busy : AI 正在生成 / 润色 / 质控 / 补全 → 蓝色进度条 + spinner + busyText
 *   - final: 病历已签发 → 绿色"不可修改"提示 + 打印按钮
 *   - draft: 普通编辑态 → 灰色文案"AI 生成内容仅供参考"
 *
 * 从 RecordEditor.tsx 拆出（Audit Round 4 M6），独立组件让三态分支表达更清晰。
 */
import { Button, Space, Spin } from 'antd'
import { CheckOutlined, PrinterOutlined } from '@ant-design/icons'
import { printRecord } from '@/utils/recordExport'
import type { Patient } from '@/domain/medical'
import { useAuthStore } from '@/store/authStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'

interface RecordEditorStatusBarProps {
  isBusy: boolean
  busyText: string
  isFinal: boolean
  finalizedAt: string | null
  recordContent: string
  recordType: string
  currentPatient: Patient | null
}

export default function RecordEditorStatusBar(props: RecordEditorStatusBarProps) {
  const { isBusy, busyText, isFinal, finalizedAt, recordContent, recordType, currentPatient } =
    props
  // 病案首页所需的医生 + 科室 + 就诊类型上下文。
  // 编辑器场景下没有 snapshot（snapshot 是签发瞬间冻结的，编辑器读不到），
  // 所以用 ctx 兜底——这是当前正在签发的接诊，doctor/dept/visit_type 都准确。
  const user = useAuthStore(s => s.user)
  const visitType = useActiveEncounterStore(s => s.visitType)
  const ctx = {
    visit_type: visitType,
    visit_time: finalizedAt,
    doctor_name: user?.real_name,
    department_name: user?.department_name,
  }

  if (isBusy) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '7px 16px',
          flexShrink: 0,
          background: 'linear-gradient(90deg, #eff6ff, #f0f9ff)',
          borderBottom: '1px solid #bfdbfe',
          color: '#1d4ed8',
          fontSize: 12,
          fontWeight: 500,
        }}
      >
        <Spin size="small" />
        <span>{busyText}</span>
      </div>
    )
  }

  if (isFinal) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '6px 16px',
          flexShrink: 0,
          background: '#f0fdf4',
          borderBottom: '1px solid #bbf7d0',
        }}
      >
        <Space size={6}>
          <CheckOutlined style={{ fontSize: 12, color: '#065f46' }} />
          <span style={{ color: '#065f46', fontSize: 12, fontWeight: 500 }}>
            病历已签发，不可修改
          </span>
        </Space>
        <Button
          size="small"
          icon={<PrinterOutlined />}
          onClick={() =>
            printRecord(recordContent, currentPatient, recordType, finalizedAt, null, ctx)
          }
          style={{
            borderRadius: 6,
            fontSize: 12,
            height: 26,
            color: '#065f46',
            borderColor: '#86efac',
            background: 'var(--surface)',
          }}
        >
          打印
        </Button>
      </div>
    )
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        padding: '3px 14px',
        flexShrink: 0,
        borderBottom: '1px solid var(--border-subtle)',
        color: '#b0bec5',
        fontSize: 11,
      }}
    >
      <span>AI 生成内容仅供参考，请医生审核后使用</span>
    </div>
  )
}
