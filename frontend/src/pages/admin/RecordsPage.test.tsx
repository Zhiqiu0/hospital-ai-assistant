/** 病历搜索必须发到服务端，并防止较早请求覆盖新搜索结果。 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import type { InputHTMLAttributes, PropsWithChildren } from 'react'

type SearchResult = { items: { id: string; patient_name: string }[]; total: number }
type TableProps = {
  dataSource: SearchResult['items']
  pagination: { current: number; onChange: (page: number) => void }
}

vi.mock('@/services/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/components/workbench/RecordViewModal', () => ({ default: () => null }))
// 只简化展示组件，搜索、分页和请求竞态均执行真实页面逻辑。
vi.mock('antd', () => {
  const Input = Object.assign(
    ({ value, onChange, placeholder }: InputHTMLAttributes<HTMLInputElement>) => (
      <input value={value} onChange={onChange} placeholder={placeholder} />
    ),
    { TextArea: () => null }
  )
  return {
    Input,
    Table: ({ dataSource, pagination }: TableProps) => (
      <div>
        <span data-testid="rows">{dataSource.map(r => r.patient_name).join(',')}</span>
        <span data-testid="page">{pagination.current}</span>
        <button onClick={() => pagination.onChange(2)}>第二页</button>
      </div>
    ),
    Typography: {
      Title: ({ children }: PropsWithChildren) => <div>{children}</div>,
      Text: ({ children }: PropsWithChildren) => <span>{children}</span>,
    },
    Modal: () => null,
    Tag: () => null,
    Button: () => null,
    Space: () => null,
  }
})

import api from '@/services/api'
import RecordsPage from './RecordsPage'

beforeEach(() => vi.resetAllMocks())

it('跨页搜索发送中文搜索词并回到第一页，清空后重新加载全部', async () => {
  vi.mocked(api.get).mockResolvedValue({ items: [], total: 24 })
  render(<RecordsPage />)
  fireEvent.click(screen.getByText('第二页'))
  await waitFor(() => expect(screen.getByTestId('page')).toHaveTextContent('2'))
  fireEvent.change(screen.getByPlaceholderText('搜索患者姓名或医生'), {
    target: { value: ' 张三 ' },
  })
  await waitFor(() => {
    const [url] = vi.mocked(api.get).mock.lastCall!
    const params = new URLSearchParams(String(url).split('?')[1])
    expect(params.get('search')).toBe('张三')
    expect(params.get('page')).toBe('1')
  })
  expect(screen.getByTestId('page')).toHaveTextContent('1')
  fireEvent.change(screen.getByPlaceholderText('搜索患者姓名或医生'), { target: { value: '' } })
  await waitFor(() => {
    const [url] = vi.mocked(api.get).mock.lastCall!
    const params = new URLSearchParams(String(url).split('?')[1])
    expect(params.get('search') || '').toBe('')
  })
})

it('旧搜索晚返回不能覆盖新结果', async () => {
  let resolveOld!: (value: SearchResult) => void
  vi.mocked(api.get)
    .mockImplementationOnce(
      () =>
        new Promise(resolve => {
          resolveOld = resolve
        })
    )
    .mockResolvedValue({ items: [{ id: 'new', patient_name: '新患者' }], total: 1 })
  render(<RecordsPage />)
  fireEvent.change(screen.getByPlaceholderText('搜索患者姓名或医生'), { target: { value: '新' } })
  await waitFor(() => expect(screen.getByTestId('rows')).toHaveTextContent('新患者'))
  await act(async () => resolveOld({ items: [{ id: 'old', patient_name: '旧患者' }], total: 24 }))
  expect(screen.getByTestId('rows')).toHaveTextContent('新患者')
  expect(screen.getByTestId('rows')).not.toHaveTextContent('旧患者')
})
