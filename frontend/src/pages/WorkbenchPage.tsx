import { useState, useCallback, useEffect } from 'react'
import { Layout, Button, Typography, Space, Tag, Modal, Form, Input, Select, Radio, DatePicker, message, Avatar, Divider, Drawer, List, Badge, Empty, Tabs } from 'antd'
import dayjs from 'dayjs'
import { LogoutOutlined, UserOutlined, PlusOutlined, MedicineBoxOutlined, HistoryOutlined, FileTextOutlined, EyeOutlined, CheckOutlined, ReloadOutlined, ManOutlined, WomanOutlined, PrinterOutlined, CameraOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { useWorkbenchStore } from '@/store/workbenchStore'
import InquiryPanel from '@/components/workbench/InquiryPanel'
import RecordEditor from '@/components/workbench/RecordEditor'
import AISuggestionPanel from '@/components/workbench/AISuggestionPanel'
import ImagingUploadModal from '@/components/workbench/ImagingUploadModal'
import LabReportTab from '@/components/workbench/LabReportTab'
import api from '@/services/api'

const { Header, Content } = Layout
const { Text } = Typography

const RECORD_TYPE_LABEL_PRINT: Record<string, string> = {
  outpatient: '门诊病历', admission_note: '入院记录', first_course_record: '首次病程记录',
  course_record: '日常病程记录', senior_round: '上级查房记录', discharge_record: '出院记录',
}

function printRecord(record: any) {
  const typeLabel = RECORD_TYPE_LABEL_PRINT[record.record_type] || record.record_type
  const patientDesc = [
    record.patient_name,
    record.patient_gender === 'male' ? '男' : record.patient_gender === 'female' ? '女' : '',
    record.patient_age ? `${record.patient_age}岁` : '',
  ].filter(Boolean).join(' · ')
  const signedAt = record.submitted_at ? new Date(record.submitted_at).toLocaleString('zh-CN') : ''
  const formatted = (record.content || '').replace(/\n/g, '<br>')
  const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>${typeLabel} - ${patientDesc}</title>
<style>
  body { font-family: 'PingFang SC','Microsoft YaHei',sans-serif; margin: 0; padding: 32px 48px; color: #1e293b; }
  h2 { text-align: center; font-size: 20px; margin-bottom: 4px; }
  .meta { text-align: center; font-size: 13px; color: #64748b; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 1px solid #e2e8f0; }
  .content { font-size: 14px; line-height: 2.0; white-space: pre-wrap; }
  .footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8; text-align: right; }
  @media print { body { padding: 20px 32px; } }
</style></head><body>
<h2>${typeLabel}</h2>
<div class="meta">${patientDesc}${signedAt ? `&nbsp;&nbsp;|&nbsp;&nbsp;签发时间：${signedAt}` : ''}</div>
<div class="content">${formatted}</div>
<div class="footer">MediScribe 智能病历系统 · 本病历由医生审核签发</div>
<script>window.onload = function() { window.print(); }<\/script>
</body></html>`
  const w = window.open('', '_blank')
  if (w) { w.document.write(html); w.document.close() }
}

interface WorkbenchPageProps {
  mode?: 'outpatient' | 'emergency'
}

export default function WorkbenchPage({ mode = 'outpatient' }: WorkbenchPageProps) {
  const isEmergency = mode === 'emergency'
  const accentColor = isEmergency ? '#dc2626' : '#2563eb'
  const accentLight = isEmergency ? '#ef4444' : '#3b82f6'
  const accentLighter = isEmergency ? '#fca5a5' : '#60a5fa'
  const navigate = useNavigate()
  const { user, clearAuth } = useAuthStore()
  const { currentPatient, currentEncounterId, setCurrentEncounter, setInquiry, setRecordContent, setRecordType, setFinal, reset, setVisitMeta } = useWorkbenchStore()
  // 无接诊时清空残留数据（仅在页面初次挂载时执行，避免新建接诊时的竞态问题）
  useEffect(() => {
    if (!currentEncounterId) reset()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 切换门诊/急诊页面时同步 visitType 到 store
  useEffect(() => {
    const defaultType = isEmergency ? 'emergency' : 'outpatient'
    const { currentVisitType, isFirstVisit } = useWorkbenchStore.getState()
    if (currentVisitType !== defaultType) {
      setVisitMeta(isFirstVisit, defaultType)
    }
  }, [isEmergency])

  const [modalOpen, setModalOpen] = useState(false)
  const [imagingOpen, setImagingOpen] = useState(false)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  // History drawer state
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyRecords, setHistoryRecords] = useState<any[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [viewRecord, setViewRecord] = useState<any>(null)

  // Resume encounter drawer state
  const [resumeOpen, setResumeOpen] = useState(false)
  const [resumeList, setResumeList] = useState<any[]>([])
  const [resumeLoading, setResumeLoading] = useState(false)

  const RECORD_TYPE_LABEL: Record<string, string> = {
    outpatient: '门诊病历', admission_note: '入院记录', first_course_record: '首次病程',
  }

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const data: any = await api.get('/medical-records/my')
      setHistoryRecords(data.items || [])
    } catch {
      message.error('加载历史病历失败')
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  const openHistory = () => {
    setHistoryOpen(true)
    loadHistory()
  }

  const openResume = async () => {
    setResumeOpen(true)
    setResumeLoading(true)
    try {
      const data: any = await api.get('/encounters/my')
      setResumeList(data || [])
    } catch {
      message.error('加载进行中接诊失败')
    } finally {
      setResumeLoading(false)
    }
  }

  const handleResume = async (item: any) => {
    setResumeLoading(true)
    try {
      const snapshot: any = await api.get(`/encounters/${item.encounter_id}/workspace`)
      reset()
      if (snapshot.patient) {
        setCurrentEncounter(snapshot.patient, snapshot.encounter_id)
      }
      if (snapshot.inquiry) {
        setInquiry(snapshot.inquiry)
      }
      setVisitMeta(snapshot.is_first_visit !== false, snapshot.visit_type || 'outpatient')
      if (snapshot.active_record) {
        if (snapshot.active_record.status === 'submitted') {
          setResumeOpen(false)
          message.warning('该接诊病历已签发，不可修改，请在「历史病历」中查看')
          return
        }
        setRecordType(snapshot.active_record.record_type || 'outpatient')
        setRecordContent(snapshot.active_record.content || '')
        setFinal(false)
      } else {
        setRecordType(snapshot.visit_type === 'inpatient' ? 'admission_note' : 'outpatient')
        setRecordContent('')
        setFinal(false)
      }
      message.success(`已恢复「${snapshot.patient?.name || item.patient.name}」的接诊工作台`)
      setResumeOpen(false)
    } catch {
      message.error('恢复接诊失败，请重试')
    } finally {
      setResumeLoading(false)
    }
  }

  const handleLogout = async () => {
    try { await api.post('/auth/logout') } catch (_) {}
    reset()
    clearAuth()
    navigate('/login')
  }

  const handleNewEncounter = async (values: any) => {
    setLoading(true)
    try {
      const isFirstVisit = values.visit_nature !== 'revisit'
      const birthDateStr = values.birth_date ? values.birth_date.format('YYYY-MM-DD') : undefined
      const computedAge = values.birth_date ? dayjs().diff(values.birth_date, 'year') : undefined
      const res: any = await api.post('/encounters/quick-start', {
        patient_name: values.patient_name,
        gender: values.gender || 'unknown',
        birth_date: birthDateStr,
        age: computedAge,
        phone: values.phone || undefined,
        visit_type: values.visit_type || 'outpatient',
        is_first_visit: isFirstVisit,
        ethnicity: values.ethnicity || undefined,
        marital_status: values.marital_status || undefined,
        occupation: values.occupation || undefined,
        workplace: values.workplace || undefined,
        address: values.address || undefined,
      })
      reset()
      setCurrentEncounter(
        { id: res.patient.id, name: res.patient.name, gender: res.patient.gender, age: computedAge },
        res.encounter_id
      )
      setVisitMeta(isFirstVisit, values.visit_type || 'outpatient')
      message.success(`已为「${res.patient.name}」开始接诊`)
      setModalOpen(false)
      form.resetFields()
      if (values.visit_type === 'inpatient') {
        navigate('/inpatient')
      }
    } catch {
      message.error('创建接诊失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Layout style={{ height: '100vh', background: 'var(--bg)' }}>
      {/* Header */}
      <Header style={{
        height: 58,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: '#fff',
        borderBottom: '1px solid var(--border)',
        padding: '0 20px',
        boxShadow: '0 1px 8px rgba(0,0,0,0.06)',
        zIndex: 100,
        flexShrink: 0,
        position: 'relative',
      }}>
        {/* Top accent stripe */}
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 3,
          background: `linear-gradient(90deg, ${accentColor}, ${accentLight}, ${accentLighter})`,
          borderRadius: '0 0 2px 2px',
        }} />

        {/* Logo */}
        <Space size={10}>
          <div style={{
            width: 32, height: 32, borderRadius: 9,
            background: `linear-gradient(135deg, ${accentColor}, ${accentLight})`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: `0 2px 8px ${isEmergency ? 'rgba(220,38,38,0.35)' : 'rgba(37,99,235,0.35)'}`,
          }}>
            <MedicineBoxOutlined style={{ color: '#fff', fontSize: 16 }} />
          </div>
          <Text strong style={{ fontSize: 16, color: 'var(--text-1)', letterSpacing: '-0.4px' }}>
            MediScribe
          </Text>
          <Tag color={isEmergency ? 'red' : 'blue'} style={{ margin: 0, borderRadius: 20 }}>
            {isEmergency ? '急诊部' : '门诊部'}
          </Tag>
        </Space>

        {/* Patient info (center) */}
        <div style={{ position: 'absolute', left: '50%', transform: 'translateX(-50%)', display: 'flex', alignItems: 'center', gap: 10 }}>
          {currentPatient ? (
            <>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8,
                background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
                border: '1px solid #bbf7d0',
                borderRadius: 24, padding: '5px 16px',
                boxShadow: '0 1px 4px rgba(5,150,105,0.1)',
              }}>
                <div style={{
                  width: 7, height: 7, borderRadius: '50%', background: '#22c55e',
                  boxShadow: '0 0 0 3px rgba(34,197,94,0.2)',
                  flexShrink: 0,
                }} />
                <Text style={{ fontSize: 13, fontWeight: 700, color: '#065f46' }}>
                  {currentPatient.name}
                </Text>
                {currentPatient.gender && currentPatient.gender !== 'unknown' && (
                  <Text style={{ fontSize: 12, color: '#059669' }}>
                    {currentPatient.gender === 'male' ? '男' : '女'}
                  </Text>
                )}
                {currentPatient.age && (
                  <Text style={{ fontSize: 12, color: '#059669' }}>{currentPatient.age}岁</Text>
                )}
              </div>
              <Text style={{ fontSize: 12, color: 'var(--text-4)', fontFamily: 'monospace', letterSpacing: 1 }}>
                #{currentEncounterId?.slice(-6).toUpperCase()}
              </Text>
            </>
          ) : (
            <Text style={{ fontSize: 13, color: 'var(--text-4)' }}>未选择患者</Text>
          )}
          <Button
            icon={<PlusOutlined />}
            size="small"
            type="primary"
            onClick={() => setModalOpen(true)}
            style={{ borderRadius: 20, fontSize: 12, height: 30, paddingInline: 14 }}
          >
            新建接诊
          </Button>
        </div>

        {/* Right: user actions */}
        <Space size={4} style={{ flexShrink: 0 }}>
          <Button
            icon={<ReloadOutlined />}
            size="small"
            type="text"
            onClick={openResume}
            style={{ color: 'var(--text-3)', fontSize: 12, borderRadius: 8 }}
          >
            续接诊
          </Button>
          <Button
            icon={<HistoryOutlined />}
            size="small"
            type="text"
            onClick={openHistory}
            style={{ color: 'var(--text-3)', fontSize: 12, borderRadius: 8 }}
          >
            历史病历
          </Button>
          <Button
            icon={<CameraOutlined />}
            size="small"
            type="text"
            onClick={() => setImagingOpen(true)}
            style={{ color: '#7c3aed', fontSize: 12, borderRadius: 8 }}
          >
            影像分析
          </Button>
          <Button
            size="small"
            type="text"
            onClick={() => navigate(isEmergency ? '/workbench' : '/emergency')}
            style={{ color: isEmergency ? '#2563eb' : '#dc2626', fontSize: 12, borderRadius: 8, fontWeight: 500 }}
          >
            切换至{isEmergency ? '门诊' : '急诊'}
          </Button>
          <Divider type="vertical" style={{ margin: '0 4px', borderColor: 'var(--border)' }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px', borderRadius: 8, background: 'var(--surface-2)' }}>
            <Avatar
              size={26}
              style={{ background: `linear-gradient(135deg, ${accentColor}, ${accentLighter})`, fontSize: 11, flexShrink: 0 }}
            >
              {user?.real_name?.[0]}
            </Avatar>
            <div style={{ lineHeight: 1.3 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-2)' }}>{user?.real_name}</div>
              {user?.department_name && (
                <div style={{ fontSize: 11, color: 'var(--text-4)' }}>{user.department_name}</div>
              )}
            </div>
          </div>
          <Button
            icon={<LogoutOutlined />}
            size="small"
            type="text"
            onClick={handleLogout}
            style={{ color: 'var(--text-3)', borderRadius: 8 }}
          />
        </Space>
      </Header>

      {/* Content */}
      <Content style={{ display: 'flex', overflow: 'hidden', gap: 10, padding: 10 }}>
        {/* Left: Inquiry + Lab Reports */}
        <div style={{
          width: 320,
          background: '#fff',
          borderRadius: 12,
          border: '1px solid var(--border)',
          overflow: 'hidden',
          flexShrink: 0,
          boxShadow: 'var(--shadow-sm)',
          display: 'flex',
          flexDirection: 'column',
        }}>
          <Tabs
            defaultActiveKey="inquiry"
            size="small"
            style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
            tabBarStyle={{ padding: '0 12px', marginBottom: 0, flexShrink: 0 }}
            items={[
              {
                key: 'inquiry',
                label: '问诊信息',
                children: (
                  <div style={{ height: 'calc(100vh - 116px)' }}>
                    <InquiryPanel />
                  </div>
                ),
              },
              {
                key: 'lab',
                label: '检验报告',
                children: (
                  <div style={{ height: 'calc(100vh - 116px)' }}>
                    <LabReportTab />
                  </div>
                ),
              },
            ]}
          />
        </div>

        {/* Center: Record editor */}
        <div style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
          <RecordEditor />
        </div>

        {/* Right: AI suggestions only */}
        <div style={{
          width: 320,
          background: '#fff',
          borderRadius: 12,
          border: '1px solid var(--border)',
          overflow: 'hidden',
          flexShrink: 0,
          boxShadow: 'var(--shadow-sm)',
        }}>
          <AISuggestionPanel />
        </div>
      </Content>

      {/* New encounter modal */}
      <Modal
        title={
          <Space>
            <div style={{
              width: 28, height: 28, borderRadius: 8,
              background: `linear-gradient(135deg, ${accentColor}, ${accentLight})`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <UserOutlined style={{ color: '#fff', fontSize: 13 }} />
            </div>
            <span>新建接诊</span>
          </Space>
        }
        open={modalOpen}
        onCancel={() => { setModalOpen(false); form.resetFields() }}
        onOk={() => form.submit()}
        confirmLoading={loading}
        okText="开始接诊"
        width={520}
      >
        <Form form={form} layout="vertical" onFinish={handleNewEncounter} style={{ marginTop: 20 }}>
          <Form.Item name="patient_name" label="患者姓名" rules={[{ required: true, message: '请输入患者姓名' }]}>
            <Input placeholder="请输入患者姓名" size="large" />
          </Form.Item>
          <div style={{ display: 'flex', gap: 12 }}>
            <Form.Item name="gender" label="性别" style={{ flex: 1 }} rules={[{ required: true, message: '请选择性别' }]}>
              <Select placeholder="选择性别">
                <Select.Option value="male">男</Select.Option>
                <Select.Option value="female">女</Select.Option>
                <Select.Option value="unknown">未知</Select.Option>
              </Select>
            </Form.Item>
            <Form.Item name="birth_date" label="出生日期" style={{ flex: 2 }} rules={[{ required: true, message: '请选择出生日期' }]}>
              <DatePicker
                placeholder="请选择出生日期"
                style={{ width: '100%' }}
                format="YYYY-MM-DD"
                disabledDate={(d) => d && d.isAfter(dayjs())}
              />
            </Form.Item>
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <Form.Item name="ethnicity" label="民族" style={{ flex: 1 }} rules={[{ required: true, message: '请选择民族' }]}>
              <Select placeholder="请选择民族" showSearch>
                {['汉族','满族','回族','苗族','维吾尔族','土家族','彝族','蒙古族','藏族','壮族','布依族','侗族','瑶族','白族','朝鲜族','哈尼族','黎族','哈萨克族','傣族','畲族'].map(e => (
                  <Select.Option key={e} value={e}>{e}</Select.Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item name="marital_status" label="婚姻状况" style={{ flex: 1 }} rules={[{ required: true, message: '请选择婚姻状况' }]}>
              <Select placeholder="请选择">
                <Select.Option value="未婚">未婚</Select.Option>
                <Select.Option value="已婚">已婚</Select.Option>
                <Select.Option value="离异">离异</Select.Option>
                <Select.Option value="丧偶">丧偶</Select.Option>
              </Select>
            </Form.Item>
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <Form.Item name="occupation" label="职业" style={{ flex: 1 }} rules={[{ required: true, message: '请输入职业' }]}>
              <Input placeholder="请输入职业" />
            </Form.Item>
            <Form.Item name="phone" label="联系电话" style={{ flex: 1 }}>
              <Input placeholder="选填" />
            </Form.Item>
          </div>
          <Form.Item name="workplace" label="工作单位" rules={[{ required: true, message: '请输入工作单位' }]}>
            <Input placeholder="请输入工作单位（无业/退休可填无）" />
          </Form.Item>
          <Form.Item name="address" label="住址" rules={[{ required: true, message: '请输入住址' }]}>
            <Input placeholder="请输入住址" />
          </Form.Item>
          <div style={{ display: 'flex', gap: 12 }}>
            <Form.Item name="visit_type" label="就诊类型" initialValue={isEmergency ? 'emergency' : 'outpatient'} style={{ flex: 1 }}>
              <Select>
                <Select.Option value="outpatient">门诊</Select.Option>
                <Select.Option value="inpatient">住院</Select.Option>
                <Select.Option value="emergency">急诊</Select.Option>
              </Select>
            </Form.Item>
            <Form.Item name="visit_nature" label="就诊性质" initialValue="first" style={{ flex: 1 }}>
              <Radio.Group buttonStyle="solid" optionType="button" size="small">
                <Radio.Button value="first">初诊</Radio.Button>
                <Radio.Button value="revisit">复诊</Radio.Button>
              </Radio.Group>
            </Form.Item>
          </div>
        </Form>
      </Modal>

      {/* Resume encounter drawer */}
      <Drawer
        title={
          <Space>
            <ReloadOutlined style={{ color: '#2563eb' }} />
            <span>进行中接诊</span>
            <Badge count={resumeList.length} style={{ background: '#2563eb' }} />
          </Space>
        }
        open={resumeOpen}
        onClose={() => setResumeOpen(false)}
        width={420}
        styles={{ body: { padding: '8px 0' } }}
      >
        {resumeLoading ? (
          <div style={{ textAlign: 'center', padding: '48px 0', color: '#94a3b8' }}>加载中...</div>
        ) : resumeList.length === 0 ? (
          <Empty description="暂无进行中接诊" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 60 }} />
        ) : (
          <List
            dataSource={resumeList}
            renderItem={(item: any) => (
              <List.Item
                style={{ padding: '12px 20px', cursor: 'pointer' }}
                extra={
                  <Button
                    size="small"
                    type="primary"
                    onClick={() => handleResume(item)}
                    style={{ borderRadius: 8 }}
                  >
                    恢复
                  </Button>
                }
              >
                <List.Item.Meta
                  avatar={
                    <div style={{
                      width: 38, height: 38, borderRadius: 10,
                      background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
                      border: '1px solid #bbf7d0',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      {item.patient?.gender === 'female'
                        ? <WomanOutlined style={{ color: '#ec4899', fontSize: 16 }} />
                        : <ManOutlined style={{ color: '#2563eb', fontSize: 16 }} />}
                    </div>
                  }
                  title={
                    <Space size={6}>
                      <Text strong style={{ fontSize: 14 }}>{item.patient?.name}</Text>
                      {item.patient?.age && (
                        <Text style={{ fontSize: 12, color: '#64748b' }}>{item.patient.age}岁</Text>
                      )}
                      <Tag color="blue" style={{ fontSize: 11, margin: 0 }}>
                        {item.visit_type === 'outpatient' ? '门诊' : item.visit_type === 'inpatient' ? '住院' : '急诊'}
                      </Tag>
                    </Space>
                  }
                  description={
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {item.visited_at ? new Date(item.visited_at).toLocaleString('zh-CN') : '-'}
                      </Text>
                      {item.chief_complaint_brief && (
                        <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                          {item.chief_complaint_brief}
                        </div>
                      )}
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Drawer>

      {/* History records drawer */}
      <Drawer
        title={
          <Space>
            <HistoryOutlined style={{ color: '#2563eb' }} />
            <span>历史签发病历</span>
            <Badge count={historyRecords.length} style={{ background: '#2563eb' }} />
          </Space>
        }
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        width={480}
        styles={{ body: { padding: '8px 0' } }}
      >
        {historyLoading ? (
          <div style={{ textAlign: 'center', padding: '48px 0', color: '#94a3b8' }}>加载中...</div>
        ) : historyRecords.length === 0 ? (
          <Empty description="暂无签发病历" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 60 }} />
        ) : (
          <List
            dataSource={historyRecords}
            renderItem={(record: any) => (
              <List.Item
                style={{ padding: '12px 20px', cursor: 'pointer' }}
                onClick={() => setViewRecord(record)}
                extra={
                  <Button
                    size="small" type="text"
                    icon={<EyeOutlined />}
                    style={{ color: '#2563eb' }}
                    onClick={(e) => { e.stopPropagation(); setViewRecord(record) }}
                  >
                    查看
                  </Button>
                }
              >
                <List.Item.Meta
                  avatar={
                    <div style={{
                      width: 38, height: 38, borderRadius: 10,
                      background: 'linear-gradient(135deg, #eff6ff, #dbeafe)',
                      border: '1px solid #bfdbfe',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <FileTextOutlined style={{ color: '#2563eb', fontSize: 16 }} />
                    </div>
                  }
                  title={
                    <Space size={6}>
                      <Text strong style={{ fontSize: 14 }}>{record.patient_name}</Text>
                      <Tag color="blue" style={{ fontSize: 11, margin: 0 }}>
                        {RECORD_TYPE_LABEL[record.record_type] || record.record_type}
                      </Tag>
                    </Space>
                  }
                  description={
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {record.submitted_at ? new Date(record.submitted_at).toLocaleString('zh-CN') : '-'}
                      </Text>
                      <div style={{ fontSize: 12, color: '#64748b', marginTop: 2, lineHeight: 1.4 }}>
                        {record.content_preview || '（无内容预览）'}
                      </div>
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Drawer>

      {/* View record modal */}
      <Modal
        title={
          viewRecord && (
            <Space>
              <FileTextOutlined style={{ color: '#2563eb' }} />
              <span>{viewRecord.patient_name}</span>
              <Tag color="blue">{RECORD_TYPE_LABEL[viewRecord?.record_type] || viewRecord?.record_type}</Tag>
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                {viewRecord.submitted_at ? new Date(viewRecord.submitted_at).toLocaleString('zh-CN') : ''}
              </Text>
            </Space>
          )
        }
        open={!!viewRecord}
        onCancel={() => setViewRecord(null)}
        footer={
          <Space>
            <Button icon={<PrinterOutlined />} onClick={() => printRecord(viewRecord)}>打印 / 导出PDF</Button>
            <Button type="primary" onClick={() => setViewRecord(null)}>关闭</Button>
          </Space>
        }
        width={680}
      >
        <div style={{
          background: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: 8,
          padding: '20px 24px',
          maxHeight: 520,
          overflowY: 'auto',
          fontSize: 14,
          lineHeight: 1.9,
          whiteSpace: 'pre-wrap',
          fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
          color: '#1e293b',
        }}>
          {viewRecord?.content || '（病历内容为空）'}
        </div>
        <div style={{
          marginTop: 12, padding: '8px 12px',
          background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8,
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <CheckOutlined style={{ color: '#22c55e' }} />
          <Text style={{ fontSize: 12, color: '#166534' }}>已签发病历 · 不可修改</Text>
        </div>
      </Modal>

      <ImagingUploadModal open={imagingOpen} onClose={() => setImagingOpen(false)} />
    </Layout>
  )
}
