/**
 * 患者管理页（pages/admin/PatientsPage.tsx）
 *
 * 管理员查看和维护全量患者档案，调用 GET /admin/patients（分页）：
 *   - 搜索：按姓名、身份证号、手机号模糊查询
 *   - 编辑患者基本信息：PUT /patients/{id}
 *   - 查看患者就诊历史：点击展开关联的接诊和病历列表
 *
 * 权限说明：
 *   医生端只能在接诊时创建/查询患者；
 *   管理员可跨科室查看全院患者，并可修正错误信息——但**不能主动新建患者**，
 *   建档只发生在接诊流程中，由医生在初诊登记时创建（确保每个患者档案都关联
 *   到一次具体接诊，避免无主孤儿档案）。如需录入外院转入或 HIS 缺失患者，
 *   由医生开一次接诊登记同步建档。
 */
import { useEffect, useState, useCallback } from 'react'
import { Table, Button, Modal, Form, Input, Select, Space, Tag, Typography, DatePicker } from 'antd'
import { EditOutlined, SearchOutlined, UserOutlined } from '@ant-design/icons'
import api from '@/services/api'

// 统一身份证 / 手机号校验工厂规则，与门诊/住院新建表单走同一份规则
import { phoneRule } from '@/utils/validators'
import { message } from '@/services/messageBridge'
import dayjs, { type Dayjs } from 'dayjs'

const { Title, Text } = Typography

const GENDER_MAP: Record<string, { label: string; color: string }> = {
  male: { label: '男', color: 'blue' },
  female: { label: '女', color: 'pink' },
  unknown: { label: '未知', color: 'default' },
}

/** 患者列表行——对应后端 PatientResponse 子集（本页展示用到的字段） */
interface PatientRow {
  id: string
  patient_no?: string | null
  name: string
  gender?: string | null
  age?: number | null
  phone?: string | null
  birth_date?: string | null
}

/** 编辑患者弹窗表单字段——birth_date 是 dayjs 对象（DatePicker 控件） */
interface PatientFormValues {
  name: string
  gender?: string
  phone?: string
  birth_date?: Dayjs | null
}

export default function PatientsPage() {
  const [patients, setPatients] = useState<PatientRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editPatient, setEditPatient] = useState<PatientRow | null>(null)
  const [form] = Form.useForm<PatientFormValues>()

  const loadPatients = useCallback(
    async (p = page, kw = keyword) => {
      setLoading(true)
      try {
        const data = (await api.get(
          `/patients?page=${p}&page_size=10&keyword=${encodeURIComponent(kw)}`
        )) as { items?: PatientRow[]; total?: number }
        setPatients(data.items || [])
        setTotal(data.total || 0)
      } finally {
        setLoading(false)
      }
    },
    [page, keyword]
  )

  useEffect(() => {
    loadPatients()
    // 只需挂载时拉一次；loadPatients 内部 setState 在此语义下是预期
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSearch = () => {
    setPage(1)
    loadPatients(1, keyword)
  }

  const openEdit = (patient: PatientRow) => {
    setEditPatient(patient)
    setModalOpen(true)
  }

  // form.setFieldsValue 必须等 Modal 内 Form 挂载后再调，否则触发
  // "Instance created by useForm is not connected to any Form element" 警告
  useEffect(() => {
    if (!modalOpen || !editPatient) return
    form.setFieldsValue({
      name: editPatient.name,
      gender: editPatient.gender ?? undefined,
      phone: editPatient.phone ?? undefined,
      birth_date: editPatient.birth_date ? dayjs(editPatient.birth_date) : undefined,
    })
  }, [modalOpen, editPatient, form])

  const handleSubmit = async (values: PatientFormValues) => {
    if (!editPatient) return
    try {
      await api.put(`/patients/${editPatient.id}`, {
        ...values,
        birth_date: values.birth_date ? values.birth_date.format('YYYY-MM-DD') : undefined,
      })
      message.success('患者信息已更新')
      setModalOpen(false)
      loadPatients()
    } catch {
      message.error('更新失败，请重试')
    }
  }

  const columns = [
    {
      title: '患者编号',
      dataIndex: 'patient_no',
      key: 'patient_no',
      width: 120,
      render: (v: string) => (
        <Text style={{ fontFamily: 'monospace', fontSize: 12, color: 'var(--text-3)' }}>
          {v || '—'}
        </Text>
      ),
    },
    {
      title: '姓名',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => (
        <Space size={6}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              background: 'linear-gradient(135deg, #eff6ff, #dbeafe)',
              border: '1px solid #bfdbfe',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <UserOutlined style={{ color: '#2563eb', fontSize: 13 }} />
          </div>
          <Text strong style={{ fontSize: 14 }}>
            {name}
          </Text>
        </Space>
      ),
    },
    {
      title: '性别',
      dataIndex: 'gender',
      key: 'gender',
      width: 80,
      render: (g: string) => {
        const info = GENDER_MAP[g] || { label: g || '—', color: 'default' }
        return (
          <Tag color={info.color} style={{ borderRadius: 20 }}>
            {info.label}
          </Tag>
        )
      },
    },
    {
      title: '年龄',
      dataIndex: 'age',
      key: 'age',
      width: 80,
      render: (age: number) => (age != null ? `${age} 岁` : '—'),
    },
    {
      title: '联系电话',
      dataIndex: 'phone',
      key: 'phone',
      width: 140,
      render: (v: string) => v || '—',
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: unknown, record: PatientRow) => (
        <Button
          size="small"
          icon={<EditOutlined />}
          onClick={() => openEdit(record)}
          style={{ borderRadius: 6 }}
        >
          编辑
        </Button>
      ),
    },
  ]

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 20,
        }}
      >
        <Title level={4} style={{ margin: 0 }}>
          患者档案管理
        </Title>
        <Space>
          <Input
            placeholder="搜索姓名或患者编号"
            value={keyword}
            onChange={e => {
              setKeyword(e.target.value)
              if (!e.target.value) loadPatients(1, '')
            }}
            onPressEnter={handleSearch}
            style={{ width: 220 }}
            prefix={<SearchOutlined style={{ color: 'var(--text-4)' }} />}
            allowClear
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
            搜索
          </Button>
        </Space>
      </div>

      <Table
        dataSource={patients}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize: 10,
          total,
          onChange: p => {
            setPage(p)
            loadPatients(p, keyword)
          },
          showTotal: t => `共 ${t} 位患者`,
          showSizeChanger: false,
        }}
        size="middle"
        style={{ borderRadius: 12, overflow: 'hidden' }}
      />

      <Modal
        title={
          <Space>
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: 8,
                background: 'linear-gradient(135deg, #2563eb, #3b82f6)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <EditOutlined style={{ color: 'var(--surface)', fontSize: 13 }} />
            </div>
            <span>编辑患者信息</span>
          </Space>
        }
        open={modalOpen}
        onCancel={() => {
          // Modal 关闭后 Form 卸载（destroyOnHidden），不需要 form.resetFields，
          // 否则触发 "useForm not connected" 警告
          setModalOpen(false)
        }}
        onOk={() => form.submit()}
        okText="保存"
        width={480}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit} style={{ marginTop: 16 }}>
          <Form.Item name="name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}>
            <Input placeholder="患者姓名" />
          </Form.Item>
          <div style={{ display: 'flex', gap: 12 }}>
            <Form.Item name="gender" label="性别" style={{ flex: 1 }}>
              <Select allowClear placeholder="请选择">
                <Select.Option value="male">男</Select.Option>
                <Select.Option value="female">女</Select.Option>
                <Select.Option value="unknown">未知</Select.Option>
              </Select>
            </Form.Item>
            <Form.Item name="birth_date" label="出生日期" style={{ flex: 1 }}>
              <DatePicker style={{ width: '100%' }} placeholder="选择日期" />
            </Form.Item>
          </div>
          <Form.Item name="phone" label="联系电话" rules={[phoneRule()]}>
            <Input placeholder="手机号码" maxLength={11} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
