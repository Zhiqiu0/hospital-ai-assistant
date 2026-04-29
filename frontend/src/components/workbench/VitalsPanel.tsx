/**
 * 生命体征录入面板（components/workbench/VitalsPanel.tsx）
 *
 * 提供结构化生命体征录入和历史查看，支持：
 *   - 快速录入当前体征（体温/脉搏/呼吸/血压/血氧）
 *   - 查看历史体征记录列表
 */
import { useState, useEffect, useCallback } from 'react'
import { Button, Form, InputNumber, message, Table, Typography, Divider } from 'antd'
import { PlusOutlined, HistoryOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '@/services/api'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'

const { Text } = Typography

interface VitalRecord {
  id: string
  recorded_at: string
  temperature?: number
  pulse?: number
  respiration?: number
  bp_systolic?: number
  bp_diastolic?: number
  spo2?: number
  weight?: number
  height?: number
  recorded_by?: string
}

export default function VitalsPanel() {
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const [form] = Form.useForm()
  const [history, setHistory] = useState<VitalRecord[]>([])
  const [saving, setSaving] = useState(false)
  const [showHistory, setShowHistory] = useState(false)

  const fetchHistory = useCallback(async () => {
    if (!currentEncounterId) return
    try {
      const res = (await api.get(`/encounters/${currentEncounterId}/vitals`)) as any
      setHistory(res.items || [])
    } catch {
      setHistory([])
    }
  }, [currentEncounterId])

  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  const handleSave = async (values: any) => {
    if (!currentEncounterId) return
    // 确保至少填了一项
    const hasAnyValue = Object.values(values).some(v => v != null && v !== '')
    if (!hasAnyValue) {
      message.warning('请至少填写一项体征数值')
      return
    }
    setSaving(true)
    try {
      await api.post(`/encounters/${currentEncounterId}/vitals`, values)
      message.success({ content: '体征已记录', duration: 1.5 })
      form.resetFields()
      fetchHistory()
    } catch {
      message.error('保存失败，请重试')
    } finally {
      setSaving(false)
    }
  }

  const columns = [
    {
      title: '时间',
      dataIndex: 'recorded_at',
      width: 100,
      render: (v: string) => <Text style={{ fontSize: 11 }}>{dayjs(v).format('MM-DD HH:mm')}</Text>,
    },
    {
      title: 'T',
      dataIndex: 'temperature',
      width: 52,
      render: (v?: number) =>
        v != null ? (
          <Text style={{ fontSize: 11, color: v > 37.5 ? '#dc2626' : 'inherit' }}>{v}℃</Text>
        ) : (
          '—'
        ),
    },
    {
      title: 'P',
      dataIndex: 'pulse',
      width: 48,
      render: (v?: number) => (v != null ? <Text style={{ fontSize: 11 }}>{v}</Text> : '—'),
    },
    {
      title: 'R',
      dataIndex: 'respiration',
      width: 44,
      render: (v?: number) => (v != null ? <Text style={{ fontSize: 11 }}>{v}</Text> : '—'),
    },
    {
      title: 'BP',
      width: 72,
      render: (_: any, row: VitalRecord) =>
        row.bp_systolic != null ? (
          <Text style={{ fontSize: 11 }}>
            {row.bp_systolic}/{row.bp_diastolic}
          </Text>
        ) : (
          '—'
        ),
    },
    {
      title: 'SpO₂',
      dataIndex: 'spo2',
      width: 56,
      render: (v?: number) =>
        v != null ? (
          <Text style={{ fontSize: 11, color: v < 95 ? '#dc2626' : 'inherit' }}>{v}%</Text>
        ) : (
          '—'
        ),
    },
  ]

  return (
    <div style={{ padding: '12px 14px' }}>
      <Text style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>生命体征</Text>

      {/* 录入表单 */}
      <Form
        form={form}
        onFinish={handleSave}
        layout="inline"
        size="small"
        style={{ marginTop: 12 }}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: '6px 10px',
            width: '100%',
          }}
        >
          <Form.Item name="temperature" style={{ margin: 0 }}>
            <InputNumber
              placeholder="体温 °C"
              min={35}
              max={42}
              step={0.1}
              style={{ width: '100%' }}
              suffix="°C"
            />
          </Form.Item>
          <Form.Item name="pulse" style={{ margin: 0 }}>
            <InputNumber
              placeholder="脉搏 次/min"
              min={20}
              max={250}
              style={{ width: '100%' }}
              suffix="次"
            />
          </Form.Item>
          <Form.Item name="respiration" style={{ margin: 0 }}>
            <InputNumber
              placeholder="呼吸 次/min"
              min={5}
              max={60}
              style={{ width: '100%' }}
              suffix="次"
            />
          </Form.Item>
          <Form.Item name="spo2" style={{ margin: 0 }}>
            <InputNumber
              placeholder="SpO₂ %"
              min={50}
              max={100}
              style={{ width: '100%' }}
              suffix="%"
            />
          </Form.Item>
          <Form.Item name="bp_systolic" style={{ margin: 0 }}>
            <InputNumber
              placeholder="收缩压 mmHg"
              min={50}
              max={250}
              style={{ width: '100%' }}
              suffix="收"
            />
          </Form.Item>
          <Form.Item name="bp_diastolic" style={{ margin: 0 }}>
            <InputNumber
              placeholder="舒张压 mmHg"
              min={30}
              max={150}
              style={{ width: '100%' }}
              suffix="舒"
            />
          </Form.Item>
        </div>
        <Button
          type="primary"
          htmlType="submit"
          loading={saving}
          icon={<PlusOutlined />}
          size="small"
          block
          style={{ marginTop: 8, background: '#059669', borderColor: '#059669' }}
        >
          记录体征
        </Button>
      </Form>

      {/* 历史记录切换 */}
      <Divider style={{ margin: '10px 0' }} />
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
        }}
        onClick={() => setShowHistory(v => !v)}
      >
        <Text style={{ fontSize: 12, color: 'var(--text-3)' }}>
          <HistoryOutlined /> 历史体征（{history.length} 条）
        </Text>
        <Text style={{ fontSize: 11, color: 'var(--text-4)' }}>
          {showHistory ? '收起' : '展开'}
        </Text>
      </div>

      {showHistory && history.length > 0 && (
        <Table
          dataSource={history}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={false}
          scroll={{ y: 200 }}
          style={{ marginTop: 8 }}
        />
      )}
    </div>
  )
}
