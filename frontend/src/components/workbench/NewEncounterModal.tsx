/**
 * 接诊弹窗（components/workbench/NewEncounterModal.tsx）
 *
 * mode='new'       初诊：直接显示新患者填写表单
 * mode='returning' 复诊：先搜索已有患者，选中后确认开始接诊
 */
import { useRef, useState, useEffect } from 'react'
import { Avatar, Button, DatePicker, Form, Input, Modal, Select, Space, Spin, Tag } from 'antd'
import { PlusOutlined, UserOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '@/services/api'

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
  }, [open, mode])

  const handleClose = () => {
    onClose()
  }

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
            age: values.birth_date ? dayjs().diff(values.birth_date, 'year') : undefined,
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
            <UserOutlined style={{ color: '#fff', fontSize: 13 }} />
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
      {/* 步骤一：搜索 */}
      {step === 'search' && (
        <div style={{ paddingTop: 16 }}>
          <Input.Search
            placeholder="输入姓名或手机号搜索已有患者..."
            value={keyword}
            onChange={e => handleSearch(e.target.value)}
            size="large"
            autoFocus
            allowClear
            onClear={() => {
              setKeyword('')
              setResults([])
            }}
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
                border: '1px solid #e2e8f0',
                borderRadius: 8,
                overflow: 'hidden',
              }}
            >
              {results.map((p, i) => (
                <div
                  key={p.id}
                  onClick={() => selectPatient(p)}
                  style={{
                    padding: '10px 14px',
                    cursor: 'pointer',
                    borderTop: i > 0 ? '1px solid #f1f5f9' : undefined,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => {
                    ;(e.currentTarget as HTMLDivElement).style.background = '#f8fafc'
                  }}
                  onMouseLeave={e => {
                    ;(e.currentTarget as HTMLDivElement).style.background = ''
                  }}
                >
                  <Avatar size={32} style={{ background: accentColor, flexShrink: 0 }}>
                    {p.name?.[0]}
                  </Avatar>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{p.name}</div>
                    <div style={{ fontSize: 12, color: '#64748b' }}>
                      {p.gender === 'male' ? '男' : p.gender === 'female' ? '女' : ''}
                      {p.age ? ` · ${p.age}岁` : ''}
                      {p.phone ? ` · ${p.phone}` : ''}
                    </div>
                  </div>
                  <Tag color={isEmergency ? 'red' : 'blue'} style={{ flexShrink: 0 }}>
                    复诊
                  </Tag>
                </div>
              ))}
            </div>
          )}
          {keyword && !searching && results.length === 0 && (
            <div style={{ textAlign: 'center', color: '#94a3b8', fontSize: 13, marginTop: 16 }}>
              未找到匹配患者
            </div>
          )}
          <div
            style={{
              marginTop: 20,
              paddingTop: 16,
              borderTop: '1px solid #f1f5f9',
              textAlign: 'center',
            }}
          >
            <Button
              type="dashed"
              icon={<PlusOutlined />}
              onClick={() => {
                setSelectedPatient(null)
                form.resetFields()
                setStep('form')
              }}
            >
              新患者，直接填写
            </Button>
          </div>
        </div>
      )}

      {/* 步骤二：表单 */}
      {step === 'form' && (
        <Form form={form} layout="vertical" onFinish={handleSubmit} style={{ marginTop: 20 }}>
          {selectedPatient ? (
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
                {selectedPatient.name?.[0]}
              </Avatar>
              <div style={{ flex: 1 }}>
                <Space size={6}>
                  <span style={{ fontWeight: 700, fontSize: 15, color: '#065f46' }}>
                    {selectedPatient.name}
                  </span>
                  {selectedPatient.gender !== 'unknown' && (
                    <span style={{ fontSize: 12, color: '#059669' }}>
                      {selectedPatient.gender === 'male' ? '男' : '女'}
                    </span>
                  )}
                  {selectedPatient.age && (
                    <span style={{ fontSize: 12, color: '#059669' }}>{selectedPatient.age}岁</span>
                  )}
                </Space>
                {selectedPatient.phone && (
                  <div style={{ fontSize: 12, color: '#059669', marginTop: 2 }}>
                    {selectedPatient.phone}
                  </div>
                )}
              </div>
              <Tag color="green">复诊</Tag>
            </div>
          ) : (
            <>
              <Form.Item
                name="patient_name"
                label="患者姓名"
                rules={[{ required: true, message: '请输入患者姓名' }]}
              >
                <Input placeholder="请输入患者姓名" size="large" />
              </Form.Item>
              <div style={{ display: 'flex', gap: 12 }}>
                <Form.Item
                  name="gender"
                  label="性别"
                  style={{ flex: 1 }}
                  rules={[{ required: true, message: '请选择性别' }]}
                >
                  <Select placeholder="选择性别">
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
              <div style={{ display: 'flex', gap: 12 }}>
                <Form.Item
                  name="ethnicity"
                  label="民族"
                  style={{ flex: 1 }}
                  rules={[{ required: true, message: '请选择民族' }]}
                >
                  <Select placeholder="请选择民族" showSearch>
                    {[
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
                    ].map(e => (
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
                  <Select placeholder="请选择">
                    {['未婚', '已婚', '离异', '丧偶'].map(v => (
                      <Select.Option key={v} value={v}>
                        {v}
                      </Select.Option>
                    ))}
                  </Select>
                </Form.Item>
              </div>
              <div style={{ display: 'flex', gap: 12 }}>
                <Form.Item
                  name="occupation"
                  label="职业"
                  style={{ flex: 1 }}
                  rules={[{ required: true, message: '请输入职业' }]}
                >
                  <Input placeholder="请输入职业" />
                </Form.Item>
                <Form.Item name="phone" label="联系电话" style={{ flex: 1 }}>
                  <Input placeholder="选填" />
                </Form.Item>
              </div>
              <Form.Item
                name="workplace"
                label="工作单位"
                rules={[{ required: true, message: '请输入工作单位' }]}
              >
                <Input placeholder="请输入工作单位（无业/退休可填无）" />
              </Form.Item>
              <Form.Item
                name="address"
                label="住址"
                rules={[{ required: true, message: '请输入住址' }]}
              >
                <Input placeholder="请输入住址" />
              </Form.Item>
            </>
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
