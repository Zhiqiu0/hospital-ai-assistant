/**
 * 病历评分卡（components/workbench/GradeScoreCard.tsx）
 *
 * 展示 LLM 对病历质量的综合评分，位于 QCIssuePanel 顶部。
 *
 * 评分维度说明（2026-04-30 引入"待整改"）：
 *   - 分数（grade_score）：连续值 0-100，反映病历质量
 *   - 等级（grade_level）：离散值 甲/乙/丙/待整改，反映"是否可签发"
 *   两者解耦：分数高不代表能签发——任何"必须修复项"（规则引擎产出）存在
 *   时等级强制为"待整改"，文案展示"N 项必须修复"。
 *
 * 显示规则：
 *   - 待整改：红橙渐变 + 🛠️ 图标，文案强调待修项数
 *   - 甲级：绿色 + 🏆     乙级：黄色 + ⚡     丙级：红色 + ⚠️
 *   - gradeScore 为 null 时不渲染（QCIssuePanel 控制）
 */
import { Typography } from 'antd'
import { GradeScore } from '@/store/types'

const { Text } = Typography

const GRADE_CONFIG: Record<
  string,
  { color: string; bg: string; border: string; label: string; icon: string }
> = {
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
  // 待整改：分数与等级解耦后的"不可签发"等级
  // 选橙红色而非纯红：跟丙级（深红）拉开层次——丙级=分数严重不足，
  // 待整改=分数可能高但有合规硬伤，前者比后者更糟，色调上保留区分度
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
  const cfg = GRADE_CONFIG[gradeScore.grade_level] || GRADE_CONFIG['乙级']
  const score = gradeScore.grade_score
  const isPending = gradeScore.grade_level === '待整改'
  const radius = 26
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (score / 100) * circumference
  // 环形描边色：待整改优先用配置橙色（即使分数高也别绿，避免视觉冲突）
  const ringStroke = isPending
    ? '#f97316'
    : score >= 90
      ? '#22c55e'
      : score >= 75
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
            {isPending
              ? `（${gradeScore.must_fix_count ?? 0} 项必须修复）`
              : score >= 90
                ? '（达到甲级标准）'
                : score >= 75
                  ? `（距甲级还差 ${90 - score} 分）`
                  : `（距乙级还差 ${75 - score} 分）`}
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
