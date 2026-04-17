/**
 * AI 提示词管理页（pages/admin/PromptsPage.tsx）
 *
 * 管理系统内置的 AI 提示词模板，调用 GET/PUT /admin/prompts：
 *   - 列出所有 task_type 对应的提示词（生成、质控、建议、语音等）
 *   - 点击「编辑」打开 Monaco Editor 或 TextArea 直接修改提示词文本
 *   - 修改后立即写入数据库并生效（下次 AI 调用时使用新提示词）
 *   - 「恢复默认」按钮重置为代码中的 prompts_*.py 内容
 *
 * 为何需要此页：
 *   各医院合规要求和用语习惯不同，提示词需按医院定制，
 *   通过管理页热更新比改代码重部署效率高。
 */
import { useEffect, useState } from 'react'
import {
  List,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Tag,
  Typography,
  Card,
  message,
  Popconfirm,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import api from '@/services/api'

const { Title, Text } = Typography
const { TextArea } = Input

const SCENE_MAP: Record<string, { label: string; color: string }> = {
  outpatient: { label: '门诊病历生成', color: 'blue' },
  admission_note: { label: '入院记录生成', color: 'geekblue' },
  first_course_record: { label: '首次病程生成', color: 'geekblue' },
  course_record: { label: '日常病程生成', color: 'geekblue' },
  senior_round: { label: '上级查房生成', color: 'geekblue' },
  discharge_record: { label: '出院记录生成', color: 'geekblue' },
  polish: { label: '病历润色', color: 'green' },
  qc: { label: '质控分析', color: 'orange' },
  inquiry: { label: '追问建议', color: 'purple' },
  exam: { label: '检查建议', color: 'cyan' },
}

export default function PromptsPage() {
  const [prompts, setPrompts] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editPrompt, setEditPrompt] = useState<any>(null)
  const [form] = Form.useForm()

  const loadPrompts = async () => {
    setLoading(true)
    try {
      const data: any = await api.get('/admin/prompts')
      setPrompts(data.items || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPrompts()
  }, [])

  const openCreate = () => {
    setEditPrompt(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (p: any) => {
    setEditPrompt(p)
    form.setFieldsValue(p)
    setModalOpen(true)
  }

  const handleSubmit = async (values: any) => {
    try {
      if (editPrompt) {
        await api.put(`/admin/prompts/${editPrompt.id}`, values)
        message.success('更新成功')
      } else {
        await api.post('/admin/prompts', values)
        message.success('创建成功')
      }
      setModalOpen(false)
      loadPrompts()
    } catch {
      message.error('操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/admin/prompts/${id}`)
      message.success('已删除')
      loadPrompts()
    } catch {
      message.error('删除失败')
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            Prompt 模板管理
          </Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            管理 AI 各功能使用的提示词模板，激活后覆盖系统默认提示词，立即生效。模板中可使用{' '}
            {`{chief_complaint}`}、{`{history_present_illness}`}、{`{past_history}`}、
            {`{allergy_history}`}、{`{physical_exam}`}、{`{initial_impression}`}、
            {`{personal_history}`} 占位符
          </Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建模板
        </Button>
      </div>
      <List
        loading={loading}
        dataSource={prompts}
        renderItem={(item: any) => {
          const scene = SCENE_MAP[item.scene] || { label: item.scene, color: 'default' }
          return (
            <Card
              style={{ marginBottom: 12 }}
              size="small"
              title={
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Tag color={scene.color}>{scene.label}</Tag>
                  <span>{item.name}</span>
                  <Tag>{item.version}</Tag>
                  {!item.is_active && <Tag color="default">已停用</Tag>}
                </div>
              }
              extra={
                <span style={{ display: 'flex', gap: 8 }}>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(item)}>
                    编辑
                  </Button>
                  <Popconfirm title="确认删除该模板？" onConfirm={() => handleDelete(item.id)}>
                    <Button size="small" danger icon={<DeleteOutlined />}>
                      删除
                    </Button>
                  </Popconfirm>
                </span>
              }
            >
              <pre
                style={{
                  fontSize: 12,
                  color: '#666',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                  maxHeight: 80,
                  overflow: 'hidden',
                  margin: 0,
                  background: '#f5f5f5',
                  padding: 8,
                  borderRadius: 4,
                }}
              >
                {item.content?.slice(0, 200)}
                {item.content?.length > 200 ? '...' : ''}
              </pre>
            </Card>
          )
        }}
        locale={{ emptyText: '暂无Prompt模板，点击「新建模板」添加' }}
      />
      <Modal
        title={editPrompt ? '编辑 Prompt 模板' : '新建 Prompt 模板'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        okText="确认"
        cancelText="取消"
        width={640}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item label="模板名称" name="name" rules={[{ required: true }]}>
            <Input placeholder="如：门诊病历生成-v2" />
          </Form.Item>
          <Form.Item label="应用场景" name="scene" rules={[{ required: true }]}>
            <Select
              options={Object.entries(SCENE_MAP).map(([v, s]) => ({ value: v, label: s.label }))}
            />
          </Form.Item>
          <Form.Item label="版本号" name="version">
            <Input placeholder="如：v1、v2" style={{ width: 120 }} />
          </Form.Item>
          <Form.Item label="Prompt 内容" name="content" rules={[{ required: true }]}>
            <TextArea
              rows={12}
              placeholder="在此输入完整的 Prompt 模板内容，支持 {变量名} 占位符"
              style={{ fontFamily: 'monospace', fontSize: 12 }}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
