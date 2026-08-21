/**
 * 质控员复核工作台（pages/QcWorkbenchPage.tsx，2026-08-21 阶段4）
 *
 * 病案首页质控方案三级体系中"科室质控员 24h 复核签字"的工作界面：
 * 待复核清单（已签发文书，科室质控员自动限本科室）→ 查看全文 →
 * 复核通过 / 退回整改（必填意见）。所有查阅与结论均写审计日志。
 */
import { useCallback, useEffect, useState } from 'react'
import { Button, Drawer, Input, Layout, Space, Table, Tabs, Tag, Typography } from 'antd'
import QcStatsPanel from './qc/QcStatsPanel'
import { CheckOutlined, LogoutOutlined, RollbackOutlined, SafetyOutlined } from '@ant-design/icons'
import { message } from '@/services/messageBridge'
import api from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import { useNavigate } from 'react-router-dom'

const { Header, Content } = Layout

/** 后端 /qc/review-queue 行 */
interface QueueItem {
  record_id: string
  encounter_id: string
  record_type: string
  record_no?: string | null
  patient_name: string
  visit_type: string
  submitted_at: string | null
  discharged_at: string | null
}

interface ReviewEntry {
  reviewer_name: string
  conclusion: string
  comment: string | null
  created_at: string
}

interface RecordDetail {
  record_id: string
  record_type: string
  content: string
  patient: { name: string; gender: string }
  submitted_at: string | null
  reviews: ReviewEntry[]
}

const TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊病历',
  emergency: '急诊病历',
  admission_note: '入院记录',
  first_course_record: '首次病程',
  course_record: '日常病程',
  senior_round: '上级查房',
  pre_op_summary: '术前小结',
  op_record: '手术记录',
  post_op_record: '术后病程',
  discharge_record: '出院记录',
}

export default function QcWorkbenchPage() {
  const { user, clearAuth } = useAuthStore()
  const navigate = useNavigate()
  const [items, setItems] = useState<QueueItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<RecordDetail | null>(null)
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(async (p: number) => {
    setLoading(true)
    try {
      const res = (await api.get(`/qc/review-queue?page=${p}&page_size=20`)) as unknown as {
        total: number
        items: QueueItem[]
      }
      setItems(res.items || [])
      setTotal(res.total || 0)
    } catch {
      message.error('加载待复核清单失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(page)
  }, [page, load])

  const openDetail = async (recordId: string) => {
    try {
      const res = (await api.get(`/qc/records/${recordId}`)) as unknown as RecordDetail
      setDetail(res)
      setComment('')
    } catch {
      message.error('加载病历失败')
    }
  }

  const submit = async (conclusion: 'passed' | 'returned') => {
    if (!detail) return
    if (conclusion === 'returned' && !comment.trim()) {
      message.warning('退回整改必须填写整改意见')
      return
    }
    setSubmitting(true)
    try {
      await api.post('/qc/reviews', {
        medical_record_id: detail.record_id,
        conclusion,
        comment: comment.trim() || null,
      })
      message.success(conclusion === 'passed' ? '复核通过已记录' : '已退回整改')
      setDetail(null)
      load(page)
    } catch {
      message.error('提交复核失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleLogout = async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      /* token 过期时 server 拒绝是正常的，本地照常清 */
    }
    clearAuth()
    navigate('/login')
  }

  return (
    <Layout style={{ height: '100vh', background: 'var(--bg)' }}>
      <Header
        style={{
          background: 'var(--surface)',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 20px',
        }}
      >
        <Space>
          <SafetyOutlined style={{ color: '#0891B2', fontSize: 18 }} />
          <Typography.Text strong>MediScribe 病历复核工作台</Typography.Text>
          <Tag color="cyan">科室质控</Tag>
        </Space>
        <Space>
          <Typography.Text type="secondary">{user?.real_name || user?.username}</Typography.Text>
          <Button type="text" icon={<LogoutOutlined />} onClick={handleLogout} />
        </Space>
      </Header>
      <Content style={{ padding: 16, overflow: 'auto' }}>
        <Tabs
          items={[
            {
              key: 'queue',
              label: '待复核',
              children: (
                <Table<QueueItem>
                  rowKey="record_id"
                  loading={loading}
                  dataSource={items}
                  pagination={{
                    current: page,
                    pageSize: 20,
                    total,
                    onChange: setPage,
                    showTotal: t => `待复核 ${t} 份`,
                  }}
                  columns={[
                    { title: '患者', dataIndex: 'patient_name', width: 120 },
                    {
                      title: '文书',
                      dataIndex: 'record_type',
                      width: 130,
                      render: (v: string, row) =>
                        `${TYPE_LABEL[v] || v}${row.record_no && row.record_no !== '1' ? ` #${row.record_no}` : ''}`,
                    },
                    {
                      title: '签发时间',
                      dataIndex: 'submitted_at',
                      render: (v: string | null) => (v ? v.replace('T', ' ').slice(0, 16) : '—'),
                    },
                    {
                      title: '出院时间（24h 复核时限参考）',
                      dataIndex: 'discharged_at',
                      render: (v: string | null) =>
                        v ? v.replace('T', ' ').slice(0, 16) : '未出院',
                    },
                    {
                      title: '操作',
                      width: 100,
                      render: (_, row) => (
                        <Button size="small" onClick={() => openDetail(row.record_id)}>
                          复核
                        </Button>
                      ),
                    },
                  ]}
                />
              ),
            },
            { key: 'stats', label: '质控统计', children: <QcStatsPanel /> },
          ]}
        />
      </Content>

      <Drawer
        open={!!detail}
        onClose={() => setDetail(null)}
        width={720}
        title={
          detail
            ? `${detail.patient.name} · ${TYPE_LABEL[detail.record_type] || detail.record_type}`
            : ''
        }
      >
        {detail && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
            {detail.reviews.length > 0 && (
              <div
                style={{
                  background: 'var(--surface-2, #f8fafc)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 8,
                  padding: '8px 12px',
                  fontSize: 12,
                }}
              >
                {detail.reviews.map((r, i) => (
                  <div key={i}>
                    {r.created_at.replace('T', ' ').slice(0, 16)} {r.reviewer_name}：
                    <Tag color={r.conclusion === 'passed' ? 'green' : 'orange'}>
                      {r.conclusion === 'passed' ? '通过' : '退回'}
                    </Tag>
                    {r.comment}
                  </div>
                ))}
              </div>
            )}
            <pre
              style={{
                flex: 1,
                overflow: 'auto',
                whiteSpace: 'pre-wrap',
                fontSize: 13,
                lineHeight: 1.7,
                background: 'var(--surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 8,
                padding: 14,
                margin: 0,
              }}
            >
              {detail.content}
            </pre>
            <Input.TextArea
              rows={2}
              value={comment}
              onChange={e => setComment(e.target.value)}
              placeholder="复核意见（退回整改时必填）"
            />
            <Space style={{ justifyContent: 'flex-end', display: 'flex' }}>
              <Button
                danger
                icon={<RollbackOutlined />}
                loading={submitting}
                onClick={() => submit('returned')}
              >
                退回整改
              </Button>
              <Button
                type="primary"
                icon={<CheckOutlined />}
                loading={submitting}
                onClick={() => submit('passed')}
              >
                复核通过
              </Button>
            </Space>
          </div>
        )}
      </Drawer>
    </Layout>
  )
}
