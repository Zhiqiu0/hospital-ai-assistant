import { useEffect, useState } from 'react'
import {
  Table, Button, Modal, Form, Input, Select, Space,
  Tag, Typography, Switch, Popconfirm, message
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import api from '@/services/api'

const { Title } = Typography
const { TextArea } = Input

const RISK_COLORS: Record<string, string> = { high: 'red', medium: 'orange', low: 'blue' }
const RISK_LABELS: Record<string, string> = { high: '高危', medium: '中危', low: '低危' }
const TYPE_LABELS: Record<string, string> = { completeness: '完整性', format: '格式', logic: '逻辑' }

export default function QCRulesPage() {
  const [rules, setRules] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editRule, setEditRule] = useState<any>(null)
  const [form] = Form.useForm()

  const loadRules = async () => {
    setLoading(true)
    try {
      const data: any = await api.get('/admin/qc-rules')
      setRules(data.items || [])
    } finally { setLoading(false) }
  }

  useEffect(() => { loadRules() }, [])

  const openCreate = () => {
    setEditRule(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (rule: any) => {
    setEditRule(rule)
    form.setFieldsValue(rule)
    setModalOpen(true)
  }

  const handleSubmit = async (values: any) => {
    try {
      if (editRule) {
        await api.put(`/admin/qc-rules/${editRule.id}`, values)
        message.success('更新成功')
      } else {
        await api.post('/admin/qc-rules', values)
        message.success('创建成功')
      }
      setModalOpen(false)
      loadRules()
    } catch { message.error('操作失败') }
  }

  const handleToggle = async (id: string) => {
    try {
      await api.put(`/admin/qc-rules/${id}/toggle`, {})
      loadRules()
    } catch { message.error('操作失败') }
  }

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/admin/qc-rules/${id}`)
      message.success('已删除')
      loadRules()
    } catch { message.error('删除失败') }
  }

  const columns = [
    { title: '规则名称', dataIndex: 'name', key: 'name' },
    {
      title: '类型', dataIndex: 'rule_type', key: 'rule_type',
      render: (v: string) => <Tag>{TYPE_LABELS[v] || v}</Tag>
    },
    { title: '针对字段', dataIndex: 'field_name', key: 'field_name' },
    {
      title: '风险等级', dataIndex: 'risk_level', key: 'risk_level',
      render: (v: string) => <Tag color={RISK_COLORS[v]}>{RISK_LABELS[v] || v}</Tag>
    },
    {
      title: '启用', dataIndex: 'is_active', key: 'is_active',
      render: (v: boolean, record: any) => (
        <Switch checked={v} size="small" onChange={() => handleToggle(record.id)} />
      )
    },
    {
      title: '操作', key: 'action',
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm title="确认删除该规则？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      )
    }
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>质控规则</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建规则</Button>
      </div>
      <Table columns={columns} dataSource={rules} rowKey="id" loading={loading} pagination={false} />
      <Modal
        title={editRule ? '编辑质控规则' : '新建质控规则'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        okText="确认"
        cancelText="取消"
        width={520}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item label="规则名称" name="name" rules={[{ required: true }]}>
            <Input placeholder="如：主诉不能为空" />
          </Form.Item>
          <Form.Item label="规则类型" name="rule_type" rules={[{ required: true }]}>
            <Select options={[
              { value: 'completeness', label: '完整性' },
              { value: 'format', label: '格式' },
              { value: 'logic', label: '逻辑' },
            ]} />
          </Form.Item>
          <Form.Item label="针对字段" name="field_name">
            <Select allowClear placeholder="选择字段（可选）" options={[
              { value: 'chief_complaint', label: '主诉' },
              { value: 'history_present_illness', label: '现病史' },
              { value: 'past_history', label: '既往史' },
              { value: 'allergy_history', label: '过敏史' },
              { value: 'physical_exam', label: '体格检查' },
              { value: 'initial_diagnosis', label: '初步诊断' },
            ]} />
          </Form.Item>
          <Form.Item label="规则条件描述" name="condition">
            <Input placeholder="如：不能为空，长度不超过20字" />
          </Form.Item>
          <Form.Item label="风险等级" name="risk_level" rules={[{ required: true }]}>
            <Select options={[
              { value: 'high', label: '高危' },
              { value: 'medium', label: '中危' },
              { value: 'low', label: '低危' },
            ]} />
          </Form.Item>
          <Form.Item label="描述说明" name="description">
            <TextArea rows={2} placeholder="规则的详细说明（可选）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
