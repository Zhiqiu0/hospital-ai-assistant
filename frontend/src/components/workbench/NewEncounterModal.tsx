/**
 * 接诊弹窗（components/workbench/NewEncounterModal.tsx）
 *
 * mode='new'       初诊：直接显示新患者填写表单
 * mode='returning' 复诊：先搜索已有患者，选中后确认开始接诊
 *
 * 子组件已拆到 newEncounter/ 子目录：
 *   SearchStep / NewPatientFields / SelectedPatientCard
 */
import { useRef, useState, useEffect } from 'react'
import { Button, Form, Modal, Select, Space } from 'antd'
import type { Dayjs } from 'dayjs'
import { UserOutlined } from '@ant-design/icons'
import api from '@/services/api'
import type { Patient, VisitType } from '@/domain/medical'
import SearchStep from './newEncounter/SearchStep'
import NewPatientFields from './newEncounter/NewPatientFields'
import SelectedPatientCard from './newEncounter/SelectedPatientCard'

/** /encounters/quick-start 返回的最小载荷形状（仅本组件用到的字段） */
interface QuickStartResult {
  encounter_id: string
  patient: Patient
  // 后端可能携带其他字段，但本组件只透传给上层 onSuccess，由上层按各自需要消费
  [key: string]: unknown
}

/** Form.onFinish 里 antd 给的字段集合：业务字段都是字符串，birth_date 是 Dayjs */
interface NewEncounterFormValues {
  visit_type?: VisitType
  patient_name?: string
  gender?: 'male' | 'female' | 'unknown'
  birth_date?: Dayjs | null
  id_card?: string
  phone?: string
  ethnicity?: string
  marital_status?: string
  occupation?: string
  workplace?: string
  address?: string
}

interface Props {
  open: boolean
  onClose: () => void
  mode: 'new' | 'returning'
  isEmergency: boolean
  accentColor: string
  accentLight: string
  onSuccess: (res: QuickStartResult, visitType: string) => void
}

export default function NewEncounterModal({
  open,
  onClose,
  mode,
  isEmergency,
  accentColor,
  accentLight,
  onSuccess,
}: Props) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [step, setStep] = useState<'search' | 'form'>('search')
  const [keyword, setKeyword] = useState('')
  const [results, setResults] = useState<Patient[]>([])
  const [searching, setSearching] = useState(false)
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 每次弹窗打开时按当前 mode 重置所有状态，防止上次的 step 残留
  useEffect(() => {
    if (open) {
      const initialStep = mode === 'new' ? 'form' : 'search'
      setStep(initialStep)
      setKeyword('')
      setResults([])
      setSelectedPatient(null)
      // 注意：form.resetFields() 必须在 Form 元素挂载时才能调用——
      //   - mode='new'：下面会渲染 <Form>，可以重置
      //   - mode='search'：先进搜索步骤，Form 没挂载；等用户点"新患者直接填写"
      //     切到 form 步骤时（见后面 onCreateNew 回调）会再 resetFields。
      // 之前这里无条件 resetFields，在复诊场景触发
      // "Instance created by useForm is not connected to any Form element" 警告。
      if (initialStep === 'form') {
        form.resetFields()
      }
    }
    // setState 在 open 变化时是预期的初始化路径
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode])

  const handleClose = () => onClose()

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
        // 复诊弹窗带 require_completed=true：后端只返回至少有 1 次完成接诊的患者，
        // 避免把"取消接诊后档案就剩个空壳"的患者误当复诊候选。
        // mode='new'（初诊登记）走查重逻辑，不需要这层过滤。
        const params = new URLSearchParams({
          keyword: kw,
          page_size: '8',
        })
        if (mode === 'returning') params.set('require_completed', 'true')
        const res = (await api.get(`/patients?${params.toString()}`)) as {
          items?: Patient[]
        }
        setResults(res.items || [])
      } catch {
        setResults([])
      } finally {
        setSearching(false)
      }
    }, 300)
  }

  const selectPatient = (p: Patient) => {
    setSelectedPatient(p)
    form.setFieldsValue({ visit_type: isEmergency ? 'emergency' : 'outpatient' })
    setStep('form')
  }

  const handleSubmit = async (values: NewEncounterFormValues) => {
    setLoading(true)
    try {
      const payload = selectedPatient
        ? {
            patient_id: selectedPatient.id,
            patient_name: selectedPatient.name,
            visit_type: values.visit_type || (isEmergency ? 'emergency' : 'outpatient'),
          }
        : {
            patient_name: values.patient_name,
            gender: values.gender || 'unknown',
            birth_date: values.birth_date ? values.birth_date.format('YYYY-MM-DD') : undefined,
            id_card: values.id_card || undefined,
            phone: values.phone || undefined,
            visit_type: values.visit_type || 'outpatient',
            ethnicity: values.ethnicity || undefined,
            marital_status: values.marital_status || undefined,
            occupation: values.occupation || undefined,
            workplace: values.workplace || undefined,
            address: values.address || undefined,
          }
      let res: QuickStartResult
      try {
        res = (await api.post('/encounters/quick-start', payload)) as QuickStartResult
      } catch (err) {
        // 网络瞬断（无 response）时延后 3s 重试一次，其他错误直接抛
        const e = err as { response?: unknown }
        if (!e?.response) {
          await new Promise(r => setTimeout(r, 3000))
          res = (await api.post('/encounters/quick-start', payload)) as QuickStartResult
        } else throw err
      }
      onSuccess(res, values.visit_type || (isEmergency ? 'emergency' : 'outpatient'))
      handleClose()
    } finally {
      setLoading(false)
    }
  }

  const titleText = mode === 'new' ? '初诊登记' : step === 'search' ? '复诊' : '复诊确认'

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
              background: `linear-gradient(135deg, ${accentColor}, ${accentLight})`,
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
            {mode === 'returning' && <Button onClick={() => setStep('search')}>← 返回</Button>}
            <Button onClick={handleClose}>取消</Button>
            <Button type="primary" onClick={() => form.submit()} loading={loading}>
              开始接诊
            </Button>
          </Space>
        )
      }
      width={520}
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
          accentColor={accentColor}
          isEmergency={isEmergency}
        />
      )}

      {step === 'form' && (
        <Form form={form} layout="vertical" onFinish={handleSubmit} style={{ marginTop: 20 }}>
          {selectedPatient ? (
            <SelectedPatientCard patient={selectedPatient} />
          ) : (
            <NewPatientFields />
          )}
          <Form.Item
            name="visit_type"
            label="就诊类型"
            initialValue={isEmergency ? 'emergency' : 'outpatient'}
          >
            <Select>
              <Select.Option value="outpatient">门诊</Select.Option>
              <Select.Option value="emergency">急诊</Select.Option>
              <Select.Option value="inpatient">住院</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      )}
    </Modal>
  )
}
