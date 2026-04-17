/**
 * 住院工作台页面（pages/InpatientWorkbenchPage.tsx）
 *
 * 住院接诊专用工作台，相比门诊有以下差异：
 *   - 问诊面板：InpatientInquiryPanel（含入院诊断、体征等住院专属字段）
 *   - 病历类型默认：inpatient
 *   - 续接诊列表：visitTypeFilter='inpatient'，只加载住院类接诊
 *   - 布局增加「病程记录」标签页（Progress Notes）
 *
 * 与 WorkbenchPage 的关系：
 *   住院工作台独立实现（非 mode prop 复用），
 *   因字段结构差异较大（主页布局、问诊面板均不同）。
 */
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
  message,
  Avatar,
  Divider,
  Empty,
} from 'antd'
import {
  LogoutOutlined,
  UserOutlined,
  PlusOutlined,
  MedicineBoxOutlined,
  CameraOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '@/store/authStore'
import { useWorkbenchStore } from '@/store/workbenchStore'
import { useWorkbenchBase } from '@/hooks/useWorkbenchBase'
import InpatientInquiryPanel from '@/components/workbench/InpatientInquiryPanel'
import RecordEditor from '@/components/workbench/RecordEditor'
import AISuggestionPanel from '@/components/workbench/AISuggestionPanel'
import ImagingUploadModal from '@/components/workbench/ImagingUploadModal'
import HistoryDrawer from '@/components/workbench/HistoryDrawer'
import ResumeDrawer from '@/components/workbench/ResumeDrawer'
import RecordViewModal from '@/components/workbench/RecordViewModal'
import api from '@/services/api'

const { Header, Content } = Layout
const { Text } = Typography

const ACCENT = '#059669'

const RECORD_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊病历',
  admission_note: '入院记录',
  first_course_record: '首次病程',
  course_record: '日常病程',
  senior_round: '上级查房',
  discharge_record: '出院记录',
}

export default function InpatientWorkbenchPage() {
  const { user } = useAuthStore()
  const { currentPatient, currentEncounterId, setCurrentEncounter, setRecordType, reset } =
    useWorkbenchStore()

  useEffect(() => {
    setRecordType('admission_note')
  }, [])

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
    visitTypeFilter: 'inpatient',
    defaultRecordType: 'admission_note',
    resumeSuccessMsg: name => `已恢复「${name}」的住院接诊工作台`,
    resumeErrorMsg: '恢复住院接诊失败，请重试',
  })

  const [modalOpen, setModalOpen] = useState(false)
  const [imagingOpen, setImagingOpen] = useState(false)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const handleNewEncounter = async (values: any) => {
    setLoading(true)
    try {
      const payload = {
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
      setRecordType('admission_note')
      setCurrentEncounter(
        { id: res.patient.id, name: res.patient.name, gender: res.patient.gender, age: values.age },
        res.encounter_id
      )
      message.success({ content: `已为「${res.patient.name}」开始住院接诊`, key: 'retry' })
      setModalOpen(false)
      form.resetFields()
    } catch {
      message.destroy('retry')
      message.error('创建住院接诊失败，请稍后重试')
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
        {/* Top accent stripe — green for inpatient */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: 3,
            background: 'linear-gradient(90deg, #065f46, #059669, #34d399)',
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
              background: 'linear-gradient(135deg, #065f46, #059669)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 2px 8px rgba(5,150,105,0.35)',
            }}
          >
            <MedicineBoxOutlined style={{ color: '#fff', fontSize: 16 }} />
          </div>
          <Text strong style={{ fontSize: 16, color: 'var(--text-1)', letterSpacing: '-0.4px' }}>
            MediScribe
          </Text>
          <Tag color="green" style={{ margin: 0, borderRadius: 20 }}>
            住院部
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
                住院 #{currentEncounterId?.slice(-6).toUpperCase()}
              </Text>
            </div>
          ) : (
            <Text style={{ fontSize: 13, color: 'var(--text-4)' }}>未选择患者</Text>
          )}
          <Button
            icon={<PlusOutlined />}
            size="small"
            onClick={() => setModalOpen(true)}
            style={{
              borderRadius: 20,
              fontSize: 12,
              height: 30,
              paddingInline: 14,
              background: ACCENT,
              borderColor: ACCENT,
              color: '#fff',
            }}
          >
            新建住院接诊
          </Button>
        </div>

        {/* Right: user actions */}
        <Space size={4}>
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
                background: 'linear-gradient(135deg, #065f46, #34d399)',
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
        {/* Left: Inpatient Inquiry */}
        <div
          style={{
            width: 320,
            background: '#fff',
            borderRadius: 12,
            border: '1px solid var(--border)',
            overflow: 'auto',
            flexShrink: 0,
            boxShadow: 'var(--shadow-sm)',
          }}
        >
          <InpatientInquiryPanel />
        </div>

        {/* Center: Record editor */}
        <div style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
          <RecordEditor />
        </div>

        {/* Right: AI suggestions */}
        <div
          style={{
            width: 364,
            background: '#fff',
            borderRadius: 12,
            border: '1px solid var(--border)',
            overflow: 'auto',
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
                background: 'linear-gradient(135deg, #065f46, #059669)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <UserOutlined style={{ color: '#fff', fontSize: 13 }} />
            </div>
            <span>新建住院接诊</span>
          </Space>
        }
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false)
          form.resetFields()
        }}
        onOk={() => form.submit()}
        confirmLoading={loading}
        okText="开始住院接诊"
        okButtonProps={{ style: { background: ACCENT, borderColor: ACCENT } }}
        width={660}
        styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleNewEncounter}
          style={{ marginTop: 16 }}
          size="small"
        >
          {/* ── 一、基本身份信息 ── */}
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: '#065f46',
              background: '#f0fdf4',
              padding: '3px 8px',
              borderRadius: 4,
              marginBottom: 10,
            }}
          >
            一、基本身份信息
          </div>

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
              name="age"
              label="年龄"
              style={{ flex: 1 }}
              rules={[{ required: true, message: '请输入年龄' }]}
            >
              <Input type="number" placeholder="岁" min={0} max={150} suffix="岁" />
            </Form.Item>
          </div>

          <Form.Item
            name="id_card"
            label={
              <span>
                身份证号{' '}
                <span style={{ color: '#ef4444', fontSize: 11 }}>（信息错误为单项否决）</span>
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
            <Form.Item name="ethnicity" label="民族" style={{ flex: 1 }}>
              <Select placeholder="民族" allowClear showSearch>
                {[
                  '汉族',
                  '回族',
                  '满族',
                  '壮族',
                  '藏族',
                  '维吾尔族',
                  '苗族',
                  '彝族',
                  '土家族',
                  '蒙古族',
                  '其他',
                ].map(e => (
                  <Select.Option key={e} value={e}>
                    {e}
                  </Select.Option>
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
                {['配偶', '父母', '子女', '兄弟姐妹', '其他亲属', '朋友', '其他'].map(r => (
                  <Select.Option key={r} value={r}>
                    {r}
                  </Select.Option>
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
            三、入院信息
          </div>

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
                <Select.Option value="急诊">急诊</Select.Option>
                <Select.Option value="门诊">门诊</Select.Option>
                <Select.Option value="其他医疗机构转入">其他医疗机构转入</Select.Option>
                <Select.Option value="其他">其他</Select.Option>
              </Select>
            </Form.Item>
            <Form.Item
              name="admission_condition"
              label="入院病情"
              style={{ flex: 1 }}
              rules={[{ required: true, message: '请选择入院病情' }]}
            >
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

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        records={historyRecords}
        loading={historyLoading}
        onView={setViewRecord}
        accentColor={ACCENT}
        tagColor="green"
        recordTypeLabel={t => RECORD_TYPE_LABEL[t] || t}
      />

      <ResumeDrawer
        open={resumeOpen}
        onClose={() => setResumeOpen(false)}
        list={resumeList}
        loading={resumeLoading}
        onResume={handleResume}
        accentColor={ACCENT}
        title="进行中住院接诊"
        emptyText="暂无进行中住院接诊"
        fixedTag={{ color: 'green', label: '住院' }}
      />

      <RecordViewModal
        record={viewRecord}
        onClose={() => setViewRecord(null)}
        accentColor={ACCENT}
        tagColor="green"
        recordTypeLabel={t => RECORD_TYPE_LABEL[t] || t}
      />

      <ImagingUploadModal open={imagingOpen} onClose={() => setImagingOpen(false)} />
    </Layout>
  )
}
