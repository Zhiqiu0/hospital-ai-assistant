/**
 * 新建住院接诊弹窗（components/workbench/NewInpatientEncounterModal.tsx）
 *
 * 与门诊 NewEncounterModal 结构对齐：
 *   step='search' 先搜索已有患者（按姓名/患者编号），命中直接复用，避免重复建档
 *   step='form'   未命中或主动新建时填写完整患者信息 + 入院信息
 *
 * 子组件已拆到 newInpatient/ 子目录：
 *   SearchStep / FormStep / SelectedPatientCard / NewPatientFields / SectionLabel
 *
 * 必填规则（病案首页规范）：
 *   姓名 + 性别 + 出生日期 + 身份证号(18位) + 民族 + 婚姻 + 职业 + 工作单位
 *   + 住址 + 紧急联系人姓名/关系/电话 + 入院途径 + 入院病情
 */
import { useEffect, useRef, useState } from 'react'
import { Button, Form, Modal, Space } from 'antd'
import { UserOutlined } from '@ant-design/icons'
import api from '@/services/api'
import { applyQuickStartResult } from '@/store/encounterIntake'
import SearchStep from './newInpatient/SearchStep'
import FormStep from './newInpatient/FormStep'
import { ACCENT } from './newInpatient/constants'

interface Props {
  open: boolean
  onClose: () => void
  onSuccess: (res: any) => void
}

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

  const titleText =
    step === 'search' ? '新建住院接诊' : selectedPatient ? '住院接诊确认' : '新建住院接诊'

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
        <FormStep form={form} selectedPatient={selectedPatient} onFinish={handleSubmit} />
      )}
    </Modal>
  )
}
