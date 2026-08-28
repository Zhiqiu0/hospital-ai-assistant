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
import type { Dayjs } from 'dayjs'
import { UserOutlined } from '@ant-design/icons'
import api from '@/services/api'
import { message } from '@/services/messageBridge'
import type { Patient } from '@/domain/medical'
import { applyQuickStartResult } from '@/store/encounterIntake'
import SearchStep from './newInpatient/SearchStep'
import FormStep from './newInpatient/FormStep'
import { ACCENT } from './newInpatient/constants'

/** /encounters/quick-start 返回的最小载荷形状 */
interface QuickStartResult {
  encounter_id: string
  patient: Patient
  [key: string]: unknown
}

/** 住院新建表单的字段集合（与 FormStep 内的 antd Form 字段一一对应） */
interface NewInpatientFormValues {
  bed_no?: string
  admission_route: string
  admission_condition: string
  patient_name?: string
  gender?: 'male' | 'female' | 'unknown'
  birth_date?: Dayjs | null
  id_card?: string
  phone?: string
  address?: string
  ethnicity?: string
  marital_status?: string
  occupation?: string
  workplace?: string
  contact_name?: string
  contact_phone?: string
  contact_relation?: string
  blood_type?: string
}

interface Props {
  open: boolean
  onClose: () => void
  onSuccess: (res: QuickStartResult) => void
}

export default function NewInpatientEncounterModal({ open, onClose, onSuccess }: Props) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  // 步骤：先搜患者（与门诊一致，避免门诊→住院时重复建档），再填表
  const [step, setStep] = useState<'search' | 'form'>('search')
  const [keyword, setKeyword] = useState('')
  const [results, setResults] = useState<Patient[]>([])
  const [searching, setSearching] = useState(false)
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 患者搜索乱序守卫序号（见 handleSearch 注释）
  const searchSeqRef = useRef(0)

  // 弹窗每次打开都重置状态，避免上次的 step / 选中态残留
  useEffect(() => {
    if (open) {
      setStep('search')
      setKeyword('')
      setResults([])
      setSelectedPatient(null)
      // 注意：住院端默认走 'search' 步骤，此时 <Form> 没挂载，调 form.resetFields()
      // 会触发 "Instance created by useForm is not connected to any Form element" 警告。
      // 切到 form 步骤的两处入口（line 225 / 选中已有患者）都已显式 resetFields。
    }
  }, [open, form])

  const handleClose = () => {
    // 关闭时 form 实例可能已被回收，避免在 Form 未挂载场景触发 useForm 警告
    if (step === 'form') {
      form.resetFields()
    }
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
    // 乱序守卫（2026-08-28 弱网审计）：先发的慢响应后到不得覆盖新关键词结果
    const seq = ++searchSeqRef.current
    debounceRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const res = (await api.get(`/patients?keyword=${encodeURIComponent(kw)}&page_size=8`)) as {
          items?: Patient[]
        }
        if (seq !== searchSeqRef.current) return
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
    setStep('form')
  }

  const handleSubmit = async (values: NewInpatientFormValues) => {
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
      let res: QuickStartResult
      try {
        res = (await api.post('/encounters/quick-start', payload)) as QuickStartResult
      } catch (err) {
        // 仅"网络瞬断"才延后 3s 重试一次，HTTP 错误直接抛（2026-08-11 审计修复，
        // 与门诊 modal 一致）：拦截器对 HTTP 错误 reject 带 status 的对象，网络错误无。
        const e = err as { status?: number }
        // 自动重发仅限老患者（2026-08-28 弱网审计收紧，与门诊 modal 一致）：
        // 新患者无去重键，"请求已到达、响应丢失"时重发会重复建档
        if (e?.status == null && 'patient_id' in payload) {
          await new Promise(r => setTimeout(r, 3000))
          res = (await api.post('/encounters/quick-start', payload)) as QuickStartResult
        } else {
          if (e?.status == null) {
            message.warning(
              '网络异常，本次创建结果未知——请先搜索该患者确认是否已建档，再决定是否重试'
            )
          }
          throw err
        }
      }
      // 同步患者档案到本地缓存（profile 字段跟随患者）
      // applyQuickStartResult 接收 EncounterIntakePayload，QuickStartResult 是兼容超集
      applyQuickStartResult(res as Parameters<typeof applyQuickStartResult>[0])
      onSuccess(res)
      handleClose()
    } catch (err) {
      // 业务错误提示（2026-08-11 审计修复）：原先只有 finally 无 catch，400/409 等
      // 会静默失败并逃逸为 unhandled rejection。提取后端 detail 提示，弹窗保持打开供重试。
      const detail = (err as { detail?: unknown })?.detail
      if (typeof detail === 'string') message.error(`办理入院失败：${detail}`)
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
        <FormStep
          form={form}
          selectedPatient={selectedPatient}
          // antd Form 不能在类型层校验字段集合，FormStep 接到 unknown 后由本组件断言成
          // NewInpatientFormValues（字段名与 FormStep 内部 Form.Item 的 name 一一对应）
          onFinish={values => handleSubmit(values as NewInpatientFormValues)}
        />
      )}
    </Modal>
  )
}
