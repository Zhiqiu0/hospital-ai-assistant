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
 * 子组件：patientHistory/PatientCardHeader / PatientPickerList / RecordList
 */
import { useEffect, useState } from 'react'
import { Drawer, Empty, Space, Spin, Input, Typography } from 'antd'
import { FileTextOutlined, UserOutlined, SearchOutlined } from '@ant-design/icons'
import api from '@/services/api'
import PatientCardHeader from './patientHistory/PatientCardHeader'
import PatientPickerList from './patientHistory/PatientPickerList'
import RecordList from './patientHistory/RecordList'

const { Text: _Text } = Typography
void _Text

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
  const [selected, setSelected] = useState<SelectedPatient | null>(null)
  const [records, setRecords] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

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
  }, [
    open,
    patientId,
    patientName,
    patientGender,
    patientAge,
    searchable,
    patientHasActiveInpatient,
  ])

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
    if (!open || !searchable || selected) return
    const kw = searchKeyword.trim()
    const t = setTimeout(
      () => {
        setSearching(true)
        api
          .get(`/patients?keyword=${encodeURIComponent(kw)}&page_size=50`)
          .then((res: any) => {
            setPatientList(res?.items || [])
          })
          .catch(() => setPatientList([]))
          .finally(() => setSearching(false))
      },
      kw ? 300 : 0
    )
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
      {/* 搜索模式 + 未选中：顶部搜索框（搜索框是"过滤这个列表"语义） */}
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
      {selected && (
        <PatientCardHeader
          selected={selected}
          total={total}
          searchable={searchable}
          onChangePatient={() => setSelected(null)}
        />
      )}

      {/* 主区：未选 → 搜索列表 / 空态；已选 → 加载中 / 空记录 / 记录列表 */}
      {!selected && searchable ? (
        <div style={{ padding: '8px 12px' }}>
          <PatientPickerList
            patientList={patientList}
            searching={searching}
            searchKeyword={searchKeyword}
            onPick={handlePickPatient}
          />
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
        <RecordList records={records} onView={onView} recordTypeLabel={recordTypeLabel} />
      )}
    </Drawer>
  )
}
