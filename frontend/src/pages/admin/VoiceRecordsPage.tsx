/**
 * 语音记录管理页（pages/admin/VoiceRecordsPage.tsx）
 *
 * 查看所有医生的语音录入记录，调用 GET /admin/voice-records（分页）：
 *   - 筛选：医生、科室、时间范围、处理状态
 *   - 列：录音时长、转写文本（截断显示）、语言、处理时长、创建时间
 *   - 「详情」Drawer：展示完整转写文本、关联接诊、生成的病历字段
 *   - 状态 Tag：pending/processing/completed/failed
 *
 * 业务价值：
 *   - 监控 ASR 转写质量，发现系统性识别错误
 *   - 统计语音功能使用率，为提示词优化提供依据
 *   - 排查转写失败的具体音频（failed 状态可下载原始音频）
 */
import { useEffect, useState } from 'react'
import { Table, Input, Select, Space, Tag, Typography, Button, Drawer, Descriptions } from 'antd'
import { AudioOutlined, SearchOutlined } from '@ant-design/icons'
import api from '@/services/api'
import { useAuthStore } from '@/store/authStore'

const { Text } = Typography

const STATUS_COLOR: Record<string, string> = {
  uploaded: 'blue',
  structured: 'green',
}
const STATUS_LABEL: Record<string, string> = {
  uploaded: '已上传',
  structured: '已整理',
}
const VISIT_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊',
  inpatient: '住院',
  emergency: '急诊',
}

export default function VoiceRecordsPage() {
  const { token } = useAuthStore()
  const [items, setItems] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState<string | undefined>()
  const [page, setPage] = useState(1)
  const [detail, setDetail] = useState<any>(null)

  const loadData = async (p = page) => {
    setLoading(true)
    try {
      const params: any = { page: p, page_size: 20 }
      if (keyword) params.keyword = keyword
      if (status) params.status = status
      const data: any = await api.get('/admin/voice-records', { params })
      setItems(data.items || [])
      setTotal(data.total || 0)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData(1)
  }, [status])

  const handleSearch = () => {
    setPage(1)
    loadData(1)
  }

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 160,
      render: (v: string) => (v ? new Date(v).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '医生',
      dataIndex: 'doctor_name',
      width: 100,
      render: (v: string) => v || '-',
    },
    {
      title: '类型',
      dataIndex: 'visit_type',
      width: 70,
      render: (v: string) => <Tag>{VISIT_TYPE_LABEL[v] || v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'}>{STATUS_LABEL[v] || v}</Tag>,
    },
    {
      title: '有录音',
      dataIndex: 'has_audio',
      width: 70,
      render: (v: boolean) =>
        v ? (
          <Tag color="blue" icon={<AudioOutlined />}>
            有
          </Tag>
        ) : (
          <Tag color="default">无</Tag>
        ),
    },
    {
      title: '转写摘要',
      dataIndex: 'transcript_summary',
      ellipsis: true,
      render: (v: string, record: any) => (
        <Text style={{ fontSize: 12 }} type="secondary">
          {v || record.transcript_preview || '（暂无）'}
        </Text>
      ),
    },
    {
      title: '操作',
      width: 80,
      render: (_: any, record: any) => (
        <Button size="small" type="link" onClick={() => setDetail(record)}>
          详情
        </Button>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
        <Text strong style={{ fontSize: 16 }}>
          语音记录
        </Text>
        <div style={{ flex: 1 }} />
        <Input
          prefix={<SearchOutlined />}
          placeholder="搜索转写内容"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          onPressEnter={handleSearch}
          style={{ width: 220 }}
          allowClear
        />
        <Select
          placeholder="状态筛选"
          value={status}
          onChange={v => {
            setStatus(v)
            setPage(1)
          }}
          allowClear
          style={{ width: 120 }}
          options={[
            { value: 'uploaded', label: '已上传' },
            { value: 'structured', label: '已整理' },
          ]}
        />
        <Button type="primary" onClick={handleSearch}>
          搜索
        </Button>
      </div>

      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{
          current: page,
          total,
          pageSize: 20,
          onChange: p => {
            setPage(p)
            loadData(p)
          },
          showTotal: t => `共 ${t} 条`,
        }}
        size="small"
      />

      <Drawer title="语音记录详情" open={!!detail} onClose={() => setDetail(null)} width={520}>
        {detail && (
          <Space direction="vertical" style={{ width: '100%' }} size={16}>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="记录 ID">
                <Text copyable style={{ fontSize: 12 }}>
                  {detail.id}
                </Text>
              </Descriptions.Item>
              <Descriptions.Item label="时间">
                {detail.created_at ? new Date(detail.created_at).toLocaleString('zh-CN') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="医生">{detail.doctor_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="就诊类型">
                {VISIT_TYPE_LABEL[detail.visit_type] || detail.visit_type || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="接诊ID">
                <Text style={{ fontSize: 12 }}>{detail.encounter_id || '-'}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_COLOR[detail.status]}>
                  {STATUS_LABEL[detail.status] || detail.status}
                </Tag>
              </Descriptions.Item>
            </Descriptions>

            {detail.has_audio && (
              <div>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                  音频播放
                </Text>
                <audio
                  controls
                  src={`/api/v1/ai/voice-records/${detail.id}/audio?token=${token}`}
                  style={{ width: '100%' }}
                />
              </div>
            )}

            {detail.transcript_summary && (
              <div>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                  对话摘要
                </Text>
                <div
                  style={{
                    background: 'var(--surface-2)',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    padding: '10px 14px',
                    fontSize: 13,
                    lineHeight: 1.7,
                  }}
                >
                  {detail.transcript_summary}
                </div>
              </div>
            )}

            {detail.transcript_preview && (
              <div>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                  转写文本（前100字）
                </Text>
                <div
                  style={{
                    background: 'var(--surface-2)',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    padding: '10px 14px',
                    fontSize: 13,
                    lineHeight: 1.7,
                    color: 'var(--text-2)',
                  }}
                >
                  {detail.transcript_preview}
                  {detail.transcript_preview?.length >= 100 && '…'}
                </div>
              </div>
            )}
          </Space>
        )}
      </Drawer>
    </div>
  )
}
