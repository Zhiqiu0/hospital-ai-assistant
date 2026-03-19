import { useEffect, useState } from 'react'
import {
  Table, Button, Modal, Form, Input, Space,
  Tag, Typography, Popconfirm, message
} from 'antd'
import { PlusOutlined, StopOutlined } from '@ant-design/icons'
import api from '@/services/api'

const { Title } = Typography

export default function DepartmentsPage() {
  const [depts, setDepts] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()

  const loadDepts = async () => {
    setLoading(true)
    try {
      const data: any = await api.get('/admin/departments')
      setDepts(data.items || [])
    } finally { setLoading(false) }
  }

  useEffect(() => { loadDepts() }, [])

  const handleSubmit = async (values: any) => {
    try {
      await api.post('/admin/departments', values)
      message.success('科室创建成功')
      setModalOpen(false)
      form.resetFields()
      loadDepts()
    } catch (e: any) {
      message.error(e?.detail || '创建失败')
    }
  }

  const handleDeactivate = async (id: string) => {
    try {
      await api.delete(`/admin/departments/${id}`)
      message.success('已停用')
      loadDepts()
    } catch { message.error('操作失败') }
  }

  const columns = [
    { title: '科室名称', dataIndex: 'name', key: 'name' },
    { title: '科室编码', dataIndex: 'code', key: 'code', render: (v: string) => <Tag>{v}</Tag> },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active',
      render: (v: boolean) => <Tag color={v ? 'success' : 'default'}>{v ? '启用' : '停用'}</Tag>
    },
    {
      title: '操作', key: 'action',
      render: (_: any, record: any) => (
        <Space>
          {record.is_active && (
            <Popconfirm title="确认停用该科室？" onConfirm={() => handleDeactivate(record.id)}>
              <Button size="small" danger icon={<StopOutlined />}>停用</Button>
            </Popconfirm>
          )}
        </Space>
      )
    }
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>科室管理</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setModalOpen(true) }}>
          新建科室
        </Button>
      </div>
      <Table columns={columns} dataSource={depts} rowKey="id" loading={loading} pagination={false} />
      <Modal
        title="新建科室"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        okText="确认"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item label="科室名称" name="name" rules={[{ required: true, message: '请输入科室名称' }]}>
            <Input placeholder="如：内科、外科" />
          </Form.Item>
          <Form.Item label="科室编码" name="code" rules={[{ required: true, message: '请输入编码' }]}>
            <Input placeholder="如：NEIKE（英文大写）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
