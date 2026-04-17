/**
 * 质控规则管理页（pages/admin/QCRulesPage.tsx）
 *
 * 管理规则引擎使用的质控规则库，调用 GET/POST/PUT/DELETE /admin/qc-rules：
 *   - 规则类型：completeness（完整性）/ insurance（医保风险）
 *   - 字段：rule_name、field_name、condition、risk_level、is_active
 *   - 启用/禁用：Switch 控制，禁用后规则引擎跳过该条规则
 *   - 新建/编辑：弹窗表单，condition 字段支持表达式语法
 *
 * 规则存库后即时生效：
 *   规则引擎每次质控时重新从 DB 加载 active 规则，
 *   无缓存，修改立刻影响下一次质控扫描。
 */
import { useEffect, useState } from 'react'
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Space,
  Tag,
  Typography,
  Switch,
  Popconfirm,
  message,
  Tooltip,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'
import api from '@/services/api'

const { Title, Text } = Typography
const { TextArea } = Input

const RISK_COLORS: Record<string, string> = { high: 'red', medium: 'orange', low: 'green' }
const RISK_LABELS: Record<string, string> = { high: '高危', medium: '中危', low: '低危' }
const TYPE_LABELS: Record<string, string> = { completeness: '完整性', insurance: '医保风险' }
const TYPE_COLORS: Record<string, string> = { completeness: 'blue', insurance: 'purple' }
const SCOPE_LABELS: Record<string, string> = {
  all: '通用',
  inpatient: '住院',
  revisit: '复诊',
  tcm: '中医',
}
const SCOPE_COLORS: Record<string, string> = {
  all: 'default',
  inpatient: 'cyan',
  revisit: 'geekblue',
  tcm: 'green',
}

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
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRules()
  }, [])

  const openCreate = () => {
    setEditRule(null)
    form.resetFields()
    form.setFieldsValue({ rule_type: 'completeness', scope: 'all', risk_level: 'medium' })
    setModalOpen(true)
  }

  const openEdit = (rule: any) => {
    setEditRule(rule)
    form.setFieldsValue({
      ...rule,
      keywords: rule.keywords || [],
      indication_keywords: rule.indication_keywords || [],
    })
    setModalOpen(true)
  }

  const handleSubmit = async (values: any) => {
    // Select mode="tags" 返回 string[]，直接传给后端
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
    } catch {
      message.error('操作失败')
    }
  }

  const handleToggle = async (id: string) => {
    try {
      await api.put(`/admin/qc-rules/${id}/toggle`, {})
      loadRules()
    } catch {
      message.error('操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/admin/qc-rules/${id}`)
      message.success('已删除')
      loadRules()
    } catch {
      message.error('删除失败')
    }
  }

  const columns = [
    {
      title: '编码',
      dataIndex: 'rule_code',
      key: 'rule_code',
      width: 90,
      render: (v: string) => (
        <Text code style={{ fontSize: 12 }}>
          {v}
        </Text>
      ),
    },
    { title: '规则名称', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '类型',
      dataIndex: 'rule_type',
      key: 'rule_type',
      width: 90,
      render: (v: string) => <Tag color={TYPE_COLORS[v] || 'default'}>{TYPE_LABELS[v] || v}</Tag>,
    },
    {
      title: '范围',
      dataIndex: 'scope',
      key: 'scope',
      width: 75,
      render: (v: string) => <Tag color={SCOPE_COLORS[v] || 'default'}>{SCOPE_LABELS[v] || v}</Tag>,
    },
    {
      title: '风险',
      dataIndex: 'risk_level',
      key: 'risk_level',
      width: 70,
      render: (v: string) => <Tag color={RISK_COLORS[v]}>{RISK_LABELS[v] || v}</Tag>,
    },
    {
      title: '关键词数',
      key: 'kw_count',
      width: 80,
      render: (_: any, r: any) => (r.keywords?.length || 0) + ' 个',
    },
    {
      title: '启用',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 65,
      render: (v: boolean, record: any) => (
        <Switch checked={v} size="small" onChange={() => handleToggle(record.id)} />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_: any, record: any) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确认删除该规则？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
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
          marginBottom: 16,
        }}
      >
        <div>
          <Title level={4} style={{ margin: 0 }}>
            质控规则管理
          </Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            共 {rules.length} 条规则，规则变更实时生效，无需重启服务
          </Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建规则
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={rules}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{ pageSize: 20, showSizeChanger: false }}
        expandable={{
          expandedRowRender: record => (
            <div style={{ padding: '8px 16px', background: '#fafafa', fontSize: 13 }}>
              {record.issue_description && (
                <div>
                  <b>问题描述：</b>
                  {record.issue_description}
                </div>
              )}
              {record.suggestion && (
                <div style={{ marginTop: 4 }}>
                  <b>修改建议：</b>
                  {record.suggestion}
                </div>
              )}
              {record.keywords?.length > 0 && (
                <div style={{ marginTop: 4 }}>
                  <b>触发关键词：</b>
                  {record.keywords.map((kw: string) => (
                    <Tag key={kw} style={{ marginBottom: 2 }}>
                      {kw}
                    </Tag>
                  ))}
                </div>
              )}
              {record.indication_keywords?.length > 0 && (
                <div style={{ marginTop: 4 }}>
                  <b>豁免关键词：</b>
                  {record.indication_keywords.map((kw: string) => (
                    <Tag key={kw} color="green" style={{ marginBottom: 2 }}>
                      {kw}
                    </Tag>
                  ))}
                </div>
              )}
            </div>
          ),
        }}
      />

      <Modal
        title={editRule ? '编辑质控规则' : '新建质控规则'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        okText="保存"
        cancelText="取消"
        width={600}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
            <Form.Item
              label="规则编码"
              name="rule_code"
              rules={[{ required: true, message: '请填写规则编码' }]}
            >
              <Input placeholder="如：CC001、INS007" />
            </Form.Item>
            <Form.Item label="规则名称" name="name" rules={[{ required: true }]}>
              <Input placeholder="如：主诉缺失" />
            </Form.Item>
            <Form.Item label="规则类型" name="rule_type" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: 'completeness', label: '完整性（字段存在检查）' },
                  { value: 'insurance', label: '医保风险（关键词触发）' },
                ]}
              />
            </Form.Item>
            <Form.Item
              label={
                <span>
                  适用范围&nbsp;
                  <Tooltip title="all=通用，inpatient=住院，revisit=复诊，tcm=含中医内容">
                    <QuestionCircleOutlined style={{ color: '#999' }} />
                  </Tooltip>
                </span>
              }
              name="scope"
              rules={[{ required: true }]}
            >
              <Select
                options={[
                  { value: 'all', label: '通用（门诊+住院）' },
                  { value: 'inpatient', label: '住院专用' },
                  { value: 'revisit', label: '复诊专用' },
                  { value: 'tcm', label: '中医内容' },
                ]}
              />
            </Form.Item>
            <Form.Item label="风险等级" name="risk_level" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: 'high', label: '高危' },
                  { value: 'medium', label: '中危' },
                  { value: 'low', label: '低危' },
                ]}
              />
            </Form.Item>
            <Form.Item label="对应字段名" name="field_name">
              <Input placeholder="如：chief_complaint（可选）" />
            </Form.Item>
          </div>

          <Form.Item
            label={
              <span>
                触发关键词&nbsp;
                <Tooltip title="完整性规则：病历中出现任一关键词即视为已填写（不触发）；医保规则：出现任一关键词则触发。输入后按 Enter 确认。">
                  <QuestionCircleOutlined style={{ color: '#999' }} />
                </Tooltip>
              </span>
            }
            name="keywords"
          >
            <Select
              mode="tags"
              placeholder="输入关键词后按 Enter 添加，如：【主诉】 主诉："
              tokenSeparators={[',']}
              open={false}
            />
          </Form.Item>

          <Form.Item
            label={
              <span>
                豁免关键词（仅医保规则）&nbsp;
                <Tooltip title="触发词出现后，若附近同时出现豁免词，则不报警。为空则无条件触发。">
                  <QuestionCircleOutlined style={{ color: '#999' }} />
                </Tooltip>
              </span>
            }
            name="indication_keywords"
          >
            <Select
              mode="tags"
              placeholder="如：因、由于、诊断、为明确（留空=无条件触发）"
              tokenSeparators={[',']}
              open={false}
            />
          </Form.Item>

          <Form.Item label="问题描述（展示给医生）" name="issue_description">
            <Input placeholder="如：主诉未填写（扣1分）" />
          </Form.Item>
          <Form.Item label="修改建议（展示给医生）" name="suggestion">
            <TextArea rows={2} placeholder="如：请填写患者主诉，格式：症状+持续时间" />
          </Form.Item>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '0 16px' }}>
            <Form.Item label="扣分说明" name="score_impact">
              <Input placeholder="如：-1分" />
            </Form.Item>
            <Form.Item label="规则说明（内部备注）" name="description">
              <Input placeholder="可选，内部备注，不显示给医生" />
            </Form.Item>
          </div>
        </Form>
      </Modal>
    </div>
  )
}
