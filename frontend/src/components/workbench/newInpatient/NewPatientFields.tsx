/**
 * 新患者完整字段（newInpatient/NewPatientFields.tsx）
 *
 * 按浙江省病案首页规范，住院全部必填：
 *   一、基本身份信息（姓名/性别/出生/身份证/民族/婚姻/血型）
 *   二、联系方式与紧急联系人
 *   三、家庭住址 + 职业 + 工作单位
 */
import { Form, Input, Select, DatePicker } from 'antd'
import dayjs from 'dayjs'
import SectionLabel from './SectionLabel'
import { ETHNICITY_OPTIONS } from './constants'

export default function NewPatientFields() {
  return (
    <>
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

      <Form.Item
        name="id_card"
        label={
          <span>
            身份证号 <span style={{ color: '#ef4444', fontSize: 11 }}>（信息错误为单项否决）</span>
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
        <Form.Item
          name="ethnicity"
          label="民族"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请选择民族' }]}
        >
          <Select placeholder="民族" showSearch>
            {ETHNICITY_OPTIONS.map(e => (
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
          <Select placeholder="婚姻">
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

      <SectionLabel text="二、联系方式与紧急联系人" />
      <div style={{ display: 'flex', gap: 10 }}>
        <Form.Item name="phone" label="本人电话" style={{ flex: 1 }}>
          <Input placeholder="手机号（选填）" />
        </Form.Item>
        <Form.Item
          name="contact_name"
          label="紧急联系人"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请输入紧急联系人姓名' }]}
        >
          <Input placeholder="联系人姓名" />
        </Form.Item>
        <Form.Item
          name="contact_relation"
          label="与患者关系"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请选择与患者关系' }]}
        >
          <Select placeholder="关系">
            {['配偶', '父母', '子女', '兄弟姐妹', '其他亲属', '朋友', '其他'].map(r => (
              <Select.Option key={r} value={r}>
                {r}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item
          name="contact_phone"
          label="联系人电话"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请输入联系人电话' }]}
        >
          <Input placeholder="联系人手机" />
        </Form.Item>
      </div>
      <Form.Item
        name="address"
        label="家庭住址"
        rules={[{ required: true, message: '请输入家庭住址' }]}
      >
        <Input placeholder="详细家庭地址" />
      </Form.Item>
      <div style={{ display: 'flex', gap: 10 }}>
        <Form.Item
          name="occupation"
          label="职业"
          style={{ flex: 1 }}
          rules={[{ required: true, message: '请输入职业' }]}
        >
          <Input placeholder="如：教师、农民、工人" />
        </Form.Item>
        <Form.Item
          name="workplace"
          label="工作单位"
          style={{ flex: 2 }}
          rules={[{ required: true, message: '请输入工作单位' }]}
        >
          <Input placeholder="工作单位（无业/退休可填无）" />
        </Form.Item>
      </div>
    </>
  )
}
