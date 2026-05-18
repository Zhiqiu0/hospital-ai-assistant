/**
 * 病历评分卡（components/workbench/GradeScoreCard.tsx）
 *
 * 展示病历质控评分，位于 QCIssuePanel 顶部。
 *
 * L3 治本路线（2026-05-18）：
 *   等级体系按浙江省卫健委 PDF 标准：
 *     - 门、急诊（PDF 注 5）：合格（≥90） / 不合格（<90）
 *     - 住院（PDF 备注 8）：甲级（≥90） / 乙级（≥80） / 丙级（<80）
 *   兼容旧返回的"甲/乙/丙/待整改"（住院 Rubric 上线前）。
 *
 * 显示规则：
 *   - 合格 / 甲级：绿色 + 🏆
 *   - 不合格 / 待整改：橙红 + ⚠️ ，文案强调待修项数
 *   - 乙级：黄色 + ⚡   - 丙级：红色 + ⚠️
 *   - gradeScore 为 null 时不渲染（QCIssuePanel 控制）
 */
import { Typography } from 'antd'
import { GradeScore } from '@/store/types'

const { Text } = Typography

interface GradeStyle {
  color: string
  bg: string
  border: string
  label: string
  icon: string
}

const GRADE_CONFIG: Record<string, GradeStyle> = {
  // 门诊新标准
  合格: {
    color: '#065f46',
    bg: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
    border: '#86efac',
    label: '合格病历',
    icon: '🏆',
  },
  不合格: {
    color: '#7c2d12',
    bg: 'linear-gradient(135deg, #fff7ed, #ffedd5)',
    border: '#f97316',
    label: '不合格',
    icon: '⚠️',
  },
  // 住院旧标准（兼容；下一期住院 Rubric 接入后保持）
  甲级: {
    color: '#065f46',
    bg: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
    border: '#86efac',
    label: '甲级病历',
    icon: '🏆',
  },
  乙级: {
    color: '#92400e',
    bg: 'linear-gradient(135deg, #fffbeb, #fef3c7)',
    border: '#fcd34d',
    label: '乙级病历',
    icon: '⚡',
  },
  丙级: {
    color: '#991b1b',
    bg: 'linear-gradient(135deg, #fff1f2, #ffe4e6)',
    border: '#fca5a5',
    label: '丙级病历',
    icon: '⚠️',
  },
  // 待整改：分数与等级解耦的"不可签发"等级（住院 + 旧门诊兼容）
  待整改: {
    color: '#7c2d12',
    bg: 'linear-gradient(135deg, #fff7ed, #ffedd5)',
    border: '#f97316',
    label: '待整改',
    icon: '🛠️',
  },
}

interface GradeScoreCardProps {
  gradeScore: GradeScore
}

export default function GradeScoreCard({ gradeScore }: GradeScoreCardProps) {
  const cfg = GRADE_CONFIG[gradeScore.grade_level] || GRADE_CONFIG['不合格']
  const score = gradeScore.grade_score
  // 不合格 / 待整改 / 丙级 都是"非通过"状态，环形颜色统一用橙红
  const isFailing =
    gradeScore.grade_level === '不合格' ||
    gradeScore.grade_level === '待整改' ||
    gradeScore.grade_level === '丙级'
  const radius = 26
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (score / 100) * circumference
  // 环形描边色：按"是否合格"分流，比硬阈值判断更稳健
  const ringStroke = isFailing
    ? '#f97316'
    : score >= 90
      ? '#22c55e'
      : score >= 80
        ? '#f59e0b'
        : '#ef4444'

  return (
    <div
      style={{
        background: cfg.bg,
        border: `1px solid ${cfg.border}`,
        borderRadius: 12,
        padding: '12px 14px',
        marginBottom: 10,
        display: 'flex',
        alignItems: 'center',
        gap: 14,
      }}
    >
      {/* 环形分数 */}
      <div style={{ position: 'relative', width: 64, height: 64, flexShrink: 0 }}>
        <svg width={64} height={64} viewBox="0 0 64 64">
          <circle cx={32} cy={32} r={radius} fill="none" stroke="#e2e8f0" strokeWidth={6} />
          <circle
            cx={32}
            cy={32}
            r={radius}
            fill="none"
            stroke={ringStroke}
            strokeWidth={6}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            transform="rotate(-90 32 32)"
            style={{ transition: 'stroke-dashoffset 0.6s ease' }}
          />
        </svg>
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text strong style={{ fontSize: 16, lineHeight: 1, color: cfg.color }}>
            {score}
          </Text>
          <Text style={{ fontSize: 9, color: cfg.color, opacity: 0.8 }}>分</Text>
        </div>
      </div>

      {/* 等级信息 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <Text style={{ fontSize: 11 }}>{cfg.icon}</Text>
          <Text strong style={{ fontSize: 14, color: cfg.color }}>
            {cfg.label}
          </Text>
          <Text style={{ fontSize: 11, color: 'var(--text-4)' }}>
            {isFailing
              ? gradeScore.must_fix_count && gradeScore.must_fix_count > 0
                ? `（${gradeScore.must_fix_count} 项必须修复）`
                : `（距合格还差 ${Math.max(0, 90 - score)} 分）`
              : score >= 90
                ? '（达到合格标准）'
                : `（距合格还差 ${90 - score} 分）`}
          </Text>
        </div>
        {gradeScore.strengths && gradeScore.strengths.length > 0 && (
          <div style={{ fontSize: 11, color: '#374151', lineHeight: 1.5 }}>
            {gradeScore.strengths.slice(0, 2).map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 4 }}>
                <Text style={{ color: '#22c55e', flexShrink: 0 }}>✓</Text>
                <Text style={{ fontSize: 11, color: '#374151' }}>{s}</Text>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
