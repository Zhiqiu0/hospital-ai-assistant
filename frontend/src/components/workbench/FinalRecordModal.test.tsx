/**
 * 签发弹窗的规则覆盖披露测试（2026-09-10 第 19 轮回归猎手）
 *
 * 抓的问题：QC 面板与 toast 已做零规则披露，但签发弹窗仍显示
 * "病历质控通过，可以签发"——医生在签发这一刻（最要紧的时刻）
 * 又拿到虚假背书。三个出口必须同口径。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import FinalRecordModal from './FinalRecordModal'
import { useQCStore } from '@/store/qcStore'
import { useRecordStore } from '@/store/recordStore'

beforeEach(() => {
  useQCStore.setState({ qcPass: true, qcIssues: [] })
  useRecordStore.setState({ recordContent: '患者今日无特殊。', recordType: 'course_record' })
})

describe('FinalRecordModal 规则覆盖披露', () => {
  it('零规则类型：显示"暂未覆盖"警示，不显示"质控通过，可以签发"', () => {
    useQCStore.setState({
      gradeScore: { grade_score: 100, grade_level: '甲级', rules_covered: false },
    })
    render(<FinalRecordModal open onCancel={() => {}} />)
    expect(screen.getAllByText(/暂未覆盖/).length).toBeGreaterThan(0)
    expect(screen.queryByText('病历质控通过，可以签发')).toBeNull()
  })

  it('有规则类型：正常显示质控通过（不能把真通过也拦了）', () => {
    useQCStore.setState({
      gradeScore: { grade_score: 95, grade_level: '甲级', rules_covered: true },
    })
    render(<FinalRecordModal open onCancel={() => {}} />)
    expect(screen.getByText('病历质控通过，可以签发')).toBeTruthy()
  })
})
