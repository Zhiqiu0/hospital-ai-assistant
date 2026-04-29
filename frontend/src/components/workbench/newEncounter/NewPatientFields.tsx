/**
 * 门诊新建患者字段（newEncounter/NewPatientFields.tsx）
 *
 * 门诊版：身份证选填（建议录入以便复诊/转住院去重），其他字段都选填。
 * 与住院 newInpatient/NewPatientFields 区别：住院全部必填，门诊宽松。
 */
import { Form, Input, Select, DatePicker } from 'antd'
import dayjs from 'dayjs'

const ETHNICITY_OPTIONS = [
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
]

export default function NewPatientFields() {
  return (
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
      {/* 身份证号：门诊选填，但建议填——是患者主索引，未来转住院时
          patient_service.find_existing 优先按身份证号去重，避免门诊→住院
          重复建档（参考 backend/app/services/patient_service.py 注释）。 */}
      <Form.Item
        name="id_card"
        label="身份证号"
        rules={[{ pattern: /^\d{17}[\dXx]$/, message: '请输入有效的18位身份证号' }]}
      >
        <Input placeholder="选填，建议录入以便复诊/转住院去重" maxLength={18} />
      </Form.Item>
      <div style={{ display: 'flex', gap: 12 }}>
        <Form.Item name="ethnicity" label="民族" style={{ flex: 1 }}>
          <Select placeholder="请选择民族（选填）" allowClear showSearch>
            {ETHNICITY_OPTIONS.map(e => (
              <Select.Option key={e} value={e}>
                {e}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="marital_status" label="婚姻状况" style={{ flex: 1 }}>
          <Select placeholder="请选择（选填）" allowClear>
            {['未婚', '已婚', '离异', '丧偶'].map(v => (
              <Select.Option key={v} value={v}>
                {v}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
      </div>
      <div style={{ display: 'flex', gap: 12 }}>
        <Form.Item name="occupation" label="职业" style={{ flex: 1 }}>
          <Input placeholder="选填" />
        </Form.Item>
        <Form.Item name="phone" label="联系电话" style={{ flex: 1 }}>
          <Input placeholder="选填" />
        </Form.Item>
      </div>
      <Form.Item name="workplace" label="工作单位">
        <Input placeholder="选填（无业/退休可填无）" />
      </Form.Item>
      <Form.Item name="address" label="住址">
        <Input placeholder="选填" />
      </Form.Item>
    </>
  )
}
