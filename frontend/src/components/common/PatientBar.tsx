/**
 * 当前患者信息条（components/common/PatientBar.tsx）
 *
 * 工作台顶栏中央展示当前接诊患者，样式已统一从 tokens 读取。
 * 空状态（未选患者）显示提示文字。
 */
import { Typography } from 'antd'
import { semantic, neutral, radius } from '@/theme/tokens'

const { Text } = Typography

interface PatientBarProps {
  patient: {
    name: string
    gender?: string
    age?: number | null
  } | null
  encounterId?: string | null
}

export default function PatientBar({ patient, encounterId }: PatientBarProps) {
  if (!patient) {
    return <Text style={{ fontSize: 13, color: neutral.text4 }}>未选择患者</Text>
  }

  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        background: semantic.successLight,
        border: `1px solid ${semantic.successBorder}`,
        borderRadius: radius.md,
        padding: '4px 12px',
        boxShadow: '0 1px 4px rgba(34,197,94,0.08)',
        lineHeight: 1,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: semantic.success,
          boxShadow: `0 0 0 2px rgba(34,197,94,0.25)`,
          flexShrink: 0,
        }}
      />
      <Text style={{ fontSize: 13, fontWeight: 700, color: '#065f46' }}>{patient.name}</Text>
      {patient.gender && patient.gender !== 'unknown' && (
        <Text style={{ fontSize: 12, color: '#059669' }}>
          {patient.gender === 'male' ? '男' : '女'}
        </Text>
      )}
      {patient.age != null && patient.age > 0 && (
        <Text style={{ fontSize: 12, color: '#059669' }}>{patient.age}岁</Text>
      )}
      {encounterId && (
        <Text
          style={{ fontSize: 11, color: neutral.text4, fontFamily: 'monospace', marginLeft: 4 }}
        >
          #{encounterId.slice(-6).toUpperCase()}
        </Text>
      )}
    </div>
  )
}
