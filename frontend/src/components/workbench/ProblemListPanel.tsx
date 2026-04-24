/**
 * 问题列表面板（components/workbench/ProblemListPanel.tsx）
 *
 * 管理住院患者的活跃诊断和临床问题：
 *   - 快速新增问题/诊断
 *   - 标记为主要诊断或已解决
 *   - 颜色区分活跃/已解决状态
 */
import { useState, useEffect, useCallback } from 'react'
import { Button, Input, List, message, Popconfirm, Space, Tag, Tooltip, Typography } from 'antd'
import {
  CheckOutlined,
  DeleteOutlined,
  PlusOutlined,
  StarFilled,
  StarOutlined,
} from '@ant-design/icons'
import api from '@/services/api'
import { useWorkbenchStore } from '@/store/workbenchStore'

const { Text } = Typography

interface ProblemItem {
  id: string
  problem_name: string
  icd_code: string | null
  onset_date: string | null
  status: 'active' | 'resolved'
  is_primary: boolean
  added_by: string | null
  created_at: string | null
}

export default function ProblemListPanel() {
  const { currentEncounterId } = useWorkbenchStore()
  const [problems, setProblems] = useState<ProblemItem[]>([])
  const [newName, setNewName] = useState('')
  const [adding, setAdding] = useState(false)

  const fetchProblems = useCallback(async () => {
    if (!currentEncounterId) return
    try {
      const res = (await api.get(`/encounters/${currentEncounterId}/problems`)) as any
      setProblems(res.items || [])
    } catch {
      setProblems([])
    }
  }, [currentEncounterId])

  useEffect(() => {
    fetchProblems()
  }, [fetchProblems])

  const handleAdd = async () => {
    if (!newName.trim() || !currentEncounterId) return
    setAdding(true)
    try {
      await api.post(`/encounters/${currentEncounterId}/problems`, {
        problem_name: newName.trim(),
        // 第一条自动设为主要诊断
        is_primary: problems.length === 0,
      })
      setNewName('')
      fetchProblems()
    } catch {
      message.error('添加失败')
    } finally {
      setAdding(false)
    }
  }

  const togglePrimary = async (p: ProblemItem) => {
    if (!currentEncounterId) return
    try {
      await api.patch(`/encounters/${currentEncounterId}/problems/${p.id}`, {
        is_primary: !p.is_primary,
      })
      fetchProblems()
    } catch {
      message.error('更新失败')
    }
  }

  const toggleResolved = async (p: ProblemItem) => {
    if (!currentEncounterId) return
    try {
      await api.patch(`/encounters/${currentEncounterId}/problems/${p.id}`, {
        status: p.status === 'active' ? 'resolved' : 'active',
      })
      fetchProblems()
    } catch {
      message.error('更新失败')
    }
  }

  const handleDelete = async (p: ProblemItem) => {
    if (!currentEncounterId) return
    try {
      await api.delete(`/encounters/${currentEncounterId}/problems/${p.id}`)
      fetchProblems()
    } catch {
      message.error('删除失败')
    }
  }

  const active = problems.filter(p => p.status === 'active')
  const resolved = problems.filter(p => p.status === 'resolved')

  return (
    <div style={{ padding: '12px 14px' }}>
      <Text style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>
        问题列表 · {active.length} 个活跃
      </Text>

      {/* 快速新增 */}
      <Space.Compact style={{ width: '100%', marginTop: 10 }}>
        <Input
          placeholder="输入诊断/问题名称，回车确认"
          value={newName}
          onChange={e => setNewName(e.target.value)}
          onPressEnter={handleAdd}
          size="small"
        />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          size="small"
          loading={adding}
          onClick={handleAdd}
          style={{ background: '#059669', borderColor: '#059669' }}
        />
      </Space.Compact>

      {/* 活跃问题 */}
      {active.length > 0 && (
        <List
          dataSource={active}
          style={{ marginTop: 10 }}
          renderItem={p => (
            <List.Item
              style={{
                padding: '6px 0',
                borderBottom: '1px solid var(--border-subtle)',
                alignItems: 'flex-start',
              }}
              actions={[
                <Tooltip title={p.is_primary ? '取消主要诊断' : '设为主要诊断'} key="primary">
                  <Button
                    type="text"
                    size="small"
                    icon={
                      p.is_primary ? (
                        <StarFilled style={{ color: '#f59e0b' }} />
                      ) : (
                        <StarOutlined style={{ color: 'var(--text-4)' }} />
                      )
                    }
                    onClick={() => togglePrimary(p)}
                    style={{ padding: 2 }}
                  />
                </Tooltip>,
                <Tooltip title="标记为已解决" key="resolve">
                  <Button
                    type="text"
                    size="small"
                    icon={<CheckOutlined style={{ color: '#16a34a' }} />}
                    onClick={() => toggleResolved(p)}
                    style={{ padding: 2 }}
                  />
                </Tooltip>,
                <Popconfirm
                  title="确认删除此条问题？"
                  onConfirm={() => handleDelete(p)}
                  okText="删除"
                  cancelText="取消"
                  key="delete"
                >
                  <Button
                    type="text"
                    size="small"
                    icon={<DeleteOutlined style={{ color: 'var(--text-4)' }} />}
                    style={{ padding: 2 }}
                  />
                </Popconfirm>,
              ]}
            >
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  {p.is_primary && (
                    <Tag color="gold" style={{ margin: 0, fontSize: 10, padding: '0 4px' }}>
                      主
                    </Tag>
                  )}
                  <Text style={{ fontSize: 13, fontWeight: p.is_primary ? 700 : 500 }}>
                    {p.problem_name}
                  </Text>
                </div>
                {p.icd_code && (
                  <Text style={{ fontSize: 10, color: 'var(--text-4)' }}>ICD: {p.icd_code}</Text>
                )}
              </div>
            </List.Item>
          )}
        />
      )}

      {/* 已解决问题（折叠显示） */}
      {resolved.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <Text style={{ fontSize: 11, color: 'var(--text-4)' }}>已解决 ({resolved.length})</Text>
          {resolved.map(p => (
            <div
              key={p.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '4px 0',
              }}
            >
              <Text delete style={{ fontSize: 12, color: 'var(--text-4)' }}>
                {p.problem_name}
              </Text>
              <Button
                type="text"
                size="small"
                onClick={() => toggleResolved(p)}
                style={{ fontSize: 10, color: 'var(--text-4)', padding: '0 4px' }}
              >
                恢复
              </Button>
            </div>
          ))}
        </div>
      )}

      {problems.length === 0 && (
        <Text
          style={{
            fontSize: 12,
            color: 'var(--text-4)',
            display: 'block',
            marginTop: 16,
            textAlign: 'center',
          }}
        >
          尚未添加任何诊断/问题
        </Text>
      )}
    </div>
  )
}
