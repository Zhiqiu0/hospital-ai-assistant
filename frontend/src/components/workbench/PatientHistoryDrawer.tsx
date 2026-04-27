/**
 * 患者聚焦型历史病历抽屉（PatientHistoryDrawer.tsx）
 *
 * 两种模式：
 *   1. 固定患者（住院端用）：传 patientId 固定不变，抽屉打开直接看该患者全部病历
 *   2. 可搜索（门诊端"患者档案"入口）：传 searchable=true 不传 patientId，
 *      抽屉顶部显示搜索框，用户输入姓名/病案号检索 → 选中后看该患者全部病历
 *
 * 数据：
 *   - 患者搜索：GET /patients?keyword=
 *   - 病历列表：GET /medical-records/by-patient/{id}
 *
 * Tag 规则（按 visit_type + visit_sequence 双通道识别）：
 *   门诊·初诊(蓝) / 门诊·复诊 N(绿) / 急诊(红) / 第 N 次住院(青)
 */
import { useEffect, useState } from 'react'
import {
  Drawer,
  List,
  Button,
  Space,
  Tag,
  Empty,
  Typography,
  Avatar,
  Spin,
  Input,
} from 'antd'
import {
  FileTextOutlined,
  EyeOutlined,
  UserOutlined,
  IdcardOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import api from '@/services/api'

const { Text } = Typography

interface SelectedPatient {
  id: string
  name: string
  gender?: string
  age?: number | null
  /** 是否有进行中的住院接诊；驱动头部"在院中"绿色标签 */
  hasActiveInpatient?: boolean
  /** 是否曾住过院（含已出院）；不在院 + 有历史 → 显示"已出院"灰色标签 */
  hasAnyInpatientHistory?: boolean
}

interface Props {
  open: boolean
  onClose: () => void
  patientId: string | null
  patientName?: string
  patientGender?: string
  patientAge?: number | null
  /** 开启搜索模式：门诊端点"患者档案"→ 可任意搜患者看档案 */
  searchable?: boolean
  /** 父级传入的"当前患者是否在院"（住院端选中病区患者时一定为 true） */
  patientHasActiveInpatient?: boolean
  onView: (record: any) => void
  recordTypeLabel: (t: string) => string
}

function getSceneTag(visitType?: string, visitSequence?: number): { text: string; color: string } {
  const seq = typeof visitSequence === 'number' && visitSequence >= 1 ? visitSequence : 1
  const suffix = seq === 1 ? '' : `·复诊 ${seq - 1}`
  if (visitType === 'inpatient') {
    return { text: seq === 1 ? '首次住院' : `第 ${seq} 次住院`, color: 'cyan' }
  }
  if (visitType === 'emergency') {
    return { text: `急诊${suffix}`, color: 'red' }
  }
  if (seq === 1) return { text: '门诊·初诊', color: 'blue' }
  return { text: `门诊·复诊 ${seq - 1}`, color: 'green' }
}

export default function PatientHistoryDrawer({
  open,
  onClose,
  patientId,
  patientName,
  patientGender,
  patientAge,
  searchable = false,
  patientHasActiveInpatient,
  onView,
  recordTypeLabel,
}: Props) {
  // 当前选中的患者——固定模式来自 props，搜索模式由内部搜索决定
  const [selected, setSelected] = useState<SelectedPatient | null>(null)
  const [records, setRecords] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  // 搜索模式状态：未选中患者时显示一个可滚动的患者列表 + 顶部搜索框
  // 搜索框是"过滤这个列表"的语义，不是 dropdown autocomplete
  const [searchKeyword, setSearchKeyword] = useState('')
  const [patientList, setPatientList] = useState<any[]>([])
  const [searching, setSearching] = useState(false)

  // props 里的 patientId 改变或抽屉打开时，同步 selected
  useEffect(() => {
    if (!open) {
      // 抽屉关闭时清空搜索模式的临时状态，下次打开是干净的
      if (searchable) {
        setSelected(null)
        setSearchKeyword('')
        setPatientList([])
      }
      return
    }
    if (patientId && patientName) {
      setSelected({
        id: patientId,
        name: patientName,
        gender: patientGender,
        age: patientAge,
        hasActiveInpatient: patientHasActiveInpatient,
      })
    } else if (!searchable) {
      setSelected(null)
    }
  }, [open, patientId, patientName, patientGender, patientAge, searchable, patientHasActiveInpatient])

  // selected 变化时加载病历
  useEffect(() => {
    if (!open || !selected) {
      setRecords([])
      setTotal(0)
      return
    }
    setLoading(true)
    api
      .get(`/medical-records/by-patient/${selected.id}`)
      .then((res: any) => {
        setRecords(res.items || [])
        setTotal(res.total || 0)
      })
      .catch(() => {
        setRecords([])
        setTotal(0)
      })
      .finally(() => setLoading(false))
  }, [open, selected])

  // 搜索/列表加载：抽屉打开 + 搜索模式 + 没选中患者时拉患者列表
  // 关键词为空 → 拉前 50 个（按建档时间倒序，最近建档的医生更可能想点）
  // 关键词非空 → 拉对应过滤结果（防抖 300ms）
  useEffect(() => {
    if (!open || !searchable || selected) {
      // 已选中患者后右侧展示病历列表，不需要再拉患者列表
      return
    }
    const kw = searchKeyword.trim()
    const t = setTimeout(() => {
      setSearching(true)
      api
        .get(`/patients?keyword=${encodeURIComponent(kw)}&page_size=50`)
        .then((res: any) => {
          setPatientList(res?.items || [])
        })
        .catch(() => setPatientList([]))
        .finally(() => setSearching(false))
    }, kw ? 300 : 0)  // 空 keyword 立即拉，有 keyword 防抖 300ms
    return () => clearTimeout(t)
  }, [open, searchable, selected, searchKeyword])

  const handlePickPatient = (p: any) => {
    setSelected({
      id: p.id,
      name: p.name,
      gender: p.gender,
      age: p.age,
      hasActiveInpatient: !!p.has_active_inpatient,
      hasAnyInpatientHistory: !!p.has_any_inpatient_history,
    })
  }

  return (
    <Drawer
      title={
        <Space size={6}>
          <FileTextOutlined style={{ color: '#059669' }} />
          <span>{searchable ? '患者档案查询' : '患者历史病历'}</span>
        </Space>
      }
      placement="right"
      width={520}
      open={open}
      onClose={onClose}
      styles={{ body: { padding: 0 } }}
    >
      {/* 搜索模式 + 未选中：顶部搜索框 + 下方滚动患者列表
          搜索框是"过滤这个列表"语义；空关键词时显示前 50 个（按建档时间倒序）。
          医生记不住名字也可以滚动找。 */}
      {searchable && !selected && (
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
          <Input
            prefix={<SearchOutlined style={{ color: 'var(--text-4)' }} />}
            placeholder="输入姓名 / 病案号 过滤列表"
            allowClear
            size="middle"
            value={searchKeyword}
            onChange={e => setSearchKeyword(e.target.value)}
          />
        </div>
      )}

      {/* 顶部患者身份卡 */}
      {selected ? (
        <div
          style={{
            padding: '14px 20px',
            borderBottom: '1px solid var(--border-subtle)',
            background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <Avatar
            size={44}
            style={{ background: 'linear-gradient(135deg, #065f46, #34d399)', fontSize: 18, flexShrink: 0 }}
          >
            {selected.name?.[0]}
          </Avatar>
          <div style={{ flex: 1, minWidth: 0, lineHeight: 1.4 }}>
            <Space size={6} align="center">
              <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-1)' }}>{selected.name}</span>
              {/* 住院状态标签：在院中（绿）/ 已出院（灰）。
                  仅在 has_active_inpatient 为明确布尔值时显示，undefined 不显示
                  避免老接口/未带字段时误标。 */}
              {/* 三态住院 Tag：
                  active=true                  → 在院中（绿）
                  active=false + history=true  → 已出院（灰）
                  history=false                → 不打 Tag（纯门诊或新患者） */}
              {selected.hasActiveInpatient === true ? (
                <Tag color="green" style={{ margin: 0, fontSize: 10, padding: '0 6px', height: 18, lineHeight: '16px' }}>
                  在院中
                </Tag>
              ) : selected.hasAnyInpatientHistory === true ? (
                <Tag style={{ margin: 0, fontSize: 10, padding: '0 6px', height: 18, lineHeight: '16px', background: '#f3f4f6', color: '#6b7280', border: '1px solid #e5e7eb' }}>
                  已出院
                </Tag>
              ) : null}
            </Space>
            <Space size={6} style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>
              {selected.gender && selected.gender !== 'unknown' && (
                <span>{selected.gender === 'male' ? '男' : '女'}</span>
              )}
              {selected.age != null && <span>{selected.age} 岁</span>}
              <span style={{ fontFamily: 'monospace', color: 'var(--text-4)' }}>
                <IdcardOutlined style={{ marginRight: 2 }} />
                {selected.id.slice(-6).toUpperCase()}
              </span>
            </Space>
            <div style={{ fontSize: 11, color: 'var(--text-4)', marginTop: 4 }}>
              共 <Text strong style={{ color: '#059669' }}>{total}</Text> 份已签发病历
            </div>
          </div>
          {searchable && (
            <Button size="small" type="text" onClick={() => setSelected(null)} style={{ color: '#059669' }}>
              换患者
            </Button>
          )}
        </div>
      ) : null}

      {/* 未选中患者：搜索模式显示患者列表，非搜索模式显示空态提示 */}
      {!selected && searchable ? (
        <div style={{ padding: '8px 12px' }}>
          {searching && patientList.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32 }}><Spin size="small" /></div>
          ) : patientList.length === 0 ? (
            <Empty description={searchKeyword ? '未找到匹配患者' : '暂无患者'} style={{ padding: '40px 0' }} image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            patientList.map((p: any) => (
              <div
                key={p.id}
                onClick={() => handlePickPatient(p)}
                style={{
                  padding: '10px 12px',
                  marginBottom: 6,
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  transition: 'all 0.15s',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.background = 'var(--surface-2)'
                  e.currentTarget.style.borderColor = '#86efac'
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.background = 'var(--surface)'
                  e.currentTarget.style.borderColor = 'var(--border)'
                }}
              >
                <Avatar size={32} style={{ background: '#0891B2', flexShrink: 0 }}>{p.name?.[0]}</Avatar>
                <div style={{ flex: 1, minWidth: 0, lineHeight: 1.4 }}>
                  <Space size={6} align="center">
                    <span style={{ fontSize: 13, fontWeight: 600 }}>{p.name}</span>
                    {/* 三态住院 Tag（与抽屉头部、复诊搜索保持一致） */}
                    {p.has_active_inpatient ? (
                      <Tag color="green" style={{ margin: 0, fontSize: 10, padding: '0 6px', height: 16, lineHeight: '14px' }}>在院中</Tag>
                    ) : p.has_any_inpatient_history ? (
                      <Tag style={{ margin: 0, fontSize: 10, padding: '0 6px', height: 16, lineHeight: '14px', background: '#f3f4f6', color: '#6b7280', border: '1px solid #e5e7eb' }}>已出院</Tag>
                    ) : null}
                  </Space>
                  <div style={{ fontSize: 11, color: 'var(--text-4)' }}>
                    {p.gender === 'male' ? '男' : p.gender === 'female' ? '女' : ''}
                    {p.age != null ? ` · ${p.age}岁` : ''}
                    {p.patient_no ? ` · ${p.patient_no}` : ''}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      ) : !selected ? (
        <div style={{ padding: '80px 20px', textAlign: 'center' }}>
          <UserOutlined style={{ fontSize: 40, color: 'var(--text-4)', marginBottom: 12 }} />
          <div style={{ color: 'var(--text-3)', fontSize: 13 }}>
            请先从左侧病区选择患者，才能查看其历史病历
          </div>
        </div>
      ) : loading ? (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin />
        </div>
      ) : records.length === 0 ? (
        <Empty
          description="该患者暂无已签发病历"
          style={{ padding: '60px 0' }}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      ) : (
        <List
          style={{ padding: '8px 16px' }}
          dataSource={records}
          renderItem={(record: any) => {
            const scene = getSceneTag(record.visit_type, record.visit_sequence)
            return (
              <List.Item
                style={{
                  padding: '12px 14px',
                  marginBottom: 8,
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 10,
                  transition: 'all 0.18s',
                  cursor: 'pointer',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.borderColor = '#86efac'
                  e.currentTarget.style.boxShadow = '0 2px 8px rgba(5,150,105,0.1)'
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.borderColor = 'var(--border)'
                  e.currentTarget.style.boxShadow = 'none'
                }}
                actions={[
                  <Button
                    key="view"
                    type="text"
                    size="small"
                    icon={<EyeOutlined />}
                    onClick={() => onView(record)}
                    style={{ color: '#059669' }}
                  >
                    查看
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space size={6}>
                      <Tag color={scene.color} style={{ fontSize: 11, margin: 0, fontWeight: 600 }}>
                        {scene.text}
                      </Tag>
                      <Text style={{ fontSize: 13, color: 'var(--text-2)' }}>
                        {recordTypeLabel(record.record_type)}
                      </Text>
                    </Space>
                  }
                  description={
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {record.submitted_at
                          ? new Date(record.submitted_at).toLocaleString('zh-CN')
                          : '-'}
                      </Text>
                      <div
                        style={{
                          fontSize: 12,
                          color: 'var(--text-3)',
                          marginTop: 4,
                          lineHeight: 1.5,
                        }}
                      >
                        {record.content_preview || '（无内容预览）'}
                      </div>
                    </div>
                  }
                />
              </List.Item>
            )
          }}
        />
      )}
    </Drawer>
  )
}
