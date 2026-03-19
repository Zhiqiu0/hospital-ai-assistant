import { useState, useCallback } from 'react'
import { Layout, Button, Typography, Space, Tag, Modal, Form, Input, Select, message, Avatar, Divider, Drawer, List, Badge, Empty } from 'antd'
import { LogoutOutlined, UserOutlined, PlusOutlined, MedicineBoxOutlined, HistoryOutlined, FileTextOutlined, EyeOutlined, CheckOutlined, ReloadOutlined, ManOutlined, WomanOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { useWorkbenchStore } from '@/store/workbenchStore'
import InpatientInquiryPanel from '@/components/workbench/InpatientInquiryPanel'
import RecordEditor from '@/components/workbench/RecordEditor'
import AISuggestionPanel from '@/components/workbench/AISuggestionPanel'
import api from '@/services/api'

const { Header, Content } = Layout
const { Text } = Typography

const RECORD_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊病历',
  admission_note: '入院记录',
  first_course_record: '首次病程',
  course_record: '日常病程',
  senior_round: '上级查房',
  discharge_record: '出院记录',
}

export default function InpatientWorkbenchPage() {
  const navigate = useNavigate()
  const { user, clearAuth } = useAuthStore()
  const { currentPatient, currentEncounterId, setCurrentEncounter, setInquiry, setRecordContent, setRecordType, setFinal, reset } = useWorkbenchStore()
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyRecords, setHistoryRecords] = useState<any[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [viewRecord, setViewRecord] = useState<any>(null)

  const [resumeOpen, setResumeOpen] = useState(false)
  const [resumeList, setResumeList] = useState<any[]>([])
  const [resumeLoading, setResumeLoading] = useState(false)

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
      setResumeList((data || []).filter((e: any) => e.visit_type === 'inpatient'))
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
        setRecordType(snapshot.active_record.record_type || 'admission_note')
        setRecordContent(snapshot.active_record.content || '')
        setFinal(snapshot.active_record.status === 'submitted')
      } else {
        setRecordType('admission_note')
        setRecordContent('')
        setFinal(false)
      }
      message.success(`已恢复「${snapshot.patient?.name || item.patient.name}」的住院接诊工作台`)
      setResumeOpen(false)
    } catch {
      message.error('恢复住院接诊失败，请重试')
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
        admission_route: values.admission_route || undefined,
        admission_condition: values.admission_condition || undefined,
      })
      reset()
      setCurrentEncounter(
        { id: res.patient.id, name: res.patient.name, gender: res.patient.gender, age: values.age },
        res.encounter_id
      )
      message.success(`已为「${res.patient.name}」开始住院接诊`)
      setModalOpen(false)
      form.resetFields()
    } catch {
      message.error('创建住院接诊失败，请重试')
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
        {/* Top accent stripe — green for inpatient */}
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 3,
          background: 'linear-gradient(90deg, #065f46, #059669, #34d399)',
          borderRadius: '0 0 2px 2px',
        }} />

        {/* Logo */}
        <Space size={10}>
          <div style={{
            width: 32, height: 32, borderRadius: 9,
            background: 'linear-gradient(135deg, #065f46, #059669)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 2px 8px rgba(5,150,105,0.35)',
          }}>
            <MedicineBoxOutlined style={{ color: '#fff', fontSize: 16 }} />
          </div>
          <Text strong style={{ fontSize: 16, color: 'var(--text-1)', letterSpacing: '-0.4px' }}>
            MediScribe
          </Text>
          <Tag color="green" style={{ margin: 0, borderRadius: 20 }}>住院部</Tag>
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
                住院号 #{currentEncounterId?.slice(-6).toUpperCase()}
              </Text>
            </>
          ) : (
            <Text style={{ fontSize: 13, color: 'var(--text-4)' }}>未选择患者</Text>
          )}
          <Button
            icon={<PlusOutlined />}
            size="small"
            onClick={() => setModalOpen(true)}
            style={{
              borderRadius: 20, fontSize: 12, height: 30, paddingInline: 14,
              background: '#059669', borderColor: '#059669', color: '#fff',
            }}
          >
            新建住院接诊
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
              style={{ background: 'linear-gradient(135deg, #065f46, #34d399)', fontSize: 11, flexShrink: 0 }}
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
        {/* Left: Inpatient Inquiry */}
        <div style={{
          width: 320,
          background: '#fff',
          borderRadius: 12,
          border: '1px solid var(--border)',
          overflow: 'auto',
          flexShrink: 0,
          boxShadow: 'var(--shadow-sm)',
        }}>
          <InpatientInquiryPanel />
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
              background: 'linear-gradient(135deg, #065f46, #059669)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <UserOutlined style={{ color: '#fff', fontSize: 13 }} />
            </div>
            <span>新建住院接诊</span>
          </Space>
        }
        open={modalOpen}
        onCancel={() => { setModalOpen(false); form.resetFields() }}
        onOk={() => form.submit()}
        confirmLoading={loading}
        okText="开始住院接诊"
        okButtonProps={{ style: { background: '#059669', borderColor: '#059669' } }}
        width={660}
        styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
      >
        <Form form={form} layout="vertical" onFinish={handleNewEncounter} style={{ marginTop: 16 }} size="small">

          {/* ── 一、基本身份信息 ── */}
          <div style={{ fontSize: 11, fontWeight: 700, color: '#065f46', background: '#f0fdf4', padding: '3px 8px', borderRadius: 4, marginBottom: 10 }}>
            一、基本身份信息
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            <Form.Item name="patient_name" label="患者姓名" style={{ flex: 2 }} rules={[{ required: true, message: '请输入患者姓名' }]}>
              <Input placeholder="请输入患者姓名" />
            </Form.Item>
            <Form.Item name="gender" label="性别" style={{ flex: 1 }} rules={[{ required: true, message: '请选择性别' }]}>
              <Select placeholder="性别">
                <Select.Option value="male">男</Select.Option>
                <Select.Option value="female">女</Select.Option>
                <Select.Option value="unknown">未知</Select.Option>
              </Select>
            </Form.Item>
            <Form.Item name="age" label="年龄" style={{ flex: 1 }} rules={[{ required: true, message: '请输入年龄' }]}>
              <Input type="number" placeholder="岁" min={0} max={150} suffix="岁" />
            </Form.Item>
          </div>

          <Form.Item
            name="id_card"
            label={<span>身份证号 <span style={{ color: '#ef4444', fontSize: 11 }}>（信息错误为单项否决）</span></span>}
            rules={[
              { required: true, message: '身份证号为必填项' },
              { pattern: /^\d{17}[\dXx]$/, message: '请输入有效的18位身份证号' },
            ]}
          >
            <Input placeholder="请输入18位身份证号" maxLength={18} />
          </Form.Item>

          <div style={{ display: 'flex', gap: 10 }}>
            <Form.Item name="ethnicity" label="民族" style={{ flex: 1 }}>
              <Select placeholder="民族" allowClear showSearch>
                {['汉族','回族','满族','壮族','藏族','维吾尔族','苗族','彝族','土家族','蒙古族','其他'].map(e => (
                  <Select.Option key={e} value={e}>{e}</Select.Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item name="marital_status" label="婚姻状况" style={{ flex: 1 }}>
              <Select placeholder="婚姻" allowClear>
                <Select.Option value="未婚">未婚</Select.Option>
                <Select.Option value="已婚">已婚</Select.Option>
                <Select.Option value="离婚">离婚</Select.Option>
                <Select.Option value="丧偶">丧偶</Select.Option>
              </Select>
            </Form.Item>
            <Form.Item name="blood_type" label="血型" style={{ flex: 1 }}>
              <Select placeholder="血型" allowClear>
                <Select.Option value="A型">A型</Select.Option>
                <Select.Option value="B型">B型</Select.Option>
                <Select.Option value="AB型">AB型</Select.Option>
                <Select.Option value="O型">O型</Select.Option>
                <Select.Option value="未知">未知</Select.Option>
              </Select>
            </Form.Item>
          </div>

          {/* ── 二、联系方式 ── */}
          <div style={{ fontSize: 11, fontWeight: 700, color: '#065f46', background: '#f0fdf4', padding: '3px 8px', borderRadius: 4, marginBottom: 10, marginTop: 4 }}>
            二、联系方式
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            <Form.Item name="phone" label="本人电话" style={{ flex: 1 }}>
              <Input placeholder="手机号" />
            </Form.Item>
            <Form.Item name="contact_name" label="紧急联系人" style={{ flex: 1 }}>
              <Input placeholder="联系人姓名" />
            </Form.Item>
            <Form.Item name="contact_relation" label="与患者关系" style={{ flex: 1 }}>
              <Select placeholder="关系" allowClear>
                {['配偶','父母','子女','兄弟姐妹','其他亲属','朋友','其他'].map(r => (
                  <Select.Option key={r} value={r}>{r}</Select.Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item name="contact_phone" label="联系人电话" style={{ flex: 1 }}>
              <Input placeholder="联系人手机" />
            </Form.Item>
          </div>

          <Form.Item name="address" label="家庭住址">
            <Input placeholder="详细家庭地址" />
          </Form.Item>

          {/* ── 三、入院信息 ── */}
          <div style={{ fontSize: 11, fontWeight: 700, color: '#065f46', background: '#f0fdf4', padding: '3px 8px', borderRadius: 4, marginBottom: 10, marginTop: 4 }}>
            三、入院信息
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            <Form.Item name="bed_no" label="床位号" style={{ flex: 1 }}>
              <Input placeholder="如：内科3床" />
            </Form.Item>
            <Form.Item name="admission_route" label="入院途径" style={{ flex: 1 }} rules={[{ required: true, message: '请选择入院途径' }]}>
              <Select placeholder="入院途径">
                <Select.Option value="急诊">急诊</Select.Option>
                <Select.Option value="门诊">门诊</Select.Option>
                <Select.Option value="其他医疗机构转入">其他医疗机构转入</Select.Option>
                <Select.Option value="其他">其他</Select.Option>
              </Select>
            </Form.Item>
            <Form.Item name="admission_condition" label="入院病情" style={{ flex: 1 }} rules={[{ required: true, message: '请选择入院病情' }]}>
              <Select placeholder="入院病情">
                <Select.Option value="危">危</Select.Option>
                <Select.Option value="急">急</Select.Option>
                <Select.Option value="一般">一般</Select.Option>
                <Select.Option value="不详">不详</Select.Option>
              </Select>
            </Form.Item>
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            <Form.Item name="occupation" label="职业" style={{ flex: 1 }}>
              <Input placeholder="如：教师、农民、工人" />
            </Form.Item>
            <Form.Item name="workplace" label="工作单位" style={{ flex: 2 }}>
              <Input placeholder="工作单位名称" />
            </Form.Item>
          </div>
        </Form>
      </Modal>

      {/* History records drawer */}
      <Drawer
        title={
          <Space>
            <HistoryOutlined style={{ color: '#059669' }} />
            <span>历史签发病历</span>
            <Badge count={historyRecords.length} style={{ background: '#059669' }} />
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
                    style={{ color: '#059669' }}
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
                      background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
                      border: '1px solid #bbf7d0',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <FileTextOutlined style={{ color: '#059669', fontSize: 16 }} />
                    </div>
                  }
                  title={
                    <Space size={6}>
                      <Text strong style={{ fontSize: 14 }}>{record.patient_name}</Text>
                      <Tag color="green" style={{ fontSize: 11, margin: 0 }}>
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

      {/* Resume encounter drawer */}
      <Drawer
        title={
          <Space>
            <ReloadOutlined style={{ color: '#059669' }} />
            <span>进行中住院接诊</span>
            <Badge count={resumeList.length} style={{ background: '#059669' }} />
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
          <Empty description="暂无进行中住院接诊" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 60 }} />
        ) : (
          <List
            dataSource={resumeList}
            renderItem={(item: any) => (
              <List.Item
                style={{ padding: '12px 20px', cursor: 'pointer' }}
                extra={
                  <Button
                    size="small"
                    onClick={() => handleResume(item)}
                    style={{ borderRadius: 8, background: '#059669', borderColor: '#059669', color: '#fff' }}
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
                        : <ManOutlined style={{ color: '#059669', fontSize: 16 }} />}
                    </div>
                  }
                  title={
                    <Space size={6}>
                      <Text strong style={{ fontSize: 14 }}>{item.patient?.name}</Text>
                      {item.patient?.age && (
                        <Text style={{ fontSize: 12, color: '#64748b' }}>{item.patient.age}岁</Text>
                      )}
                      <Tag color="green" style={{ fontSize: 11, margin: 0 }}>住院</Tag>
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

      {/* View record modal */}
      <Modal
        title={
          viewRecord && (
            <Space>
              <FileTextOutlined style={{ color: '#059669' }} />
              <span>{viewRecord.patient_name}</span>
              <Tag color="green">{RECORD_TYPE_LABEL[viewRecord?.record_type] || viewRecord?.record_type}</Tag>
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
