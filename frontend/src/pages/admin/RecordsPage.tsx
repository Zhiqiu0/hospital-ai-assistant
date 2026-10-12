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
import { useCallback, useEffect, useRef, useState } from 'react'
import { Table, Tag, Typography, Button, Space, Input } from 'antd'
import { message } from '@/services/messageBridge'
import { SearchOutlined, EyeOutlined, EditOutlined } from '@ant-design/icons'
import api from '@/services/api'
import RecordViewModal from '@/components/workbench/RecordViewModal'
import RecordRevisionModal from './RecordRevisionModal'
import { genderCode, genderText } from '@/utils/gender'
// 文书类型标签统一用 recordExport 的完整表（2026-09-16 终检收口）：
// 本地手抄表只有 3 类，日常病程/急诊等 7 类在管理端列表里直接裸显英文键
// （course_record）。那份表有契约测试锁着"与后端枚举一一对应"，跟着它走。
import { RECORD_TYPE_LABEL } from '@/utils/recordExport'

const { Title, Text } = Typography

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
  // 只接纳最新请求；筛选切换、修订刷新和卸载都会淘汰旧响应。
  const requestId = useRef(0)
  const [refreshVersion, setRefreshVersion] = useState(0)
  const [viewRecord, setViewRecord] = useState<RecordRow | null>(null)

  // ── 修订病历（2026-05-03 加）─────────────────────────────────────────────
  // 已签发病历是法律文件，必须留痕修改：后端创建新 RecordVersion，旧版本保留。
  // 修订理由必填，写入 audit_logs 永久可查。
  const [reviseRecord, setReviseRecord] = useState<RecordRow | null>(null)
  // 独立弹窗按文书主键重新挂载，隔离正文编辑、诊断核对与旧提交响应。
  const openRevise = (record: RecordRow) => setReviseRecord(record)

  const loadRecords = useCallback(async () => {
    const id = ++requestId.current
    setLoading(true)
    try {
      // 由服务端在分页前匹配姓名，支持当前页之外的病历。
      const params = new URLSearchParams({
        page: String(page),
        page_size: '20',
        search: search.trim(),
      })
      const data = (await api.get(`/admin/records?${params}`)) as {
        items?: RecordRow[]
        total?: number
      }
      if (id !== requestId.current) return
      setRecords(data.items || [])
      setTotal(data.total || 0)
    } catch {
      if (id === requestId.current) message.error('病历列表加载失败，请重试')
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [page, search])

  useEffect(() => {
    void loadRecords()
    return () => {
      requestId.current += 1
    }
  }, [loadRecords, refreshVersion])

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
              color={genderCode(row.patient_gender) === 'male' ? 'blue' : 'pink'}
              style={{ fontSize: 11, margin: 0 }}
            >
              {genderText(row.patient_gender, '未知')}
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
          // 改搜索词时从第一页重新查询，避免沿用原列表的页码。
          onChange={e => {
            setSearch(e.target.value)
            setPage(1)
          }}
          maxLength={100}
          style={{ width: 220 }}
          allowClear
        />
      </div>

      <Table
        columns={columns}
        dataSource={records}
        rowKey="id"
        loading={loading}
        pagination={{
          total,
          pageSize: 20,
          current: page,
          onChange: p => {
            setPage(p)
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

      {reviseRecord && (
        <RecordRevisionModal
          key={reviseRecord.id}
          record={reviseRecord}
          onClose={() => setReviseRecord(null)}
          onSaved={() => setRefreshVersion(version => version + 1)}
        />
      )}
    </div>
  )
}
