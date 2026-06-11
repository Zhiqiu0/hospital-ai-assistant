/**
 * 用户新建/编辑表单弹窗（pages/admin/users/UserFormModal.tsx）
 *
 * 2026-06-11 Round 5.5 拆分：从 UsersPage.tsx 抽出。
 *   - 新建模式（editUser=null）：用户名 + 初始密码 + 姓名/角色/科室 + 工号/手机号
 *   - 编辑模式（editUser 非空）：仅姓名/角色/科室（用户名不可改，密码走重置弹窗）
 *   - 提交逻辑（API 调用）仍在父组件 UsersPage 的 onSubmit 中，本组件只管表单 UI
 */
import { useEffect } from 'react'
import { Modal, Form, Input, Select } from 'antd'
import { ROLE_MAP, type UserRow, type DeptOption, type UserFormValues } from './types'

interface UserFormModalProps {
  /** 弹窗是否可见 */
  open: boolean
  /** 编辑目标用户；null = 新建模式 */
  editUser: UserRow | null
  /** 科室下拉选项 */
  departments: DeptOption[]
  /** 取消/关闭回调 */
  onCancel: () => void
  /** 表单校验通过后的提交回调（由父组件调 API） */
  onSubmit: (values: UserFormValues) => void
}

export default function UserFormModal({
  open,
  editUser,
  departments,
  onCancel,
  onSubmit,
}: UserFormModalProps) {
  const [form] = Form.useForm<UserFormValues>()

  // form.resetFields / setFieldsValue 必须等 Modal 内的 Form 挂载之后再调，
  // 否则 useForm 实例没连接到任何 Form 元素，触发
  // "Instance created by useForm is not connected to any Form element" 警告。
  // 监听 open + editUser 变化在 effect 里同步初值。
  useEffect(() => {
    if (!open) return
    if (editUser) {
      form.setFieldsValue({
        real_name: editUser.real_name,
        role: editUser.role,
        department_id: editUser.department_id ?? undefined,
      })
    } else {
      form.resetFields()
    }
  }, [open, editUser, form])

  return (
    <Modal
      title={editUser ? '编辑用户' : '新建用户'}
      open={open}
      onCancel={onCancel}
      onOk={() => form.submit()}
      okText="确认"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={onSubmit} autoComplete="off">
        {!editUser && (
          <>
            <Form.Item label="用户名" name="username" rules={[{ required: true }]}>
              <Input placeholder="登录用户名" autoComplete="off" />
            </Form.Item>
            <Form.Item label="密码" name="password" rules={[{ required: true, min: 6 }]}>
              <Input.Password placeholder="至少6位" autoComplete="new-password" />
            </Form.Item>
          </>
        )}
        <Form.Item label="姓名" name="real_name" rules={[{ required: true }]}>
          <Input placeholder="真实姓名" />
        </Form.Item>
        <Form.Item label="角色" name="role" rules={[{ required: true }]}>
          <Select
            options={Object.entries(ROLE_MAP).map(([v, r]) => ({ value: v, label: r.label }))}
          />
        </Form.Item>
        <Form.Item label="所属科室" name="department_id">
          <Select
            allowClear
            placeholder="选择科室（可选）"
            options={departments.map(d => ({ value: d.id, label: d.name }))}
          />
        </Form.Item>
        {!editUser && (
          <>
            <Form.Item label="工号" name="employee_no">
              <Input placeholder="员工编号（可选）" />
            </Form.Item>
            <Form.Item label="手机号" name="phone">
              <Input placeholder="手机号（可选）" />
            </Form.Item>
          </>
        )}
      </Form>
    </Modal>
  )
}
