/**
 * 生命体征全角归一化测试（2026-09-10 编码边界审计前端侧）
 *
 * 抓的问题：医生中文输入法全角态敲的 ３６．５ 原样进表单值——保存时后端
 * 会归一落库，但 AI 生成/质控请求带的是表单原值，全角串直接进 prompt 与
 * 病历正文（实测生成出 "T:[未测]"）。Form.Item normalize 在源头归一。
 */
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Form } from 'antd'
import VitalSignsInput from './VitalSignsInput'

function Host({ onForm }: { onForm: (f: ReturnType<typeof Form.useForm>[0]) => void }) {
  const [form] = Form.useForm()
  onForm(form)
  return (
    <Form form={form}>
      <VitalSignsInput />
    </Form>
  )
}

describe('VitalSignsInput 全角归一化', () => {
  it('全角 ３６．８ 键入后表单值为半角 36.8', () => {
    let form: ReturnType<typeof Form.useForm>[0]
    render(<Host onForm={f => (form = f)} />)
    const t = screen.getByPlaceholderText('36.5')
    fireEvent.change(t, { target: { value: '３６．８' } })
    expect(form!.getFieldValue('temperature')).toBe('36.8')
  })

  it('半角输入原样保留', () => {
    let form: ReturnType<typeof Form.useForm>[0]
    render(<Host onForm={f => (form = f)} />)
    fireEvent.change(screen.getByPlaceholderText('120'), { target: { value: '135' } })
    expect(form!.getFieldValue('bp_systolic')).toBe('135')
  })

  it('八个体征框全部挂了归一化（防漏挂回归）', () => {
    let form: ReturnType<typeof Form.useForm>[0]
    render(<Host onForm={f => (form = f)} />)
    const cases: Array<[string, string]> = [
      ['36.5', 'temperature'],
      ['72', 'pulse'],
      ['18', 'respiration'],
      ['120', 'bp_systolic'],
      ['80', 'bp_diastolic'],
      ['98', 'spo2'],
      ['170', 'height'],
      ['65', 'weight'],
    ]
    for (const [ph, field] of cases) {
      fireEvent.change(screen.getByPlaceholderText(ph), { target: { value: '１２' } })
      expect(form!.getFieldValue(field), field).toBe('12')
    }
  })
})
