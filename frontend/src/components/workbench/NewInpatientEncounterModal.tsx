/**
 * 新建住院接诊弹窗（components/workbench/NewInpatientEncounterModal.tsx）
 *
 * 与门诊 NewEncounterModal 结构对齐：
 *   step='search' 先搜索已有患者（按姓名/患者编号），命中直接复用，避免重复建档
 *   step='form'   未命中或主动新建时填写完整患者信息 + 入院信息
 *
 * 与门诊一致的字段：姓名 / 性别 / 出生日期（DatePicker，统一存 birth_date）
 *                    身份证号 / 手机号 / 民族 / 婚姻 / 职业 / 工作单位 / 住址
 * 住院专属字段：血型 / 紧急联系人三件套 / 床位号 / 入院途径 / 入院病情
 *
 * 必填规则（病案首页规范）：
 *   姓名 + 性别 + 出生日期 + 身份证号(18位) + 民族 + 婚姻 + 职业 + 工作单位
 *   + 住址 + 紧急联系人姓名/关系/电话 + 入院途径 + 入院病情
 */
import { useEffect, useRef, useState } from 'react'
import {
  Avatar,
  Button,
  DatePicker,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
} from 'antd'
import { PlusOutlined, UserOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '@/services/api'
import { applyQuickStartResult } from '@/store/encounterIntake'

const ACCENT = '#059669'

const SectionLabel = ({ text }: { text: string }) => (
  <div
    style={{
      fontSize: 11,
      fontWeight: 700,
      color: '#065f46',
      background: '#f0fdf4',
      padding: '3px 8px',
      borderRadius: 4,
      marginBottom: 10,
      marginTop: 4,
    }}
  >
    {text}
  </div>
)

interface Props {
  open: boolean
  onClose: () => void
  onSuccess: (res: any) => void
}

// 民族选项（与门诊保持一致）
const ETHNICITY_OPTIONS = [
  '汉族',
  '满族',
  '回族',
  '苗族',
  '维吾尔族',
  '土家族',
  '彝族',
  '蒙古族',
  '藏族',
  '壮族',
  '布依族',
  '侗族',
  '瑶族',
  '白族',
  '朝鲜族',
  '哈尼族',
  '黎族',
  '哈萨克族',
  '傣族',
  '畲族',
  '其他',
]

export default function NewInpatientEncounterModal({ open, onClose, onSuccess }: Props) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  // 步骤：先搜患者（与门诊一致，避免门诊→住院时重复建档），再填表
  const [step, setStep] = useState<'search' | 'form'>('search')
  const [keyword, setKeyword] = useState('')
  const [results, setResults] = useState<any[]>([])
  const [searching, setSearching] = useState(false)
  const [selectedPatient, setSelectedPatient] = useState<any | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 弹窗每次打开都重置状态，避免上次的 step / 选中态残留
  useEffect(() => {
    if (open) {
      setStep('search')
      setKeyword('')
      setResults([])
      setSelectedPatient(null)
      form.resetFields()
    }
  }, [open, form])

  const handleClose = () => {
    form.resetFields()
    onClose()
  }

  // 防抖搜索：参考门诊 NewEncounterModal，通过 /patients?keyword= 模糊匹配
  const handleSearch = (kw: string) => {
    setKeyword(kw)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!kw.trim()) {
      setResults([])
      return
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const res = await api.get(`/patients?keyword=${encodeURIComponent(kw)}&page_size=8`)
        setResults((res as any).items || [])
      } catch {
        setResults([])
      } finally {
        setSearching(false)
      }
    }, 300)
  }

  const selectPatient = (p: any) => {
    setSelectedPatient(p)
    setStep('form')
  }

  const handleSubmit = async (values: any) => {
    setLoading(true)
    try {
      // 选中已有患者：仅传 patient_id + 入院信息，不重复传患者档案字段
      // 新建患者：传完整字段，birth_date 用 YYYY-MM-DD（后端不再接受 age）
      const payload = selectedPatient
        ? {
            patient_id: selectedPatient.id,
            patient_name: selectedPatient.name,
            visit_type: 'inpatient',
            bed_no: values.bed_no || undefined,
            admission_route: values.admission_route,
            admission_condition: values.admission_condition,
          }
        : {
            patient_name: values.patient_name,
            gender: values.gender || 'unknown',
            birth_date: values.birth_date ? values.birth_date.format('YYYY-MM-DD') : undefined,
            id_card: values.id_card || undefined,
            phone: values.phone || undefined,
            address: values.address || undefined,
            ethnicity: values.ethnicity || undefined,
            marital_status: values.marital_status || undefined,
            occupation: values.occupation || undefined,
            workplace: values.workplace || undefined,
            contact_name: values.contact_name || undefined,
            contact_phone: values.contact_phone || undefined,
            contact_relation: values.contact_relation || undefined,
            blood_type: values.blood_type || undefined,
            visit_type: 'inpatient',
            bed_no: values.bed_no || undefined,
            admission_route: values.admission_route,
            admission_condition: values.admission_condition,
          }
      let res: any
      try {
        res = await api.post('/encounters/quick-start', payload)
      } catch (err: any) {
        // 网络瞬断重试一次（与门诊 modal 一致），减少现场误触
        if (!err?.response) {
          await new Promise(r => setTimeout(r, 3000))
          res = await api.post('/encounters/quick-start', payload)
        } else throw err
      }
      // 同步患者档案到本地缓存（profile 字段跟随患者）
      applyQuickStartResult(res)
      onSuccess(res)
      handleClose()
    } finally {
      setLoading(false)
    }
  }

  const titleText = step === 'search' ? '新建住院接诊' : selectedPatient ? '住院接诊确认' : '新建住院接诊'

  return (
    <Modal
      open={open}
      onCancel={handleClose}
      title={
        <Space>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              background: `linear-gradient(135deg, #065f46, ${ACCENT})`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <UserOutlined style={{ color: 'var(--surface)', fontSize: 13 }} />
          </div>
          <span>{titleText}</span>
        </Space>
      }
      footer={
        step === 'search' ? (
          <Button onClick={handleClose}>取消</Button>
        ) : (
          <Space>
            <Button onClick={() => setStep('search')}>← 返回</Button>
            <Button onClick={handleClose}>取消</Button>
            <Button
              type="primary"
              onClick={() => form.submit()}
              loading={loading}
              style={{ background: ACCENT, borderColor: ACCENT }}
            >
              开始住院接诊
            </Button>
          </Space>
        )
      }
      width={selectedPatient ? 520 : 720}
      styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
    >
      {step === 'search' && (
        <SearchStep
          keyword={keyword}
          onSearch={handleSearch}
          searching={searching}
          results={results}
          onSelect={selectPatient}
          onCreateNew={() => {
            setSelectedPatient(null)
            form.resetFields()
            setStep('form')
          }}
        />
      )}
      {step === 'form' && (
        <FormStep
          form={form}
          selectedPatient={selectedPatient}
          onFinish={handleSubmit}
        />
      )}
    </Modal>
  )
}

// ── 子组件：搜索步骤 ─────────────────────────────────────────────────────────
interface SearchStepProps {
  keyword: string
  onSearch: (kw: string) => void
  searching: boolean
  results: any[]
  onSelect: (p: any) => void
  onCreateNew: () => void
}

function SearchStep({ keyword, onSearch, searching, results, onSelect, onCreateNew }: SearchStepProps) {
  return (
    <div style={{ paddingTop: 16 }}>
      <Input.Search
        placeholder="输入姓名或患者编号搜索已有患者..."
        value={keyword}
        onChange={e => onSearch(e.target.value)}
        size="large"
        autoFocus
        allowClear
        onClear={() => onSearch('')}
      />
      {searching && (
        <div style={{ textAlign: 'center', padding: '16px 0' }}>
          <Spin size="small" />
        </div>
      )}
      {!searching && results.length > 0 && (
        <div
          style={{
            marginTop: 10,
            border: '1px solid var(--border)',
            borderRadius: 8,
            overflow: 'hidden',
          }}
        >
          {results.map((p, i) => (
            <div
              key={p.id}
              onClick={() => onSelect(p)}
              style={{
                padding: '10px 14px',
                cursor: 'pointer',
                borderTop: i > 0 ? '1px solid var(--border-subtle)' : undefined,
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => {
                ;(e.currentTarget as HTMLDivElement).style.background = 'var(--surface-2)'
              }}
              onMouseLeave={e => {
                ;(e.currentTarget as HTMLDivElement).style.background = ''
              }}
            >
              <Avatar size={32} style={{ background: ACCENT, flexShrink: 0 }}>
                {p.name?.[0]}
              </Avatar>
              <div style={{ flex: 1 }}>
                <Space size={6} align="center">
                  <span style={{ fontWeight: 600, fontSize: 14 }}>{p.name}</span>
                  {/* 三态住院 Tag（与门诊端复诊搜索、历史病历抽屉保持一致）：
                      住院端搜患者时尤其有意义——
                        在院中 → 不该再开新住院接诊（已经在住），应去病区找
                        已出院 → 旧患者再次入院，正常新建
                        无 Tag → 纯门诊或新患者 */}
                  {p.has_active_inpatient ? (
                    <Tag color="green" style={{ margin: 0, fontSize: 10, padding: '0 6px', height: 16, lineHeight: '14px' }}>在院中</Tag>
                  ) : p.has_any_inpatient_history ? (
                    <Tag style={{ margin: 0, fontSize: 10, padding: '0 6px', height: 16, lineHeight: '14px', background: '#f3f4f6', color: '#6b7280', border: '1px solid #e5e7eb' }}>已出院</Tag>
                  ) : null}
                </Space>
                <div style={{ fontSize: 12, color: 'var(--text-3)' }}>
                  {p.gender === 'male' ? '男' : p.gender === 'female' ? '女' : ''}
                  {p.age ? ` · ${p.age}岁` : ''}
                  {p.phone ? ` · ${p.phone}` : ''}
                </div>
              </div>
              <Tag color="green" style={{ flexShrink: 0 }}>
                住院复用
              </Tag>
            </div>
          ))}
        </div>
      )}
      {keyword && !searching && results.length === 0 && (
        <div
          style={{ textAlign: 'center', color: 'var(--text-4)', fontSize: 13, marginTop: 16 }}
        >
          未找到匹配患者
        </div>
      )}
      <div
        style={{
          marginTop: 20,
          paddingTop: 16,
          borderTop: '1px solid var(--border-subtle)',
          textAlign: 'center',
        }}
      >
        <Button type="dashed" icon={<PlusOutlined />} onClick={onCreateNew}>
          新患者，直接填写
        </Button>
      </div>
    </div>
  )
}

// ── 子组件：表单步骤 ─────────────────────────────────────────────────────────
interface FormStepProps {
  form: any
  selectedPatient: any | null
  onFinish: (values: any) => void
}

function FormStep({ form, selectedPatient, onFinish }: FormStepProps) {
  return (
    <Form form={form} layout="vertical" onFinish={onFinish} style={{ marginTop: 16 }} size="small">
      {/* 命中已有患者：只展示信息卡片 + 入院信息（不再重复采集档案字段） */}
      {selectedPatient ? (
        <SelectedPatientCard patient={selectedPatient} />
      ) : (
        <NewPatientFields />
      )}

      {/* 入院信息：选中已有患者也要填，因为这是当次接诊属性 */}
      <SectionLabel text={selectedPatient ? '入院信息' : '三、入院信息'} />
      <div style={{ display: 'flex', gap: 10 }}>
        <Form.Item name="bed_no" label="床位号" style={{ flex: 1 }}>
          <Input placeholder="如：内科3床" />
        </Form.Item>
        <Form.Item
          name="admission_route"
          label="入院途径"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请选择入院途径' }]}
        >
          <Select placeholder="入院途径">
            {['急诊', '门诊', '其他医疗机构转入', '其他'].map(v => (
              <Select.Option key={v} value={v}>
                {v}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item
          name="admission_condition"
          label="入院病情"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请选择入院病情' }]}
        >
          <Select placeholder="入院病情">
            {['危', '急', '一般', '不详'].map(v => (
              <Select.Option key={v} value={v}>
                {v}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
      </div>
    </Form>
  )
}

// 已选中患者展示卡片（与门诊 NewEncounterModal 风格一致）
function SelectedPatientCard({ patient }: { patient: any }) {
  return (
    <div
      style={{
        background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
        border: '1px solid #bbf7d0',
        borderRadius: 8,
        padding: '12px 14px',
        marginBottom: 16,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
      }}
    >
      <Avatar size={36} style={{ background: '#16a34a', flexShrink: 0 }}>
        {patient.name?.[0]}
      </Avatar>
      <div style={{ flex: 1 }}>
        <Space size={6}>
          <span style={{ fontWeight: 700, fontSize: 15, color: '#065f46' }}>{patient.name}</span>
          {patient.gender !== 'unknown' && (
            <span style={{ fontSize: 12, color: '#059669' }}>
              {patient.gender === 'male' ? '男' : '女'}
            </span>
          )}
          {patient.age && (
            <span style={{ fontSize: 12, color: '#059669' }}>{patient.age}岁</span>
          )}
        </Space>
        {patient.phone && (
          <div style={{ fontSize: 12, color: '#059669', marginTop: 2 }}>{patient.phone}</div>
        )}
      </div>
      <Tag color="green">住院复用</Tag>
    </div>
  )
}

// 新患者完整字段（按浙江省病案首页规范，住院全部必填）
function NewPatientFields() {
  return (
    <>
      <SectionLabel text="一、基本身份信息" />
      <div style={{ display: 'flex', gap: 10 }}>
        <Form.Item
          name="patient_name"
          label="患者姓名"
          style={{ flex: 2 }}
          rules={[{ required: true, message: '请输入患者姓名' }]}
        >
          <Input placeholder="请输入患者姓名" />
        </Form.Item>
        <Form.Item
          name="gender"
          label="性别"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请选择性别' }]}
        >
          <Select placeholder="性别">
            <Select.Option value="male">男</Select.Option>
            <Select.Option value="female">女</Select.Option>
            <Select.Option value="unknown">未知</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item
          name="birth_date"
          label="出生日期"
          style={{ flex: 2 }}
          rules={[{ required: true, message: '请选择出生日期' }]}
        >
          <DatePicker
            placeholder="请选择出生日期"
            style={{ width: '100%' }}
            format="YYYY-MM-DD"
            disabledDate={d => d && d.isAfter(dayjs())}
          />
        </Form.Item>
      </div>

      <Form.Item
        name="id_card"
        label={
          <span>
            身份证号 <span style={{ color: '#ef4444', fontSize: 11 }}>（信息错误为单项否决）</span>
          </span>
        }
        rules={[
          { required: true, message: '身份证号为必填项' },
          { pattern: /^\d{17}[\dXx]$/, message: '请输入有效的18位身份证号' },
        ]}
      >
        <Input placeholder="请输入18位身份证号" maxLength={18} />
      </Form.Item>

      <div style={{ display: 'flex', gap: 10 }}>
        <Form.Item
          name="ethnicity"
          label="民族"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请选择民族' }]}
        >
          <Select placeholder="民族" showSearch>
            {ETHNICITY_OPTIONS.map(e => (
              <Select.Option key={e} value={e}>
                {e}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item
          name="marital_status"
          label="婚姻状况"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请选择婚姻状况' }]}
        >
          <Select placeholder="婚姻">
            {['未婚', '已婚', '离婚', '丧偶'].map(v => (
              <Select.Option key={v} value={v}>
                {v}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="blood_type" label="血型" style={{ flex: 1 }}>
          <Select placeholder="血型" allowClear>
            {['A型', 'B型', 'AB型', 'O型', '未知'].map(v => (
              <Select.Option key={v} value={v}>
                {v}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
      </div>

      <SectionLabel text="二、联系方式与紧急联系人" />
      <div style={{ display: 'flex', gap: 10 }}>
        <Form.Item name="phone" label="本人电话" style={{ flex: 1 }}>
          <Input placeholder="手机号（选填）" />
        </Form.Item>
        <Form.Item
          name="contact_name"
          label="紧急联系人"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请输入紧急联系人姓名' }]}
        >
          <Input placeholder="联系人姓名" />
        </Form.Item>
        <Form.Item
          name="contact_relation"
          label="与患者关系"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请选择与患者关系' }]}
        >
          <Select placeholder="关系">
            {['配偶', '父母', '子女', '兄弟姐妹', '其他亲属', '朋友', '其他'].map(r => (
              <Select.Option key={r} value={r}>
                {r}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item
          name="contact_phone"
          label="联系人电话"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请输入联系人电话' }]}
        >
          <Input placeholder="联系人手机" />
        </Form.Item>
      </div>
      <Form.Item
        name="address"
        label="家庭住址"
        rules={[{ required: true, message: '请输入家庭住址' }]}
      >
        <Input placeholder="详细家庭地址" />
      </Form.Item>
      <div style={{ display: 'flex', gap: 10 }}>
        <Form.Item
          name="occupation"
          label="职业"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请输入职业' }]}
        >
          <Input placeholder="如：教师、农民、工人" />
        </Form.Item>
        <Form.Item
          name="workplace"
          label="工作单位"
          style={{ flex: 2 }}
          rules={[{ required: true, message: '请输入工作单位' }]}
        >
          <Input placeholder="工作单位（无业/退休可填无）" />
        </Form.Item>
      </div>
    </>
  )
}
