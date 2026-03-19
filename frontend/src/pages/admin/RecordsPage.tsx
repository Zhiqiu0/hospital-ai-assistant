import { useEffect, useState } from 'react'
import { Table, Tag, Typography, Modal, Button, Space, Input } from 'antd'
import { FileTextOutlined, SearchOutlined, EyeOutlined, CheckOutlined } from '@ant-design/icons'
import api from '@/services/api'

const { Title, Text } = Typography

const RECORD_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊病历', admission_note: '入院记录', first_course_record: '首次病程',
}

export default function RecordsPage() {
  const [records, setRecords] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [viewRecord, setViewRecord] = useState<any>(null)

  const loadRecords = async (p = page) => {
    setLoading(true)
    try {
      const data: any = await api.get(`/admin/records?page=${p}&page_size=20`)
      setRecords(data.items || [])
      setTotal(data.total || 0)
    } finally { setLoading(false) }
  }

  useEffect(() => { loadRecords() }, [])

  const filtered = search
    ? records.filter((r) =>
        r.patient_name?.includes(search) || r.doctor_name?.includes(search)
      )
    : records

  const columns = [
    {
      title: '患者', dataIndex: 'patient_name', key: 'patient_name',
      render: (name: string, row: any) => (
        <Space size={4}>
          <Text strong>{name}</Text>
          {row.patient_gender && (
            <Tag color={row.patient_gender === 'male' ? 'blue' : 'pink'} style={{ fontSize: 11, margin: 0 }}>
              {row.patient_gender === 'male' ? '男' : '女'}
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: '病历类型', dataIndex: 'record_type', key: 'record_type',
      render: (v: string) => <Tag color="blue">{RECORD_TYPE_LABEL[v] || v}</Tag>,
    },
    {
      title: '主治医生', dataIndex: 'doctor_name', key: 'doctor_name',
      render: (name: string) => <Text>{name}</Text>,
    },
    {
      title: '签发时间', dataIndex: 'submitted_at', key: 'submitted_at',
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
      sorter: (a: any, b: any) =>
        new Date(a.submitted_at).getTime() - new Date(b.submitted_at).getTime(),
      defaultSortOrder: 'descend' as const,
    },
    {
      title: '内容摘要', dataIndex: 'content_preview', key: 'content_preview',
      ellipsis: true,
      render: (v: string) => <Text type="secondary" style={{ fontSize: 12 }}>{v || '—'}</Text>,
    },
    {
      title: '操作', key: 'action',
      render: (_: any, record: any) => (
        <Button
          size="small" type="link" icon={<EyeOutlined />}
          onClick={() => setViewRecord(record)}
        >
          查看病历
        </Button>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0, color: '#0f172a' }}>病历管理</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>所有已签发病历（管理员可见全部，医生仅见本人）</Text>
        </div>
        <Input
          prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
          placeholder="搜索患者姓名或医生"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 220 }}
          allowClear
        />
      </div>

      <Table
        columns={columns}
        dataSource={filtered}
        rowKey="id"
        loading={loading}
        pagination={{
          total, pageSize: 20, current: page,
          onChange: (p) => { setPage(p); loadRecords(p) },
          showTotal: (t) => `共 ${t} 份病历`,
        }}
        style={{ background: '#fff', borderRadius: 10 }}
      />

      <Modal
        title={
          viewRecord && (
            <Space>
              <FileTextOutlined style={{ color: '#2563eb' }} />
              <span>{viewRecord.patient_name}</span>
              <Tag color="blue">{RECORD_TYPE_LABEL[viewRecord?.record_type] || viewRecord?.record_type}</Tag>
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                主治：{viewRecord.doctor_name}
              </Text>
            </Space>
          )
        }
        open={!!viewRecord}
        onCancel={() => setViewRecord(null)}
        footer={<Button onClick={() => setViewRecord(null)}>关闭</Button>}
        width={700}
      >
        <Text type="secondary" style={{ fontSize: 12 }}>
          签发时间：{viewRecord?.submitted_at ? new Date(viewRecord.submitted_at).toLocaleString('zh-CN') : '-'}
        </Text>
        <div style={{
          background: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: 8,
          padding: '20px 24px',
          maxHeight: 500,
          overflowY: 'auto',
          fontSize: 14,
          lineHeight: 1.9,
          whiteSpace: 'pre-wrap',
          margin: '12px 0',
          fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
          color: '#1e293b',
        }}>
          {viewRecord?.content || '（病历内容为空）'}
        </div>
        <div style={{
          padding: '8px 12px',
          background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8,
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <CheckOutlined style={{ color: '#22c55e' }} />
          <Text style={{ fontSize: 12, color: '#166534' }}>已签发病历，归档不可修改</Text>
        </div>
      </Modal>
    </div>
  )
}
