/**
 * 科室管理页（pages/admin/DepartmentsPage.tsx）
 *
 * 管理医院科室的树状结构，调用 GET/POST/PUT/DELETE /admin/departments：
 *   - 树形表格展示父子科室关系（parent_id 关联）
 *   - 新建科室：可选父科室（下拉选择已有科室）
 *   - 编辑：修改科室名称、负责人、联系方式
 *   - 软删除：is_active=False，已有关联用户的科室不允许删除
 *
 * 科室数据用于：
 *   - 用户创建时分配所属科室
 *   - 统计页按科室维度汇总病历量
 */
import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Space, Tag, Typography, Popconfirm } from 'antd'
import { PlusOutlined, StopOutlined, CheckCircleOutlined, EditOutlined } from '@ant-design/icons'
import api from '@/services/api'
import { message } from '@/services/messageBridge'

const { Title } = Typography

/** 科室列表行——对应后端 DepartmentResponse */
interface DepartmentRow {
  id: string
  name: string
  code: string
  is_active: boolean
}

/** 新建/编辑科室表单字段；编辑模式 code 只读但表单仍持有 */
interface DepartmentFormValues {
  name: string
  code: string
}

export default function DepartmentsPage() {
  const [depts, setDepts] = useState<DepartmentRow[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  // editing=null：新建模式；editing=科室对象：编辑模式。两个模式共用同一份 Modal/Form
  // 跟用户管理页一致：避免多套 Modal 漂移
  const [editing, setEditing] = useState<DepartmentRow | null>(null)
  const [form] = Form.useForm<DepartmentFormValues>()

  const loadDepts = async () => {
    setLoading(true)
    try {
      const data = (await api.get('/admin/departments')) as { items?: DepartmentRow[] }
      setDepts(data.items || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadDepts()
  }, [])

  const handleSubmit = async (values: DepartmentFormValues) => {
    try {
      if (editing) {
        // 编辑：只允许改 name；code 后端拒绝修改，从 payload 里剔除避免误传
        await api.put(`/admin/departments/${editing.id}`, { name: values.name })
        message.success('科室已更新')
      } else {
        await api.post('/admin/departments', values)
        message.success('科室创建成功')
      }
      setModalOpen(false)
      setEditing(null)
      // form.resetFields 由下面 useEffect 监听 modalOpen 变化时统一处理
      // 这里手动调会在 Modal 关闭后撞 "useForm not connected" 警告（Form 卸载了）
      loadDepts()
    } catch (e) {
      const detail = (e as { detail?: string })?.detail
      message.error(detail || (editing ? '更新失败' : '创建失败'))
    }
  }

  const openEdit = (record: DepartmentRow) => {
    setEditing(record)
    setModalOpen(true)
  }

  // form.resetFields / setFieldsValue 必须等 Modal 内的 Form 挂载之后再调，
  // 否则 useForm 实例没连接到任何 Form 元素，触发
  // "Instance created by useForm is not connected to any Form element" 警告。
  useEffect(() => {
    if (!modalOpen) return
    if (editing) {
      form.setFieldsValue({ name: editing.name, code: editing.code })
    } else {
      form.resetFields()
    }
  }, [modalOpen, editing, form])

  const handleDeactivate = async (id: string) => {
    try {
      await api.delete(`/admin/departments/${id}`)
      message.success('已停用')
      loadDepts()
    } catch {
      message.error('操作失败')
    }
  }

  // 启用已停用科室（2026-05-03 加）—— 与用户管理对齐，让停用动作可逆
  const handleActivate = async (id: string) => {
    try {
      await api.post(`/admin/departments/${id}/activate`)
      message.success('已启用')
      loadDepts()
    } catch {
      message.error('操作失败')
    }
  }

  const columns = [
    { title: '科室名称', dataIndex: 'name', key: 'name' },
    { title: '科室编码', dataIndex: 'code', key: 'code', render: (v: string) => <Tag>{v}</Tag> },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (v: boolean) => <Tag color={v ? 'success' : 'default'}>{v ? '启用' : '停用'}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: DepartmentRow) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          {record.is_active ? (
            <Popconfirm title="确认停用该科室？" onConfirm={() => handleDeactivate(record.id)}>
              <Button size="small" danger icon={<StopOutlined />}>
                停用
              </Button>
            </Popconfirm>
          ) : (
            <Popconfirm title="确认启用该科室？" onConfirm={() => handleActivate(record.id)}>
              <Button size="small" type="primary" icon={<CheckCircleOutlined />}>
                启用
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          科室管理
        </Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            // 新建按钮：先清 editing 再开 Modal，resetFields 由 useEffect 监听处理
            setEditing(null)
            setModalOpen(true)
          }}
        >
          新建科室
        </Button>
      </div>
      <Table
        columns={columns}
        dataSource={depts}
        rowKey="id"
        loading={loading}
        pagination={false}
      />
      <Modal
        title={editing ? '编辑科室' : '新建科室'}
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false)
          setEditing(null)
        }}
        onOk={() => form.submit()}
        okText="确认"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            label="科室名称"
            name="name"
            rules={[{ required: true, message: '请输入科室名称' }]}
          >
            <Input placeholder="如：内科、外科" />
          </Form.Item>
          <Form.Item
            label="科室编码"
            name="code"
            rules={[{ required: true, message: '请输入编码' }]}
            // 编辑模式下科室编码只读：HIS 同步、历史外键都依赖 code，改动会让旧数据失联。
            // 跟后端 DepartmentUpdate 不接 code 字段的限制保持一致。
            tooltip={editing ? '科室编码创建后不可修改' : undefined}
          >
            <Input placeholder="如：NEIKE（英文大写）" disabled={!!editing} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
