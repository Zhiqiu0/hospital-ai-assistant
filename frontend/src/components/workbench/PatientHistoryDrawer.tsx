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
  AutoComplete,
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
  onView,
  recordTypeLabel,
}: Props) {
  // 当前选中的患者——固定模式来自 props，搜索模式由内部搜索决定
  const [selected, setSelected] = useState<SelectedPatient | null>(null)
  const [records, setRecords] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  // 搜索模式状态
  const [searchKeyword, setSearchKeyword] = useState('')
  const [searchOptions, setSearchOptions] = useState<any[]>([])
  const [searching, setSearching] = useState(false)

  // props 里的 patientId 改变或抽屉打开时，同步 selected
  useEffect(() => {
    if (!open) {
      // 抽屉关闭时清空搜索模式的临时状态，下次打开是干净的
      if (searchable) {
        setSelected(null)
        setSearchKeyword('')
        setSearchOptions([])
      }
      return
    }
    if (patientId && patientName) {
      setSelected({ id: patientId, name: patientName, gender: patientGender, age: patientAge })
    } else if (!searchable) {
      setSelected(null)
    }
  }, [open, patientId, patientName, patientGender, patientAge, searchable])

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

  // 搜索框输入防抖（300ms）
  useEffect(() => {
    if (!searchable || !searchKeyword.trim()) {
      setSearchOptions([])
      return
    }
    const kw = searchKeyword.trim()
    const t = setTimeout(() => {
      setSearching(true)
      api
        .get(`/patients?keyword=${encodeURIComponent(kw)}&page_size=8`)
        .then((res: any) => {
          const items = res?.items || res || []
          setSearchOptions(
            items.map((p: any) => ({
              value: p.id,
              label: (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Avatar size={24} style={{ background: '#0891B2', fontSize: 12 }}>
                    {p.name?.[0]}
                  </Avatar>
                  <span style={{ fontSize: 13, fontWeight: 500 }}>{p.name}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-4)' }}>
                    {p.gender === 'male' ? '男' : p.gender === 'female' ? '女' : ''}
                    {p.age != null ? ` · ${p.age}岁` : ''}
                    {p.patient_no ? ` · ${p.patient_no}` : ''}
                  </span>
                </div>
              ),
              patient: p,
            }))
          )
        })
        .catch(() => setSearchOptions([]))
        .finally(() => setSearching(false))
    }, 300)
    return () => clearTimeout(t)
  }, [searchKeyword, searchable])

  const handlePickPatient = (_value: string, option: any) => {
    const p = option.patient
    setSelected({ id: p.id, name: p.name, gender: p.gender, age: p.age })
    setSearchKeyword('')
    setSearchOptions([])
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
      {/* 搜索模式：顶部搜索框 + （已选患者后可点"换患者"） */}
      {searchable && (
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
          <AutoComplete
            style={{ width: '100%' }}
            value={searchKeyword}
            onChange={setSearchKeyword}
            options={searchOptions}
            onSelect={handlePickPatient}
            notFoundContent={searching ? <Spin size="small" /> : (searchKeyword.trim() ? '未找到患者' : null)}
          >
            <Input
              prefix={<SearchOutlined style={{ color: 'var(--text-4)' }} />}
              placeholder="输入姓名 / 病案号 搜索患者"
              allowClear
              size="middle"
            />
          </AutoComplete>
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
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-1)' }}>{selected.name}</div>
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

      {/* 列表 or 空态 */}
      {!selected ? (
        <div style={{ padding: '80px 20px', textAlign: 'center' }}>
          <UserOutlined style={{ fontSize: 40, color: 'var(--text-4)', marginBottom: 12 }} />
          <div style={{ color: 'var(--text-3)', fontSize: 13 }}>
            {searchable ? '在上方搜索框输入患者姓名，查看其所有病历' : '请先从左侧病区选择患者，才能查看其历史病历'}
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
