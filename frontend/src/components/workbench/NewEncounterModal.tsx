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
import { UserOutlined } from '@ant-design/icons'
import api from '@/services/api'
import SearchStep from './newEncounter/SearchStep'
import NewPatientFields from './newEncounter/NewPatientFields'
import SelectedPatientCard from './newEncounter/SelectedPatientCard'

interface Props {
  open: boolean
  onClose: () => void
  mode: 'new' | 'returning'
  isEmergency: boolean
  accentColor: string
  accentLight: string
  onSuccess: (res: any, visitType: string) => void
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
  const [results, setResults] = useState<any[]>([])
  const [searching, setSearching] = useState(false)
  const [selectedPatient, setSelectedPatient] = useState<any | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 每次弹窗打开时按当前 mode 重置所有状态，防止上次的 step 残留
  useEffect(() => {
    if (open) {
      setStep(mode === 'new' ? 'form' : 'search')
      setKeyword('')
      setResults([])
      setSelectedPatient(null)
      form.resetFields()
    }
  }, [open, mode]) // eslint-disable-line react-hooks/exhaustive-deps

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
    form.setFieldsValue({ visit_type: isEmergency ? 'emergency' : 'outpatient' })
    setStep('form')
  }

  const handleSubmit = async (values: any) => {
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
      let res: any
      try {
        res = await api.post('/encounters/quick-start', payload)
      } catch (err: any) {
        if (!err?.response) {
          await new Promise(r => setTimeout(r, 3000))
          res = await api.post('/encounters/quick-start', payload)
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
