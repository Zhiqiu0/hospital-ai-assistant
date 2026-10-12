/** 签发与管理员修订必须核对最终正文诊断；预览失效后不得沿用旧确认。 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
vi.mock('@/services/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/services/messageBridge', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))
vi.mock('./RecordViewModal', () => ({ default: () => null }))
import api from '@/services/api'
import FinalRecordModal from './FinalRecordModal'
import RecordsPage from '@/pages/admin/RecordsPage'
import { useRecordStore } from '@/store/recordStore'
import { useQCStore } from '@/store/qcStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'

const preview = {
  diagnoses: [
    { name: '最终诊断甲', category: 'western', is_primary: true, code: 'A01', code_type: 'ICD-10' },
    { name: '最终诊断乙', category: 'western', is_primary: false, code: null, code_type: null },
  ],
  requires_confirmation: true,
  projection_error: null,
  his_writeback_required: true,
}
beforeEach(() => {
  vi.resetAllMocks()
  useRecordStore.getState().reset()
  useRecordStore.setState({
    recordContent: '【诊断】最终诊断甲、最终诊断乙',
    recordType: 'outpatient',
  })
  useActiveEncounterStore.setState({ encounterId: 'confirm-e' })
  useQCStore.setState({ qcPass: true, qcIssues: [], gradeScore: null })
  vi.mocked(api.post).mockImplementation(async url =>
    String(url).endsWith('diagnosis-preview') ? preview : { submitted_at: '2026-10-12' }
  )
})
it('签发需明确核对诊断与主诊断，提交不携带旧编码', async () => {
  render(<FinalRecordModal open onCancel={vi.fn()} />)
  await screen.findByRole('radio', { name: /最终诊断乙/ })
  fireEvent.click(screen.getByRole('checkbox', { name: /认真阅读/ }))
  expect(screen.getByRole('button', { name: /确认签发/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('radio', { name: /最终诊断乙/ }))
  fireEvent.click(screen.getByRole('checkbox', { name: /已核对以上诊断/ }))
  fireEvent.click(screen.getByRole('button', { name: /确认签发/ }))
  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith(
      '/medical-records/quick-save',
      expect.objectContaining({
        confirmed_diagnoses: [
          { name: '最终诊断甲', category: 'western', is_primary: false },
          { name: '最终诊断乙', category: 'western', is_primary: true },
        ],
      })
    )
  )
})
it('正文变化立即作废诊断确认，旧预览响应不能恢复确认', async () => {
  render(<FinalRecordModal open onCancel={vi.fn()} />)
  await screen.findByRole('radio', { name: /最终诊断甲/ })
  fireEvent.click(screen.getByRole('checkbox', { name: /已核对以上诊断/ }))
  fireEvent.click(screen.getByRole('checkbox', { name: /认真阅读/ }))
  let finish!: (value: unknown) => void
  vi.mocked(api.post).mockImplementationOnce(
    () =>
      new Promise(resolve => {
        finish = resolve
      })
  )
  act(() => useRecordStore.getState().setRecordContent('修改后的诊断'))
  expect(screen.getByRole('button', { name: /确认签发/ })).toBeDisabled()
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  await act(async () => finish(preview))
  expect(screen.getByRole('checkbox', { name: /已核对以上诊断/ })).not.toBeChecked()
})
it('管理员修订保留理由并核对最终诊断后提交', async () => {
  vi.mocked(api.get).mockResolvedValue({
    items: [
      {
        id: 'revise-r',
        patient_name: '合成患者',
        record_type: 'outpatient',
        content: '【诊断】最终诊断甲、最终诊断乙',
      },
    ],
    total: 1,
  })
  render(<RecordsPage />)
  fireEvent.click(await screen.findByRole('button', { name: /修订/ }))
  await screen.findByRole('radio', { name: /最终诊断乙/ })
  fireEvent.change(screen.getByPlaceholderText(/请说明本次修订原因/), {
    target: { value: '更正最终诊断' },
  })
  expect(screen.getByRole('button', { name: /确认修订并留痕/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('radio', { name: /最终诊断乙/ }))
  fireEvent.click(screen.getByRole('checkbox', { name: /已核对以上诊断/ }))
  fireEvent.click(screen.getByRole('button', { name: /确认修订并留痕/ }))
  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith(
      '/admin/records/revise-r/revise',
      expect.objectContaining({
        revise_reason: '更正最终诊断',
        confirmed_diagnoses: expect.arrayContaining([
          { name: '最终诊断乙', category: 'western', is_primary: true },
        ]),
      })
    )
  )
})

it('文书读取未完成时即使完成全部确认也不能签发，双击只提交一次', async () => {
  useRecordStore.setState({ recordLoading: true })
  render(<FinalRecordModal open onCancel={vi.fn()} />)
  await screen.findByRole('radio', { name: /最终诊断甲/ })
  fireEvent.click(screen.getByRole('checkbox', { name: /已核对以上诊断/ }))
  fireEvent.click(screen.getByRole('checkbox', { name: /认真阅读/ }))
  const button = screen.getByRole('button', { name: /确认签发/ })
  expect(button).toBeDisabled()
  act(() => useRecordStore.setState({ recordLoading: false }))
  // 保持签发请求在途，重复点击也只能发送一次。
  vi.mocked(api.post).mockImplementationOnce(() => new Promise(() => {}))
  fireEvent.click(button)
  fireEvent.click(button)
  expect(
    vi.mocked(api.post).mock.calls.filter(([url]) => url === '/medical-records/quick-save')
  ).toHaveLength(1)
})
