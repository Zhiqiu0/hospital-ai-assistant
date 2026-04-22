/**
 * 新建住院接诊弹窗（components/workbench/NewInpatientEncounterModal.tsx）
 * 包含基本身份、联系方式、入院信息三节表单。
 */
import { useState } from 'react'
import { Form, Input, Modal, Select, Space } from 'antd'
import { UserOutlined } from '@ant-design/icons'
import api from '@/services/api'
import { applyQuickStartResult } from '@/store/encounterIntake'

const ACCENT = '#059669'

const SectionLabel = ({ text }: { text: string }) => (
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
    {text}
  </div>
)

interface Props {
  open: boolean
  onClose: () => void
  onSuccess: (res: any) => void
}

export default function NewInpatientEncounterModal({ open, onClose, onSuccess }: Props) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const handleClose = () => {
    form.resetFields()
    onClose()
  }

  const handleSubmit = async (values: any) => {
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
      } catch (err: any) {
        if (!err?.response) {
          await new Promise(r => setTimeout(r, 3000))
          res = await api.post('/encounters/quick-start', payload)
        } else throw err
      }
      // 1.6 数据接入：住院新建 quick-start 的 patient + profile 同步到 patientCache
      applyQuickStartResult(res)
      onSuccess(res)
      handleClose()
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      open={open}
      onCancel={handleClose}
      onOk={() => form.submit()}
      confirmLoading={loading}
      okText="开始住院接诊"
      okButtonProps={{ style: { background: ACCENT, borderColor: ACCENT } }}
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
      width={660}
      styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        style={{ marginTop: 16 }}
        size="small"
      >
        <SectionLabel text="一、基本身份信息" />
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
              {['未婚', '已婚', '离婚', '丧偶'].map(v => (
                <Select.Option key={v} value={v}>
                  {v}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="blood_type" label="血型" style={{ flex: 1 }}>
            <Select placeholder="血型" allowClear>
              {['A型', 'B型', 'AB型', 'O型', '未知'].map(v => (
                <Select.Option key={v} value={v}>
                  {v}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
        </div>

        <SectionLabel text="二、联系方式" />
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

        <SectionLabel text="三、入院信息" />
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
              {['急诊', '门诊', '其他医疗机构转入', '其他'].map(v => (
                <Select.Option key={v} value={v}>
                  {v}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item
            name="admission_condition"
            label="入院病情"
            style={{ flex: 1 }}
            rules={[{ required: true, message: '请选择入院病情' }]}
          >
            <Select placeholder="入院病情">
              {['危', '急', '一般', '不详'].map(v => (
                <Select.Option key={v} value={v}>
                  {v}
                </Select.Option>
              ))}
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
  )
}
