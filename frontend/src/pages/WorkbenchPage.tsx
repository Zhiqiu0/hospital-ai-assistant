import { useState, useCallback } from 'react'
import { Layout, Button, Typography, Space, Tag, Modal, Form, Input, Select, message, Avatar, Divider, Drawer, List, Badge, Empty } from 'antd'
import { LogoutOutlined, UserOutlined, PlusOutlined, MedicineBoxOutlined, HistoryOutlined, FileTextOutlined, EyeOutlined, CheckOutlined, ReloadOutlined, ManOutlined, WomanOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { useWorkbenchStore } from '@/store/workbenchStore'
import InquiryPanel from '@/components/workbench/InquiryPanel'
import RecordEditor from '@/components/workbench/RecordEditor'
import AISuggestionPanel from '@/components/workbench/AISuggestionPanel'
import api from '@/services/api'

const { Header, Content } = Layout
const { Text } = Typography

export default function WorkbenchPage() {
  const navigate = useNavigate()
  const { user, clearAuth } = useAuthStore()
  const { currentPatient, currentEncounterId, setCurrentEncounter, setInquiry, setRecordContent, setRecordType, setFinal, reset } = useWorkbenchStore()
  const [modalOpen, setModalOpen] = useState(false)
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
      if (snapshot.active_record) {
        setRecordType(snapshot.active_record.record_type || 'outpatient')
        setRecordContent(snapshot.active_record.content || '')
        setFinal(snapshot.active_record.status === 'submitted')
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

  const handleLogout = () => {
    clearAuth()
    navigate('/login')
  }

  const handleNewEncounter = async (values: any) => {
    setLoading(true)
    try {
      const res: any = await api.post('/encounters/quick-start', {
        patient_name: values.patient_name,
        gender: values.gender || 'unknown',
        age: values.age ? Number(values.age) : undefined,
        phone: values.phone || undefined,
        visit_type: values.visit_type || 'outpatient',
      })
      reset()
      setCurrentEncounter(
        { id: res.patient.id, name: res.patient.name, gender: res.patient.gender, age: values.age },
        res.encounter_id
      )
      message.success(`已为「${res.patient.name}」开始接诊`)
      setModalOpen(false)
      form.resetFields()
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
          background: 'linear-gradient(90deg, #2563eb, #3b82f6, #60a5fa)',
          borderRadius: '0 0 2px 2px',
        }} />

        {/* Logo */}
        <Space size={10}>
          <div style={{
            width: 32, height: 32, borderRadius: 9,
            background: 'linear-gradient(135deg, #1d4ed8, #3b82f6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 2px 8px rgba(37,99,235,0.35)',
          }}>
            <MedicineBoxOutlined style={{ color: '#fff', fontSize: 16 }} />
          </div>
          <Text strong style={{ fontSize: 16, color: 'var(--text-1)', letterSpacing: '-0.4px' }}>
            MediScribe
          </Text>
          <Tag color="blue" style={{ margin: 0, borderRadius: 20 }}>门诊部</Tag>
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
        <Space size={4}>
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
          <Divider type="vertical" style={{ margin: '0 4px', borderColor: 'var(--border)' }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px', borderRadius: 8, background: 'var(--surface-2)' }}>
            <Avatar
              size={26}
              style={{ background: 'linear-gradient(135deg, #2563eb, #60a5fa)', fontSize: 11, flexShrink: 0 }}
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
        {/* Left: Inquiry */}
        <div style={{
          width: 300,
          background: '#fff',
          borderRadius: 12,
          border: '1px solid var(--border)',
          overflow: 'auto',
          flexShrink: 0,
          boxShadow: 'var(--shadow-sm)',
        }}>
          <InquiryPanel />
        </div>

        {/* Center: Record editor */}
        <div style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
          <RecordEditor />
        </div>

        {/* Right: AI suggestions */}
        <div style={{
          width: 364,
          background: '#fff',
          borderRadius: 12,
          border: '1px solid var(--border)',
          overflow: 'auto',
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
              background: 'linear-gradient(135deg, #2563eb, #3b82f6)',
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
        width={440}
      >
        <Form form={form} layout="vertical" onFinish={handleNewEncounter} style={{ marginTop: 20 }}>
          <Form.Item name="patient_name" label="患者姓名" rules={[{ required: true, message: '请输入患者姓名' }]}>
            <Input placeholder="请输入患者姓名" size="large" />
          </Form.Item>
          <div style={{ display: 'flex', gap: 12 }}>
            <Form.Item name="gender" label="性别" style={{ flex: 1 }}>
              <Select placeholder="选择性别" allowClear>
                <Select.Option value="male">男</Select.Option>
                <Select.Option value="female">女</Select.Option>
                <Select.Option value="unknown">未知</Select.Option>
              </Select>
            </Form.Item>
            <Form.Item name="age" label="年龄" style={{ flex: 1 }}>
              <Input type="number" placeholder="岁" min={0} max={150} suffix="岁" />
            </Form.Item>
          </div>
          <Form.Item name="phone" label="联系电话">
            <Input placeholder="选填" />
          </Form.Item>
          <Form.Item name="visit_type" label="就诊类型" initialValue="outpatient">
            <Select>
              <Select.Option value="outpatient">门诊</Select.Option>
              <Select.Option value="inpatient">住院</Select.Option>
              <Select.Option value="emergency">急诊</Select.Option>
            </Select>
          </Form.Item>
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
        footer={<Button onClick={() => setViewRecord(null)}>关闭</Button>}
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
    </Layout>
  )
}
