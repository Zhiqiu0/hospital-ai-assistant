import { useEffect, useState } from 'react'
import {
  Table, Button, Modal, Form, Input, Select, Space,
  Tag, Typography, Popconfirm, message
} from 'antd'
import { PlusOutlined, EditOutlined, StopOutlined } from '@ant-design/icons'
import api from '@/services/api'

const { Title } = Typography

const ROLE_MAP: Record<string, { label: string; color: string }> = {
  super_admin: { label: '超级管理员', color: 'red' },
  hospital_admin: { label: '医院管理员', color: 'orange' },
  dept_admin: { label: '科室管理员', color: 'gold' },
  doctor: { label: '医生', color: 'blue' },
  nurse: { label: '护士', color: 'cyan' },
}

export default function UsersPage() {
  const [users, setUsers] = useState<any[]>([])
  const [departments, setDepartments] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editUser, setEditUser] = useState<any>(null)
  const [form] = Form.useForm()

  const loadUsers = async (p = page) => {
    setLoading(true)
    try {
      const data: any = await api.get(`/admin/users?page=${p}&page_size=10`)
      setUsers(data.items)
      setTotal(data.total)
    } finally { setLoading(false) }
  }

  const loadDepts = async () => {
    const data: any = await api.get('/admin/departments')
    setDepartments(data.items || [])
  }

  useEffect(() => { loadUsers(); loadDepts() }, [])

  const openCreate = () => {
    setEditUser(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (user: any) => {
    setEditUser(user)
    form.setFieldsValue({ real_name: user.real_name, role: user.role, department_id: user.department_id })
    setModalOpen(true)
  }

  const handleSubmit = async (values: any) => {
    try {
      if (editUser) {
        await api.put(`/admin/users/${editUser.id}`, values)
        message.success('更新成功')
      } else {
        await api.post('/admin/users', values)
        message.success('创建成功')
      }
      setModalOpen(false)
      loadUsers()
    } catch (e: any) {
      message.error(e?.detail || '操作失败')
    }
  }

  const handleDeactivate = async (id: string) => {
    try {
      await api.delete(`/admin/users/${id}`)
      message.success('已停用')
      loadUsers()
    } catch { message.error('操作失败') }
  }

  const columns = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '姓名', dataIndex: 'real_name', key: 'real_name' },
    {
      title: '角色', dataIndex: 'role', key: 'role',
      render: (role: string) => {
        const r = ROLE_MAP[role] || { label: role, color: 'default' }
        return <Tag color={r.color}>{r.label}</Tag>
      }
    },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active',
      render: (v: boolean) => <Tag color={v ? 'success' : 'default'}>{v ? '启用' : '停用'}</Tag>
    },
    {
      title: '操作', key: 'action',
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>编辑</Button>
          {record.is_active && (
            <Popconfirm title="确认停用该用户？" onConfirm={() => handleDeactivate(record.id)}>
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
        <Title level={4} style={{ margin: 0 }}>用户管理</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用户</Button>
      </div>
      <Table
        columns={columns}
        dataSource={users}
        rowKey="id"
        loading={loading}
        pagination={{ total, pageSize: 10, current: page, onChange: (p) => { setPage(p); loadUsers(p) } }}
      />
      <Modal
        title={editUser ? '编辑用户' : '新建用户'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        okText="确认"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          {!editUser && (
            <>
              <Form.Item label="用户名" name="username" rules={[{ required: true }]}>
                <Input placeholder="登录用户名" />
              </Form.Item>
              <Form.Item label="密码" name="password" rules={[{ required: true, min: 6 }]}>
                <Input.Password placeholder="至少6位" />
              </Form.Item>
            </>
          )}
          <Form.Item label="姓名" name="real_name" rules={[{ required: true }]}>
            <Input placeholder="真实姓名" />
          </Form.Item>
          <Form.Item label="角色" name="role" rules={[{ required: true }]}>
            <Select options={Object.entries(ROLE_MAP).map(([v, r]) => ({ value: v, label: r.label }))} />
          </Form.Item>
          <Form.Item label="所属科室" name="department_id">
            <Select
              allowClear
              placeholder="选择科室（可选）"
              options={departments.map((d: any) => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
          {!editUser && (
            <>
              <Form.Item label="工号" name="employee_no">
                <Input placeholder="员工编号（可选）" />
              </Form.Item>
              <Form.Item label="手机号" name="phone">
                <Input placeholder="手机号（可选）" />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>
    </div>
  )
}
