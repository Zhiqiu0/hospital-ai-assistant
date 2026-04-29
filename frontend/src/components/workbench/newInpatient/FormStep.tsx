/**
 * 住院新建接诊：表单步骤（newInpatient/FormStep.tsx）
 *
 * 选中已有患者：只展示信息卡片 + 入院信息（不再重复采集档案字段）
 * 新患者：完整字段 + 入院信息
 *
 * 入院信息（床位号 / 入院途径 / 入院病情）属于当次接诊属性，
 * 选中已有患者也要填。
 */
import { Form, Input, Select } from 'antd'
import SectionLabel from './SectionLabel'
import SelectedPatientCard from './SelectedPatientCard'
import NewPatientFields from './NewPatientFields'

interface FormStepProps {
  form: any
  selectedPatient: any | null
  onFinish: (values: any) => void
}

export default function FormStep({ form, selectedPatient, onFinish }: FormStepProps) {
  return (
    <Form form={form} layout="vertical" onFinish={onFinish} style={{ marginTop: 16 }} size="small">
      {selectedPatient ? <SelectedPatientCard patient={selectedPatient} /> : <NewPatientFields />}

      <SectionLabel text={selectedPatient ? '入院信息' : '三、入院信息'} />
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
    </Form>
  )
}
