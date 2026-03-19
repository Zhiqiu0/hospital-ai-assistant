import { useEffect, useState, useCallback } from 'react'
import {
  Table, Input, Space, Tag, Typography, Select, Button
} from 'antd'
import { SearchOutlined, AuditOutlined } from '@ant-design/icons'
import api from '@/services/api'

const { Title, Text } = Typography

const ACTION_LABELS: Record<string, { label: string; color: string }> = {
  login: { label: '登录', color: 'blue' },
  sign_record: { label: '签发病历', color: 'green' },
  create_user: { label: '创建用户', color: 'purple' },
  update_user: { label: '修改用户', color: 'orange' },
  delete_user: { label: '删除用户', color: 'red' },
  update_patient: { label: '修改患者', color: 'cyan' },
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  ok: { label: '成功', color: 'success' },
  error: { label: '失败', color: 'error' },
}

export default function AuditLogsPage() {
  const [logs, setLogs] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [loading, setLoading] = useState(false)

  const loadLogs = useCallback(async (p = page, kw = keyword, act = actionFilter) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: String(p),
        page_size: '20',
        keyword: kw,
        action: act,
      })
      const data: any = await api.get(`/admin/audit-logs?${params}`)
      setLogs(data.items || [])
      setTotal(data.total || 0)
    } finally {
      setLoading(false)
    }
  }, [page, keyword, actionFilter])

  useEffect(() => { loadLogs() }, [])

  const handleSearch = () => {
    setPage(1)
    loadLogs(1, keyword, actionFilter)
  }

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '—',
    },
    {
      title: '操作人',
      dataIndex: 'user_name',
      key: 'user_name',
      width: 120,
      render: (name: string, row: any) => (
        <div>
          <Text strong style={{ fontSize: 13 }}>{name || '—'}</Text>
          {row.user_role && (
            <div style={{ fontSize: 11, color: '#94a3b8' }}>{row.user_role}</div>
          )}
        </div>
      ),
    },
    {
      title: '操作',
      dataIndex: 'action',
      key: 'action',
      width: 120,
      render: (action: string) => {
        const info = ACTION_LABELS[action] || { label: action, color: 'default' }
        return <Tag color={info.color} style={{ borderRadius: 20 }}>{info.label}</Tag>
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (status: string) => {
        const info = STATUS_MAP[status] || { label: status, color: 'default' }
        return <Tag color={info.color} style={{ borderRadius: 20 }}>{info.label}</Tag>
      },
    },
    {
      title: '资源',
      key: 'resource',
      width: 140,
      render: (_: any, row: any) => row.resource_type ? (
        <div>
          <Text style={{ fontSize: 12, color: '#64748b' }}>{row.resource_type}</Text>
          {row.resource_id && (
            <div style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace' }}>
              {row.resource_id.slice(-8).toUpperCase()}
            </div>
          )}
        </div>
      ) : '—',
    },
    {
      title: '详情',
      dataIndex: 'detail',
      key: 'detail',
      render: (v: string) => (
        <Text style={{ fontSize: 12, color: '#475569' }}>{v || '—'}</Text>
      ),
    },
    {
      title: 'IP',
      dataIndex: 'ip_address',
      key: 'ip_address',
      width: 120,
      render: (v: string) => (
        <Text style={{ fontSize: 11, fontFamily: 'monospace', color: '#94a3b8' }}>{v || '—'}</Text>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Space size={8}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: 'linear-gradient(135deg, #7c3aed, #a78bfa)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <AuditOutlined style={{ color: '#fff', fontSize: 15 }} />
          </div>
          <Title level={4} style={{ margin: 0 }}>操作审计日志</Title>
        </Space>
        <Space>
          <Select
            placeholder="操作类型"
            value={actionFilter || undefined}
            allowClear
            onChange={(v) => setActionFilter(v || '')}
            style={{ width: 140 }}
            options={Object.entries(ACTION_LABELS).map(([k, v]) => ({ value: k, label: v.label }))}
          />
          <Input
            placeholder="搜索操作人或详情"
            value={keyword}
            onChange={(e) => {
              setKeyword(e.target.value)
              if (!e.target.value) loadLogs(1, '', actionFilter)
            }}
            onPressEnter={handleSearch}
            style={{ width: 200 }}
            prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
            allowClear
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
            搜索
          </Button>
        </Space>
      </div>

      <Table
        dataSource={logs}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize: 20,
          total,
          onChange: (p) => { setPage(p); loadLogs(p, keyword, actionFilter) },
          showTotal: (t) => `共 ${t} 条日志`,
          showSizeChanger: false,
        }}
        size="middle"
        style={{ borderRadius: 12, overflow: 'hidden' }}
        scroll={{ x: 900 }}
      />
    </div>
  )
}
