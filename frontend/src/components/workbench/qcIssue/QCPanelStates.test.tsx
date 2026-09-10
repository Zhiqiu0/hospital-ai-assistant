/**
 * 质控通过态视图的规则覆盖披露测试（2026-09-10 收敛轮审计）
 *
 * 抓的问题：日常病程/上级查房零规则 → 评分恒 100，QCPassedView 显示
 * "质控通过 + 🏆 甲级病历"给医生虚假背书。零覆盖时必须换披露态。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QCPassedView } from './QCPanelStates'
import type { GradeScore } from '@/store/types'

const uncovered: GradeScore = {
  grade_score: 100,
  grade_level: '甲级',
  rules_covered: false,
}

const covered: GradeScore = {
  grade_score: 95,
  grade_level: '甲级',
  rules_covered: true,
}

describe('QCPassedView 规则覆盖披露', () => {
  it('零规则类型：显示"暂未覆盖"披露，不显示"质控通过"与评分卡', () => {
    render(
      <QCPassedView
        gradeScore={uncovered}
        qcSummary="该文书类型的结构化质控规则暂未覆盖，评分仅供参考"
      />
    )
    // 标题与描述都带披露词属预期，用 getAllByText
    expect(screen.getAllByText(/暂未覆盖/).length).toBeGreaterThan(0)
    expect(screen.queryByText('质控通过')).toBeNull()
    // 🏆 评分卡（"甲级病历"标签）不得出现
    expect(screen.queryByText('甲级病历')).toBeNull()
  })

  it('有规则类型：正常显示质控通过与评分卡（不能因披露把真通过也拦了）', () => {
    render(<QCPassedView gradeScore={covered} qcSummary="质控通过（95 分 甲级）" />)
    expect(screen.getByText('质控通过')).toBeTruthy()
    expect(screen.getByText('甲级病历')).toBeTruthy()
  })

  it('旧后端无 rules_covered 字段：按已覆盖处理（向后兼容）', () => {
    render(
      <QCPassedView gradeScore={{ grade_score: 92, grade_level: '合格' }} qcSummary="质控通过" />
    )
    expect(screen.getAllByText('质控通过').length).toBeGreaterThan(0)
  })
})
