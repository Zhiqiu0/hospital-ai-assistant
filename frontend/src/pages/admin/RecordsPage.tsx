/**
 * 病历管理页（pages/admin/RecordsPage.tsx）
 *
 * 管理员查看全院所有病历，调用 GET /admin/records（分页+筛选）：
 *   - 筛选：状态（draft/submitted）、病历类型、科室、医生、时间范围
 *   - 列：患者、就诊类型、签发医生、科室、版本、状态、时间
 *   - 「查看」：弹出 RecordViewModal 展示完整内容
 *   - 「导出」：触发 Word 导出（recordExport.ts）
 *
 * 后端 JOIN 说明：
 *   /admin/records 接口 JOIN patient + user + department，
 *   一次返回所有关联信息，无需前端二次请求。
 */
import { useEffect, useState } from 'react'
import { Table, Tag, Typography, Modal, Button, Space, Input } from 'antd'
import { message } from '@/services/messageBridge'
import { SearchOutlined, EyeOutlined, EditOutlined } from '@ant-design/icons'
import api from '@/services/api'
import RecordViewModal from '@/components/workbench/RecordViewModal'

const { TextArea } = Input

const { Title, Text } = Typography

const RECORD_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊病历',
  admission_note: '入院记录',
  first_course_record: '首次病程',
}

/** 病历列表行——后端 /admin/records 把 patient/doctor/department JOIN 后扁平返回。
 *  2026-05-16 加：病案首页所需字段（patient_snapshot 优先 + 当前 patient 字段做 fallback）。
 */
interface RecordRow {
  id: string
  record_type: string
  content?: string
  content_preview?: string
  patient_name?: string
  patient_gender?: string
  doctor_name?: string
  submitted_at?: string | null
  // 病案首页字段（与 RecordViewModal.ViewableRecord 对齐）
  patient_snapshot?: Record<string, unknown> | null
  patient_no?: string | null
  patient_phone?: string | null
  patient_id_card?: string | null
  patient_address?: string | null
  patient_ethnicity?: string | null
  patient_marital_status?: string | null
  patient_occupation?: string | null
  patient_workplace?: string | null
  patient_contact_name?: string | null
  patient_contact_phone?: string | null
  patient_contact_relation?: string | null
  patient_blood_type?: string | null
  patient_birth_date?: string | null
  visit_type?: string | null
  visit_time?: string | null
  bed_no?: string | null
  department_name?: string | null
  // 兼容 RecordViewModal.ViewableRecord 的 index signature——
  // RecordViewModal 用 [key: string]: unknown 透传未消费字段
  [key: string]: unknown
}

export default function RecordsPage() {
  const [records, setRecords] = useState<RecordRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [viewRecord, setViewRecord] = useState<RecordRow | null>(null)

  // ── 修订病历（2026-05-03 加）─────────────────────────────────────────────
  // 已签发病历是法律文件，必须留痕修改：后端创建新 RecordVersion，旧版本保留。
  // 修订理由必填，写入 audit_logs 永久可查。
  const [reviseRecord, setReviseRecord] = useState<RecordRow | null>(null)
  const [reviseContent, setReviseContent] = useState('')
  const [reviseReason, setReviseReason] = useState('')
  const [reviseSubmitting, setReviseSubmitting] = useState(false)

  const openRevise = (record: RecordRow) => {
    setReviseRecord(record)
    setReviseContent(record.content || '')
    setReviseReason('')
  }

  const closeRevise = () => {
    setReviseRecord(null)
    setReviseContent('')
    setReviseReason('')
  }

  const submitRevise = async () => {
    if (!reviseRecord) return
    if (!reviseReason.trim()) {
      message.warning('请填写修订理由')
      return
    }
    if (!reviseContent.trim()) {
      message.warning('病历内容不能为空')
      return
    }
    setReviseSubmitting(true)
    try {
      await api.post(`/admin/records/${reviseRecord.id}/revise`, {
        content: reviseContent,
        revise_reason: reviseReason.trim(),
      })
      message.success('病历已修订，原版本保留供审计')
      closeRevise()
      // 刷新列表（让 content_preview 更新到新版本）
      loadRecords()
    } catch (e: unknown) {
      const detail = (e as { detail?: string })?.detail
      message.error(detail || '修订失败')
    } finally {
      setReviseSubmitting(false)
    }
  }

  const loadRecords = async (p = page) => {
    setLoading(true)
    try {
      const data = (await api.get(`/admin/records?page=${p}&page_size=20`)) as {
        items?: RecordRow[]
        total?: number
      }
      setRecords(data.items || [])
      setTotal(data.total || 0)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRecords()
    // 只挂载时加载一次；setState 在 effect 里是预期路径
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const filtered = search
    ? records.filter(r => r.patient_name?.includes(search) || r.doctor_name?.includes(search))
    : records

  const columns = [
    {
      title: '患者',
      dataIndex: 'patient_name',
      key: 'patient_name',
      render: (name: string, row: RecordRow) => (
        <Space size={4}>
          <Text strong>{name}</Text>
          {row.patient_gender && (
            <Tag
              color={row.patient_gender === 'male' ? 'blue' : 'pink'}
              style={{ fontSize: 11, margin: 0 }}
            >
              {row.patient_gender === 'male' ? '男' : '女'}
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: '病历类型',
      dataIndex: 'record_type',
      key: 'record_type',
      render: (v: string) => <Tag color="blue">{RECORD_TYPE_LABEL[v] || v}</Tag>,
    },
    {
      title: '主治医生',
      dataIndex: 'doctor_name',
      key: 'doctor_name',
      render: (name: string) => <Text>{name}</Text>,
    },
    {
      title: '签发时间',
      dataIndex: 'submitted_at',
      key: 'submitted_at',
      render: (v: string) => (v ? new Date(v).toLocaleString('zh-CN') : '-'),
      sorter: (a: RecordRow, b: RecordRow) =>
        new Date(a.submitted_at || '').getTime() - new Date(b.submitted_at || '').getTime(),
      defaultSortOrder: 'descend' as const,
    },
    {
      title: '内容摘要',
      dataIndex: 'content_preview',
      key: 'content_preview',
      ellipsis: true,
      render: (v: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {v || '—'}
        </Text>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: RecordRow) => (
        <Space>
          <Button
            size="small"
            type="link"
            icon={<EyeOutlined />}
            onClick={() => setViewRecord(record)}
          >
            查看
          </Button>
          <Button
            size="small"
            type="link"
            icon={<EditOutlined />}
            onClick={() => openRevise(record)}
          >
            修订
          </Button>
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
          marginBottom: 20,
        }}
      >
        <div>
          <Title level={4} style={{ margin: 0, color: 'var(--text-1)' }}>
            病历管理
          </Title>
          <Text type="secondary" style={{ fontSize: 13 }}>
            所有已签发病历（管理员可见全部，医生仅见本人）
          </Text>
        </div>
        <Input
          prefix={<SearchOutlined style={{ color: 'var(--text-4)' }} />}
          placeholder="搜索患者姓名或医生"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ width: 220 }}
          allowClear
        />
      </div>

      <Table
        columns={columns}
        dataSource={filtered}
        rowKey="id"
        loading={loading}
        pagination={{
          total,
          pageSize: 20,
          current: page,
          onChange: p => {
            setPage(p)
            loadRecords(p)
          },
          showTotal: t => `共 ${t} 份病历`,
        }}
        style={{ background: 'var(--surface)', borderRadius: 10 }}
      />

      {/* 复用工作台 RecordViewModal——管理员视图也有完整"病案首页"+打印按钮。
          之前是 admin 页面自己 inline 写的简版（只有正文+签发时间），改完之后
          所有"查看病历"入口的首页/样式/打印逻辑统一在一个组件里。 */}
      <RecordViewModal
        record={viewRecord}
        onClose={() => setViewRecord(null)}
        accentColor="#2563eb"
        tagColor="blue"
        recordTypeLabel={t => RECORD_TYPE_LABEL[t] || t}
        showPrint
      />

      {/* 修订病历弹窗：留痕式修改（创建新 RecordVersion，旧版本保留供审计） */}
      <Modal
        title={
          reviseRecord && (
            <Space>
              <EditOutlined style={{ color: '#dc2626' }} />
              <span>修订病历</span>
              <Tag color="default">{reviseRecord.patient_name}</Tag>
              <Tag color="blue">
                {RECORD_TYPE_LABEL[reviseRecord.record_type] || reviseRecord.record_type}
              </Tag>
            </Space>
          )
        }
        open={!!reviseRecord}
        onCancel={closeRevise}
        okText="确认修订并留痕"
        cancelText="取消"
        okButtonProps={{ loading: reviseSubmitting, danger: true }}
        onOk={submitRevise}
        width={760}
        destroyOnHidden
      >
        <div
          style={{
            padding: '8px 10px',
            background: '#fef9c3',
            border: '1px solid #fde047',
            borderRadius: 6,
            marginBottom: 12,
            fontSize: 12,
            color: '#854d0e',
          }}
        >
          ⚠️
          已签发病历是法律文件。修订将创建新版本，原版本永久保留供审计；操作人、时间、修订理由会写入审计日志。
        </div>

        <div style={{ marginBottom: 12 }}>
          <Text strong style={{ fontSize: 13 }}>
            修订理由 <Text type="danger">*</Text>
          </Text>
          <TextArea
            value={reviseReason}
            onChange={e => setReviseReason(e.target.value)}
            rows={2}
            placeholder="请说明本次修订原因（如：医生提交后发现 XX 字段有误，需更正）"
            maxLength={500}
            showCount
            style={{ marginTop: 6 }}
          />
        </div>

        <div>
          <Text strong style={{ fontSize: 13 }}>
            病历正文（修订后）
          </Text>
          <TextArea
            value={reviseContent}
            onChange={e => setReviseContent(e.target.value)}
            rows={20}
            style={{
              marginTop: 6,
              fontFamily: "'PingFang SC', 'Microsoft YaHei', monospace",
              fontSize: 13,
              lineHeight: 1.8,
            }}
          />
        </div>
      </Modal>
    </div>
  )
}
