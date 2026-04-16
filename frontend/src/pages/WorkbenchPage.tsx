import { useState, useEffect } from 'react'
import {
  Layout,
  Button,
  Typography,
  Space,
  Tag,
  Modal,
  Form,
  Input,
  Select,
  Radio,
  DatePicker,
  message,
  Avatar,
  Divider,
  Empty,
  Tabs,
} from 'antd'
import dayjs from 'dayjs'
import {
  LogoutOutlined,
  UserOutlined,
  PlusOutlined,
  MedicineBoxOutlined,
  CameraOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { useWorkbenchStore } from '@/store/workbenchStore'
import { useWorkbenchBase } from '@/hooks/useWorkbenchBase'
import InquiryPanel from '@/components/workbench/InquiryPanel'
import RecordEditor from '@/components/workbench/RecordEditor'
import AISuggestionPanel from '@/components/workbench/AISuggestionPanel'
import ImagingUploadModal from '@/components/workbench/ImagingUploadModal'
import HistoryDrawer from '@/components/workbench/HistoryDrawer'
import ResumeDrawer from '@/components/workbench/ResumeDrawer'
import RecordViewModal from '@/components/workbench/RecordViewModal'
import LabReportTab from '@/components/workbench/LabReportTab'
import api from '@/services/api'

const { Header, Content } = Layout
const { Text } = Typography

const RECORD_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊病历',
  admission_note: '入院记录',
  first_course_record: '首次病程记录',
  course_record: '日常病程记录',
  senior_round: '上级查房记录',
  discharge_record: '出院记录',
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
  const { user } = useAuthStore()
  const { currentPatient, currentEncounterId, setCurrentEncounter, setVisitMeta, reset } =
    useWorkbenchStore()

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

  const {
    historyOpen,
    setHistoryOpen,
    historyRecords,
    historyLoading,
    openHistory,
    viewRecord,
    setViewRecord,
    resumeOpen,
    setResumeOpen,
    resumeList,
    resumeLoading,
    openResume,
    handleResume,
    handleLogout,
  } = useWorkbenchBase({
    resumeSuccessMsg: name => `已恢复「${name}」的接诊工作台`,
  })

  const [modalOpen, setModalOpen] = useState(false)
  const [imagingOpen, setImagingOpen] = useState(false)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const handleNewEncounter = async (values: any) => {
    setLoading(true)
    try {
      const isFirstVisit = values.visit_nature !== 'revisit'
      const birthDateStr = values.birth_date ? values.birth_date.format('YYYY-MM-DD') : undefined
      const computedAge = values.birth_date ? dayjs().diff(values.birth_date, 'year') : undefined
      const payload = {
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
      }
      let res: any
      try {
        res = await api.post('/encounters/quick-start', payload)
      } catch (firstErr: any) {
        if (!firstErr?.response) {
          message.loading({ content: '连接中，正在重试...', key: 'retry', duration: 3 })
          await new Promise(r => setTimeout(r, 3000))
          res = await api.post('/encounters/quick-start', payload)
        } else {
          throw firstErr
        }
      }
      reset()
      setCurrentEncounter(
        {
          id: res.patient.id,
          name: res.patient.name,
          gender: res.patient.gender,
          age: computedAge,
        },
        res.encounter_id
      )
      setVisitMeta(isFirstVisit, values.visit_type || 'outpatient')
      message.success({ content: `已为「${res.patient.name}」开始接诊`, key: 'retry' })
      setModalOpen(false)
      form.resetFields()
      if (values.visit_type === 'inpatient') {
        navigate('/inpatient')
      }
    } catch {
      message.destroy('retry')
      message.error('创建接诊失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Layout style={{ height: '100vh', background: 'var(--bg)' }}>
      {/* Header */}
      <Header
        style={{
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
        }}
      >
        {/* Top accent stripe */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: 3,
            background: `linear-gradient(90deg, ${accentColor}, ${accentLight}, ${accentLighter})`,
            borderRadius: '0 0 2px 2px',
          }}
        />

        {/* Logo */}
        <Space size={10}>
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 9,
              background: `linear-gradient(135deg, ${accentColor}, ${accentLight})`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: `0 2px 8px ${isEmergency ? 'rgba(220,38,38,0.35)' : 'rgba(37,99,235,0.35)'}`,
            }}
          >
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
        <div
          style={{
            position: 'absolute',
            left: '50%',
            transform: 'translateX(-50%)',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          {currentPatient ? (
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
                border: '1px solid #bbf7d0',
                borderRadius: 8,
                padding: '4px 12px',
                boxShadow: '0 1px 4px rgba(5,150,105,0.1)',
                lineHeight: 1,
              }}
            >
              <div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: '#22c55e',
                  boxShadow: '0 0 0 2px rgba(34,197,94,0.25)',
                  flexShrink: 0,
                }}
              />
              <Text style={{ fontSize: 13, fontWeight: 700, color: '#065f46' }}>
                {currentPatient.name}
              </Text>
              {currentPatient.gender && currentPatient.gender !== 'unknown' && (
                <Text style={{ fontSize: 12, color: '#059669' }}>
                  {currentPatient.gender === 'male' ? '男' : '女'}
                </Text>
              )}
              {currentPatient.age != null && currentPatient.age > 0 && (
                <Text style={{ fontSize: 12, color: '#059669' }}>{currentPatient.age}岁</Text>
              )}
              <Text
                style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace', marginLeft: 4 }}
              >
                #{currentEncounterId?.slice(-6).toUpperCase()}
              </Text>
            </div>
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
            size="small"
            type="text"
            onClick={openResume}
            style={{ color: 'var(--text-3)', fontSize: 12, borderRadius: 8 }}
          >
            续接诊
          </Button>
          <Button
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
            style={{
              color: isEmergency ? '#2563eb' : '#dc2626',
              fontSize: 12,
              borderRadius: 8,
              fontWeight: 500,
            }}
          >
            切换至{isEmergency ? '门诊' : '急诊'}
          </Button>
          <Divider type="vertical" style={{ margin: '0 4px', borderColor: 'var(--border)' }} />
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '4px 10px',
              borderRadius: 8,
              background: 'var(--surface-2)',
            }}
          >
            <Avatar
              size={26}
              style={{
                background: `linear-gradient(135deg, ${accentColor}, ${accentLighter})`,
                fontSize: 11,
                flexShrink: 0,
              }}
            >
              {user?.real_name?.[0]}
            </Avatar>
            <div style={{ lineHeight: 1.3 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-2)' }}>
                {user?.real_name}
              </div>
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
      <Content
        style={{ display: 'flex', overflow: 'hidden', gap: 10, padding: 10, position: 'relative' }}
      >
        {/* Left: Inquiry + Lab Reports */}
        <div
          style={{
            width: 320,
            background: '#fff',
            borderRadius: 12,
            border: '1px solid var(--border)',
            overflow: 'hidden',
            flexShrink: 0,
            boxShadow: 'var(--shadow-sm)',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
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

        {/* Right: AI suggestions */}
        <div
          style={{
            width: 320,
            background: '#fff',
            borderRadius: 12,
            border: '1px solid var(--border)',
            overflow: 'hidden',
            flexShrink: 0,
            boxShadow: 'var(--shadow-sm)',
          }}
        >
          <AISuggestionPanel />
        </div>

        {/* No-patient overlay */}
        {!currentPatient && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              background: 'rgba(248,250,252,0.90)',
              backdropFilter: 'blur(3px)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 16,
              zIndex: 50,
              borderRadius: 8,
            }}
          >
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <span style={{ fontSize: 14, color: '#64748b' }}>
                  暂无接诊，请先新建接诊或续接诊
                </span>
              }
            />
            <Space>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setModalOpen(true)}
                size="large"
                style={{ borderRadius: 20 }}
              >
                新建接诊
              </Button>
              <Button onClick={openResume} size="large" style={{ borderRadius: 20 }}>
                续接诊
              </Button>
            </Space>
          </div>
        )}
      </Content>

      {/* New encounter modal */}
      <Modal
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
            <span>新建接诊</span>
          </Space>
        }
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false)
          form.resetFields()
        }}
        onOk={() => form.submit()}
        confirmLoading={loading}
        okText="开始接诊"
        width={520}
      >
        <Form form={form} layout="vertical" onFinish={handleNewEncounter} style={{ marginTop: 20 }}>
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
                <Select.Option value="未婚">未婚</Select.Option>
                <Select.Option value="已婚">已婚</Select.Option>
                <Select.Option value="离异">离异</Select.Option>
                <Select.Option value="丧偶">丧偶</Select.Option>
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
          <div style={{ display: 'flex', gap: 12 }}>
            <Form.Item
              name="visit_type"
              label="就诊类型"
              initialValue={isEmergency ? 'emergency' : 'outpatient'}
              style={{ flex: 1 }}
            >
              <Select>
                <Select.Option value="outpatient">门诊</Select.Option>
                <Select.Option value="inpatient">住院</Select.Option>
                <Select.Option value="emergency">急诊</Select.Option>
              </Select>
            </Form.Item>
            <Form.Item
              name="visit_nature"
              label="就诊性质"
              initialValue="first"
              style={{ flex: 1 }}
            >
              <Radio.Group buttonStyle="solid" optionType="button" size="small">
                <Radio.Button value="first">初诊</Radio.Button>
                <Radio.Button value="revisit">复诊</Radio.Button>
              </Radio.Group>
            </Form.Item>
          </div>
        </Form>
      </Modal>

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        records={historyRecords}
        loading={historyLoading}
        onView={setViewRecord}
        accentColor={accentColor}
        tagColor={isEmergency ? 'red' : 'blue'}
        recordTypeLabel={t => RECORD_TYPE_LABEL[t] || t}
      />

      <ResumeDrawer
        open={resumeOpen}
        onClose={() => setResumeOpen(false)}
        list={resumeList}
        loading={resumeLoading}
        onResume={handleResume}
        accentColor={accentColor}
      />

      <RecordViewModal
        record={viewRecord}
        onClose={() => setViewRecord(null)}
        accentColor={accentColor}
        tagColor={isEmergency ? 'red' : 'blue'}
        recordTypeLabel={t => RECORD_TYPE_LABEL[t] || t}
        showPrint
      />

      <ImagingUploadModal open={imagingOpen} onClose={() => setImagingOpen(false)} />
    </Layout>
  )
}
