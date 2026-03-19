import { useEffect, useState } from 'react'
import { Button, Card, Form, Input, InputNumber, Select, Space, Switch, Table, Tag, Typography, message } from 'antd'
import api from '@/services/api'

const { Title, Text } = Typography

const SCENE_LABELS: Record<string, string> = {
  generate: '病历生成',
  polish: '病历润色',
  qc: '质控分析',
  inquiry: '问诊建议/诊断建议',
  exam: '检查建议',
}

const MODEL_OPTIONS = [
  { value: 'deepseek-chat', label: 'DeepSeek Chat' },
  { value: 'deepseek-reasoner', label: 'DeepSeek Reasoner' },
]

export default function ModelConfigsPage() {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [savingScene, setSavingScene] = useState<string | null>(null)

  const loadData = async () => {
    setLoading(true)
    try {
      const data: any = await api.get('/admin/model-configs')
      setItems(Array.isArray(data) ? data : [])
    } catch {
      message.error('加载模型配置失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadData() }, [])

  const handleSave = async (scene: string, values: any) => {
    setSavingScene(scene)
    try {
      await api.put(`/admin/model-configs/${scene}`, values)
      message.success(`${SCENE_LABELS[scene] || scene}配置已保存`)
      loadData()
    } catch {
      message.error('保存失败')
    } finally {
      setSavingScene(null)
    }
  }

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>模型配置</Title>
        <Text type="secondary" style={{ fontSize: 12 }}>
          按场景配置模型、温度和最大输出长度；保存后立即影响对应 AI 能力。
        </Text>
      </div>

      <Table
        rowKey="scene"
        loading={loading}
        pagination={false}
        dataSource={items}
        columns={[
          {
            title: '场景',
            dataIndex: 'scene',
            width: 180,
            render: (scene: string) => (
              <Space direction="vertical" size={2}>
                <Tag color="blue" style={{ marginRight: 0 }}>{SCENE_LABELS[scene] || scene}</Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>{scene}</Text>
              </Space>
            ),
          },
          {
            title: '配置',
            render: (_: any, record: any) => (
              <Card size="small" bodyStyle={{ padding: 12 }}>
                <Form
                  layout="inline"
                  initialValues={record}
                  onFinish={(values) => handleSave(record.scene, values)}
                >
                  <Form.Item name="model_name" label="模型" rules={[{ required: true }]}>
                    <Select style={{ width: 180 }} options={MODEL_OPTIONS} />
                  </Form.Item>
                  <Form.Item name="temperature" label="温度" rules={[{ required: true }]}>
                    <InputNumber min={0} max={2} step={0.1} style={{ width: 100 }} />
                  </Form.Item>
                  <Form.Item name="max_tokens" label="最大Token" rules={[{ required: true }]}>
                    <InputNumber min={256} max={16384} step={256} style={{ width: 120 }} />
                  </Form.Item>
                  <Form.Item name="is_active" label="启用" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <Form.Item name="description" label="说明">
                    <Input style={{ width: 220 }} placeholder="场景用途说明" />
                  </Form.Item>
                  <Form.Item>
                    <Button type="primary" htmlType="submit" loading={savingScene === record.scene}>保存</Button>
                  </Form.Item>
                </Form>
              </Card>
            ),
          },
        ]}
      />
    </div>
  )
}
